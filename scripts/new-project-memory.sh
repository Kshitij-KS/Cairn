#!/usr/bin/env bash
# new-project-memory.sh — give a project repo its own memory tier (see templates/project-memory/README.md)
#
#   scripts/new-project-memory.sh <path-to-project-repo> [project-name]
#
# Idempotent: never overwrites an existing file. Existing client configs get a
# `<file>.team-memory.suggested` sibling and a printed merge hint instead.
set -u
set -o pipefail

CAIRN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TPL="$CAIRN_ROOT/templates/project-memory"
TARGET="${1:-}"; [ -n "$TARGET" ] || { echo "usage: $0 <path-to-project-repo> [project-name]" >&2; exit 1; }
[ -d "$TARGET" ] || { echo "ERROR: $TARGET is not a directory" >&2; exit 1; }
TARGET="$(cd "$TARGET" && pwd -P)"
git -C "$TARGET" rev-parse --show-toplevel >/dev/null 2>&1 || { echo "ERROR: $TARGET is not a git repository (git init first)" >&2; exit 1; }
[ "$(git -C "$TARGET" rev-parse --show-toplevel)" = "$TARGET" ] || { echo "ERROR: run against the repo root, not a subfolder" >&2; exit 1; }

NAME="${2:-$(basename "$TARGET" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')}"
TITLE="$(basename "$TARGET" | sed -E 's/[_-]+/ /g')"
DATE="$(date +%Y-%m-%d)"
[ "$NAME" != "cairn" ] || { echo "ERROR: project name 'cairn' is reserved" >&2; exit 1; }

created=(); skipped=(); suggested=()
render() { # render <src> <dest>  — substitute placeholders; never overwrite
  local src="$1" dest="$2"
  if [ -e "$dest" ]; then skipped+=("${dest#"$TARGET"/}"); return 0; fi
  mkdir -p "$(dirname "$dest")"
  sed -e "s/__PROJECT_NAME__/$NAME/g" -e "s/__PROJECT_TITLE__/$TITLE/g" -e "s/__DATE__/$DATE/g" \
      "$src" > "$dest"
  created+=("${dest#"$TARGET"/}")
}
render_or_suggest() { # for configs that may already exist (JSON that needs a manual merge)
  local src="$1" dest="$2" want
  if [ -e "$dest" ]; then
    # already exactly what we would write (a re-run): nothing to merge
    want="$(sed -e "s/__PROJECT_NAME__/$NAME/g" -e "s/__PROJECT_TITLE__/$TITLE/g" -e "s/__DATE__/$DATE/g" "$src")"
    if [ "$want" = "$(cat "$dest")" ]; then skipped+=("${dest#"$TARGET"/}"); return 0; fi
    render "$src" "$dest.team-memory.suggested"; suggested+=("${dest#"$TARGET"/}")
  else render "$src" "$dest"; fi
}

# 1. memory/ notes + manifest
while IFS= read -r -d '' f; do
  rel="${f#"$TPL/memory/"}"; render "$f" "$TARGET/memory/${rel%.tmpl}"
done < <(find "$TPL/memory" -type f -print0)

# 2. sync scripts + canonical skill (copied from cairn so there is one source of truth)
# memory_guard.py and mem.py were NOT copied before 2026-09-23, so the project tier ran with
# "memory_guard.py missing - policy NOT enforced" on every commit. The policy comes from cairn
# too (people and roles are company-wide); an existing project policy is left untouched.
for s in sync-memory.sh sync-memory.ps1 sync-memory.py memory_guard.py mem.py; do render "$CAIRN_ROOT/scripts/$s" "$TARGET/memory/scripts/$s"; done
render "$CAIRN_ROOT/governance/roles.json" "$TARGET/memory/governance/roles.json"
chmod +x "$TARGET/memory/scripts/sync-memory.sh" 2>/dev/null || true
render "$CAIRN_ROOT/.agents/skills/team-memory/SKILL.md" "$TARGET/memory/.agents/skills/team-memory/SKILL.md"

# 3. client configs
render            "$TPL/client-config/cursor-memory.mdc.tmpl"           "$TARGET/.cursor/rules/memory.mdc"
render            "$TPL/client-config/kiro-steering-memory.md.tmpl"     "$TARGET/.kiro/steering/memory.md"
render            "$TPL/client-config/kiro-hook-session-start.json.tmpl" "$TARGET/.kiro/hooks/memory-session-start.json"
render            "$TPL/client-config/kiro-hook-post-task.json.tmpl"    "$TARGET/.kiro/hooks/memory-post-task.json"
render_or_suggest "$TPL/client-config/kiro-mcp.json.tmpl"               "$TARGET/.kiro/settings/mcp.json"
render_or_suggest "$TPL/client-config/mcp.json.tmpl"                    "$TARGET/.mcp.json"
render_or_suggest "$TPL/client-config/cursor-mcp.json.tmpl"             "$TARGET/.cursor/mcp.json"
render_or_suggest "$TPL/client-config/claude-settings.json.tmpl"        "$TARGET/.claude/settings.json"

# 3b. the gate on GitHub: a memory-gate workflow scoped to memory/, and the memory block of
#     CODEOWNERS (the product's own code owners are never touched). Without these, any code pull
#     request could rewrite the project's features or its own roles.json unreviewed.
render_or_suggest "$TPL/client-config/memory-gate.yml.tmpl"             "$TARGET/.github/workflows/memory-gate.yml"
co_py=""; for c in python3 python py; do command -v "$c" >/dev/null 2>&1 && { co_py="$c"; break; }; done
if [ -n "$co_py" ] && co_block="$("$co_py" "$TARGET/memory/scripts/memory_guard.py" --notes-root "$TARGET/memory" codeowners --print 2>/dev/null)"; then
  if [ -e "$TARGET/.github/CODEOWNERS" ] && grep -qF "$co_block" "$TARGET/.github/CODEOWNERS" 2>/dev/null && \
     [ "$(printf '%s\n' "$co_block")" = "$(sed -n '/^# >>> cairn memory/,/^# <<< cairn memory <<</p' "$TARGET/.github/CODEOWNERS")" ]; then
    skipped+=(".github/CODEOWNERS (memory block already current)")
  elif [ -e "$TARGET/.github/CODEOWNERS" ]; then
    printf '%s\n' "$co_block" > "$TARGET/.github/CODEOWNERS.team-memory.suggested"; suggested+=(".github/CODEOWNERS (append the memory block, or run memory/scripts/memory_guard.py --notes-root memory codeowners --write)")
  else
    mkdir -p "$TARGET/.github"; printf '%s\n' "$co_block" > "$TARGET/.github/CODEOWNERS"; created+=(".github/CODEOWNERS (memory block)")
  fi
else
  skipped+=(".github/CODEOWNERS: fill the owner's GitHub login in memory/governance/roles.json, then run memory/scripts/memory_guard.py --notes-root memory codeowners --write")
fi

# 4. CLAUDE.md — append the import once
if [ -f "$TARGET/CLAUDE.md" ]; then
  if ! grep -q '@memory/AGENT-RULES.md' "$TARGET/CLAUDE.md"; then
    sed -e "s/__PROJECT_NAME__/$NAME/g" -e "s/__PROJECT_TITLE__/$TITLE/g" "$TPL/client-config/CLAUDE-snippet.md.tmpl" >> "$TARGET/CLAUDE.md"; created+=("CLAUDE.md (appended)")
  else skipped+=("CLAUDE.md (import already present)"); fi
else
  { printf '# %s\n' "$TITLE"; sed -e "s/__PROJECT_NAME__/$NAME/g" -e "s/__PROJECT_TITLE__/$TITLE/g" "$TPL/client-config/CLAUDE-snippet.md.tmpl"; } > "$TARGET/CLAUDE.md"; created+=("CLAUDE.md")
fi

# 5. skill copies for Claude Code / Kiro (the sync script keeps them fresh afterwards)
for d in .claude .kiro; do render "$TARGET/memory/.agents/skills/team-memory/SKILL.md" "$TARGET/$d/skills/team-memory/SKILL.md"; done

# 5b. slash commands (/cairn /cairn-context /cairn-recall /cairn-remember /cairn-gaps /cairn-try /cairn-feature), pointed at memory/scripts
for f in "$CAIRN_ROOT"/.claude/commands/*.md; do
  dest="$TARGET/.claude/commands/$(basename "$f")"
  if [ -e "$dest" ]; then skipped+=("${dest#"$TARGET"/}"); continue; fi
  mkdir -p "$(dirname "$dest")"; sed -e 's#scripts/mem\.py#memory/scripts/mem.py#g' "$f" > "$dest"; created+=("${dest#"$TARGET"/}")
done

# 6. register with Basic Memory
reg="skipped (basic-memory not on PATH)"
if command -v basic-memory >/dev/null 2>&1; then
  if basic-memory project list --json 2>/dev/null | grep -Eq "\"name\"[[:space:]]*:[[:space:]]*\"$NAME\""; then reg="already registered"
  elif basic-memory project add "$NAME" "$TARGET/memory" >/dev/null 2>&1; then reg="registered → $TARGET/memory"
  else reg="FAILED — run: basic-memory project add $NAME \"$TARGET/memory\""; fi
fi

# ---------------------------------------------------------------- report
printf '\nproject memory for "%s" (%s)\n' "$NAME" "$TARGET"
printf '  created (%d):\n' "${#created[@]}"; [ "${#created[@]}" -eq 0 ] || printf '    + %s\n' "${created[@]}"
[ "${#skipped[@]}" -eq 0 ] || { printf '  left untouched (%d):\n' "${#skipped[@]}"; printf '    = %s\n' "${skipped[@]}"; }
if [ "${#suggested[@]}" -gt 0 ]; then
  printf '  MERGE BY HAND — these already existed, see the .team-memory.suggested file next to each:\n'; printf '    ! %s\n' "${suggested[@]}"
  printf '    (add the "basic-memory" server / hooks block; then delete the .suggested file)\n'
fi
printf '  Basic Memory: %s\n' "$reg"
printf '\nnext:\n  cd "%s" && git add -A memory .claude .cursor .kiro .mcp.json CLAUDE.md && git commit -m "memory: add project memory tier (%s)"\n' "$TARGET" "$NAME"
printf '  then fill memory/context/overview.md and run: uv run -q --script memory/scripts/sync-memory.py pre\n'
