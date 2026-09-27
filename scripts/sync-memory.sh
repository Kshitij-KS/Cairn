#!/usr/bin/env bash
# sync-memory.sh - git sync for the shared AI-agent memory (cairn or a project's memory/).
#
#   scripts/sync-memory.sh pre      # before a session: pull --rebase --autostash, register with
#                                   # Basic Memory, refresh skill copies, print a 1-line summary
#   scripts/sync-memory.sh post     # after a session: add + commit memory paths, pull --rebase, push
#   scripts/sync-memory.sh status   # dirty files, ahead/behind, registration state
#
# Idempotent and safe to run repeatedly. On a merge conflict it prints the conflicted files and
# STOPS (exit 2). It never force-pushes, never auto-resolves, never deletes anything.
#
# Exit codes: 0 ok, 1 error, 2 conflict, 3 secret, 4 access denied, 5 invalid note,
#             6 policy cannot be enforced (guard or Python missing), 7 the push was refused because
#             the branch is protected (sync-memory.py then opens a pull request), 75 another sync
#             holds the lock.
#
# 2026-09 audit fixes (06-F1..F11): commits are built in a TEMPORARY index holding only this tier,
# so nothing the user staged elsewhere can ride along; a missing guard or interpreter blocks the
# commit; autostash conflicts stop with exit 2; detached HEAD is refused; pull/push use the
# configured upstream; nothing is pushed unless every unpushed commit stays inside this tier.
#
# Layout it expects (works for both tiers because the manifest sits next to scripts/):
#   <notes_root>/.basic-memory/project.json   <- manifest: {"name": "...", "kind": "team|project"}
#   <notes_root>/scripts/sync-memory.sh       <- this file
#   <notes_root>/.agents/skills/team-memory/SKILL.md  <- canonical skill; copies go to <repo>/.claude and <repo>/.kiro
#
# Env: MEMORY_SYNC_QUIET=1 (less output), MEMORY_SYNC_NO_PUSH=1 (commit but don't push),
#      MEMORY_SYNC_DIRECT_PUSH=0 (commit and rebase, then leave the push to sync-memory.py's
#      pull-request mode),
#      MEMORY_AGENT=<name> (recorded in the commit trailer), MEMORY_SYNC_REMOTE (default: origin)

set -u
set -o pipefail

MODE="${1:-pre}"
REMOTE="${MEMORY_SYNC_REMOTE:-origin}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
NOTES_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
MANIFEST="$NOTES_ROOT/.basic-memory/project.json"

log()  { [ "${MEMORY_SYNC_QUIET:-0}" = "1" ] || printf '%s\n' "$*"; }
warn() { printf 'sync-memory: WARN %s\n' "$*" >&2; }
die()  { printf 'sync-memory: ERROR %s\n' "$*" >&2; exit "${2:-1}"; }

# ---------------------------------------------------------------- manifest + repo discovery
[ -f "$MANIFEST" ] || die "manifest not found: $MANIFEST"
PROJECT_NAME="$(grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' "$MANIFEST" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
PROJECT_KIND="$(grep -o '"kind"[[:space:]]*:[[:space:]]*"[^"]*"' "$MANIFEST" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
[ -n "$PROJECT_NAME" ] || die "manifest has no \"name\": $MANIFEST"
PROJECT_KIND="${PROJECT_KIND:-team}"

command -v git >/dev/null 2>&1 || die "git is not installed"
REPO_ROOT="$(git -C "$NOTES_ROOT" rev-parse --show-toplevel 2>/dev/null)" || die "$NOTES_ROOT is not inside a git repository"
cd "$REPO_ROOT" || die "cannot cd to $REPO_ROOT"

# Path (relative to repo root) that this tier owns. team -> whole repo; project -> memory/ folder.
case "$NOTES_ROOT" in
  "$REPO_ROOT") REL_NOTES="." ;;
  "$REPO_ROOT"/*) REL_NOTES="${NOTES_ROOT#"$REPO_ROOT"/}" ;;
  *) die "notes root $NOTES_ROOT is outside repo $REPO_ROOT" ;;
esac
TAG="[$PROJECT_NAME]"

BRANCH="$(git symbolic-ref -q --short HEAD 2>/dev/null || true)"
HAS_REMOTE=0; git remote get-url "$REMOTE" >/dev/null 2>&1 && HAS_REMOTE=1
UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
HAS_UPSTREAM=0; [ -n "$UPSTREAM" ] && HAS_UPSTREAM=1
if [ -z "$BRANCH" ] && [ "$MODE" != "status" ]; then
  # A detached HEAD used to pull nothing, then commit where no branch would ever push it (06-F8).
  die "HEAD is detached; check out your branch (git switch main) and run sync again" 1
fi

# ---------------------------------------------------------------- guards
rebase_in_progress() {
  local g; g="$(git rev-parse --git-dir)"
  [ -d "$g/rebase-merge" ] || [ -d "$g/rebase-apply" ] || [ -f "$g/MERGE_HEAD" ]
}

report_conflict() {
  printf '\n%s MERGE CONFLICT - sync stopped. Nothing was force-pushed or auto-resolved.\n' "$TAG" >&2
  printf 'Conflicted files:\n' >&2
  git diff --name-only --diff-filter=U 2>/dev/null | sed 's/^/  - /' >&2
  printf '\nResolve by hand, then:\n  git add <files> && git rebase --continue && %s post\n' "$0" >&2
  printf 'Or undo the pull entirely:\n  git rebase --abort\n' >&2
  exit 2
}

if rebase_in_progress; then
  printf '%s a rebase/merge is already in progress - resolve it before syncing.\n' "$TAG" >&2
  git diff --name-only --diff-filter=U 2>/dev/null | sed 's/^/  - /' >&2
  printf '  git add <files> && git rebase --continue    # or: git rebase --abort\n' >&2
  exit 2
fi

# Lock: two hooks (e.g. Claude Code Stop + Kiro Stop) must not sync the same clone at once.
# The dispatcher (sync-memory.py) takes the lock itself so pre, compile and expire run under ONE
# lock (06-F7) and tells us with MEMORY_SYNC_LOCK_HELD=1. Run directly, we lock here.
TMP_INDEX=""
cleanup() { [ -n "$TMP_INDEX" ] && rm -f "$TMP_INDEX" "$TMP_INDEX.lock"; [ -n "${LOCK_DIR:-}" ] && rm -rf "$LOCK_DIR" 2>/dev/null; true; }
if [ "${MEMORY_SYNC_LOCK_HELD:-0}" != "1" ] && [ "$MODE" != "status" ]; then
  LOCK_DIR="$(git rev-parse --absolute-git-dir)/sync-memory.lock"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    # stale only if older than 30 minutes; a busy lock is exit 75, never a silent success (06-F7)
    if [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then rm -rf "$LOCK_DIR"; mkdir "$LOCK_DIR" 2>/dev/null || die "could not acquire lock $LOCK_DIR"
    else LOCK_DIR=""; printf '%s another sync is running; not syncing now.\n' "$TAG" >&2; exit 75; fi
  fi
  printf 'pid=%s started=%s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$LOCK_DIR/owner" 2>/dev/null || true
fi
trap cleanup EXIT

# ---------------------------------------------------------------- helpers
pull_rebase() {
  [ "$HAS_REMOTE" = 1 ] || { warn "no remote '$REMOTE' - working offline"; return 0; }
  [ "$HAS_UPSTREAM" = 1 ] || { warn "branch '$BRANCH' has no upstream - skipping pull (first push will set it)"; return 0; }
  local before err; before="$(git rev-parse HEAD)"; err="$(mktemp)"
  # No remote/branch arguments: git uses the CONFIGURED upstream, which may differ in name (06-F9).
  if ! git pull --rebase --autostash --quiet 2>"$err"; then
    if rebase_in_progress || [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then rm -f "$err"; report_conflict; fi
    cat "$err" >&2; rm -f "$err"
    die "git pull --rebase failed (network? auth?). Memory may be stale."
  fi
  rm -f "$err"
  # An autostash that fails to re-apply leaves conflicts while git pull still exits 0 (06-F5).
  if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then report_conflict; fi
  PULLED="$(git rev-list --count "$before..HEAD" 2>/dev/null || echo 0)"
}

ensure_registered() {
  local bm=""
  if command -v basic-memory >/dev/null 2>&1; then bm=basic-memory
  elif command -v bm >/dev/null 2>&1; then bm=bm
  else warn "basic-memory not on PATH - skipped project registration (README step 2)"; return 0; fi
  # --json: the table view truncates long names
  if "$bm" project list --json 2>/dev/null | grep -Eq "\"name\"[[:space:]]*:[[:space:]]*\"$PROJECT_NAME\""; then
    REGISTERED="yes"
  else
    if "$bm" project add "$PROJECT_NAME" "$NOTES_ROOT" >/dev/null 2>&1; then
      REGISTERED="added"; log "$TAG registered Basic Memory project '$PROJECT_NAME' -> $NOTES_ROOT"
    else
      REGISTERED="failed"; warn "could not register project '$PROJECT_NAME' (run: $bm project add $PROJECT_NAME \"$NOTES_ROOT\")"
    fi
  fi
}

refresh_skill_copies() {
  local canonical="$NOTES_ROOT/.agents/skills/team-memory/SKILL.md"
  [ -f "$canonical" ] || return 0
  local dest
  for dest in "$REPO_ROOT/.claude/skills/team-memory/SKILL.md" "$REPO_ROOT/.kiro/skills/team-memory/SKILL.md"; do
    if [ -L "$dest" ]; then continue; fi                      # symlink (macOS/Linux) - nothing to copy
    if [ ! -f "$dest" ] || ! cmp -s "$canonical" "$dest"; then
      mkdir -p "$(dirname "$dest")" && cp "$canonical" "$dest" && log "$TAG refreshed skill copy ${dest#"$REPO_ROOT"/}"
    fi
  done
}

GUARD="$NOTES_ROOT/scripts/memory_guard.py"
PYTHON_CMD=""
find_python() {
  local c
  for c in python3 python py; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      PYTHON_CMD="$c"; return 0
    fi
  done
  command -v uv >/dev/null 2>&1 && { PYTHON_CMD="uv run -q --script"; return 0; }
  return 1
}
require_guard() {
  # FAIL CLOSED: a missing guard or interpreter used to print a warning and commit anyway (06-F4).
  [ -f "$GUARD" ] || die "memory_guard.py is missing ($GUARD): the policy cannot be enforced, so nothing is committed" 6
  find_python || die "no Python 3.9+ found (python3, python, py or uv): the policy cannot be enforced, so nothing is committed" 6
}
guard() {  # guard <subcommand> [args...]
  # shellcheck disable=SC2086
  $PYTHON_CMD "$GUARD" --notes-root "$NOTES_ROOT" "$@"
}

secret_guard() {
  # Runs against the temporary index, i.e. exactly the tree that will be committed.
  local bad
  bad="$(git diff --cached --name-only | grep -Ei '(^|/)\.env($|\.)|\.(pem|key|p12|pfx)$|id_rsa|credentials\.json$' || true)"
  if [ -n "$bad" ]; then
    printf '%s refusing to commit files that look like secrets:\n%s\n' "$TAG" "$bad" >&2
    exit 3
  fi
  bad="$(git diff --cached -U0 | grep -E '^\+' | grep -En '(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' || true)"
  if [ -n "$bad" ]; then
    printf '%s refusing to commit: the change contains what looks like an API key / private key:\n%s\n' "$TAG" "$bad" >&2
    exit 3
  fi
}

tier_only() {  # tier_only <file-with-paths>: every path is inside this tier?
  [ "$REL_NOTES" = "." ] && return 0
  ! grep -qv "^$REL_NOTES/" "$1"
}

# ---------------------------------------------------------------- modes
PULLED=0; REGISTERED="n/a"
case "$MODE" in
  pre)
    pull_rebase
    ensure_registered
    refresh_skill_copies
    # One line for the agent's context (SessionStart hooks add stdout to context).
    recent="$(git log --since='7 days ago' --name-only --pretty=format: -- "$REL_NOTES" 2>/dev/null | grep -E '(^|/)(context|decisions|projects|log)/.*\.md$' | grep -v 'CHANGELOG.md' | awk '!seen[$0]++' | head -5 | tr '\n' ' ')"
    stale="$(grep -rl '^review_needed:' "$NOTES_ROOT/context" "$NOTES_ROOT/decisions" "$NOTES_ROOT/projects" 2>/dev/null | wc -l | tr -d ' ')"
    printf '%s memory synced: %s@%s, pulled %s commit(s), Basic Memory project %s. Recently changed: %s\n' \
      "$TAG" "$BRANCH" "$(git rev-parse --short HEAD)" "$PULLED" "$REGISTERED" "${recent:-nothing in 7 days}"
    if [ "${stale:-0}" != "0" ]; then
      printf '%s %s note(s) carry review_needed after a planning change: treat them as possibly stale and prefer the note they point at.\n' "$TAG" "$stale"
    fi
    ;;

  post)
    require_guard
    # Build the commit in a TEMPORARY index: HEAD plus this tier's working-tree changes, nothing
    # else. The user's own index is never staged into, reset or committed (06-F1, 06-F11).
    TMP_INDEX="$(git rev-parse --absolute-git-dir)/sync-memory.index.$$"
    export GIT_INDEX_FILE="$TMP_INDEX"
    if git rev-parse --verify -q HEAD >/dev/null; then git read-tree HEAD || die "could not prepare the sync index"
    else git read-tree --empty || die "could not prepare the sync index"; fi
    git add -A -- "$REL_NOTES" 2>/dev/null || die "git add failed"
    COMMITTED=0
    if git diff --cached --quiet; then
      log "$TAG nothing to commit."
    else
      # Attribution is written from the git identity, never from what the agent claims.
      guard stamp --staged >/dev/null || die "guard stamp failed" 6
      git add -A -- "$REL_NOTES" 2>/dev/null || true
      # The gate. Same code CI runs, so this cannot pass here and fail there.
      guard check --staged --quiet; rc=$?   # NOT `if ! guard`: that swallows the exit code
      if [ "$rc" -ne 0 ]; then
        case "$rc" in
          3) printf '%s blocked: a secret would have been committed. Nothing was written.\n' "$TAG" >&2 ;;
          4) printf '%s blocked: this change is above your level. Write it as a proposal instead (log/proposals/).\n' "$TAG" >&2 ;;
          6) printf '%s blocked: the policy could not be loaded, so nothing is committed.\n' "$TAG" >&2 ;;
          *) printf '%s blocked: the note did not pass validation. Fix the findings above and retry.\n' "$TAG" >&2 ;;
        esac
        exit "$rc"
      fi
      secret_guard
      list="$(mktemp)"; git diff --cached --name-only > "$list"
      tier_only "$list" || { rm -f "$list"; die "internal: the sync index holds paths outside $REL_NOTES; nothing committed"; }
      n="$(wc -l < "$list" | tr -d ' ')"
      files="$(head -3 "$list" | tr '\n' ',' | sed 's/,$//; s/,/, /g')"; rm -f "$list"
      [ "$n" -gt 3 ] && files="$files, +$((n-3)) more"
      agent="${MEMORY_AGENT:-${CLAUDE_CODE_ENTRYPOINT:+claude-code}}"; agent="${agent:-${KIRO_AGENT:+kiro}}"; agent="${agent:-unknown}"
      # same default as memory_guard.Ctx: an agent runtime's marker means agent (trailer must match the gate)
      if [ -n "${MEMORY_ACTOR_KIND:-}" ]; then actor="$MEMORY_ACTOR_KIND"
      elif [ -n "${CLAUDE_CODE_SESSION_ID:-}${CLAUDECODE:-}${CLAUDE_CODE_ENTRYPOINT:-}${KIRO_AGENT:-}${CURSOR_AGENT:-}${MEMORY_AGENT:-}" ]; then actor=agent
      else actor=human; fi
      git commit --quiet --no-verify -m "memory: ${n} file(s) - ${files}" \
        -m "Sync-Actor: ${actor}" -m "Sync-Agent: ${agent}" -m "Sync-Host: $(hostname 2>/dev/null || echo '?')" \
        || die "git commit failed (is user.name / user.email configured?)"
      COMMITTED=1
      log "$TAG committed $n file(s)."
    fi
    unset GIT_INDEX_FILE
    rm -f "$TMP_INDEX"; TMP_INDEX=""
    # Bring the user's real index in line with the new commit for this tier only; their staging
    # anywhere else is untouched.
    [ "$COMMITTED" = 1 ] && git reset -q -- "$REL_NOTES" 2>/dev/null
    if [ "${MEMORY_SYNC_NO_PUSH:-0}" = "1" ]; then log "$TAG push skipped (MEMORY_SYNC_NO_PUSH=1)"; exit 0; fi
    [ "$HAS_REMOTE" = 1 ] || { warn "no remote '$REMOTE' - commit kept locally"; exit 0; }
    if [ "$HAS_UPSTREAM" = 1 ]; then
      # nothing local to push -> no network round-trip (Stop hooks fire on every turn)
      [ "$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)" = "0" ] && { log "$TAG nothing to push."; exit 0; }
      # Push only memory work: a project-tier hook once pushed an unrelated application commit
      # because it happened to be ahead (06-F6).
      list="$(mktemp)"; git log --format= --name-only '@{u}..HEAD' | sed '/^$/d' | sort -u > "$list"
      if ! tier_only "$list"; then
        printf '%s not pushing: unpushed commits change files outside %s:\n' "$TAG" "$REL_NOTES" >&2
        grep -v "^$REL_NOTES/" "$list" | head -5 | sed 's/^/  - /' >&2; rm -f "$list"
        printf '%s push those yourself (the memory commit is kept locally and will go with them).\n' "$TAG" >&2
        exit 0
      fi
      rm -f "$list"
      pull_rebase
      if [ "${MEMORY_SYNC_DIRECT_PUSH:-1}" = "0" ]; then
        log "$TAG committed locally; sync-memory.py opens the pull request."
        exit 0
      fi
      UP_REMOTE="${UPSTREAM%%/*}"; UP_BRANCH="${UPSTREAM#*/}"
      err="$(mktemp)"
      git push --quiet "$UP_REMOTE" "HEAD:$UP_BRANCH" 2>"$err" || {
        if grep -Eqi 'protected branch|GH006|GH013|repository rule' "$err"; then
          cat "$err" >&2; rm -f "$err"
          printf '%s %s is protected: not pushing directly. The commit is kept locally.\n' "$TAG" "$UP_BRANCH" >&2
          exit 7
        fi
        # someone pushed between our pull and push: one retry, still no force
        pull_rebase
        git push --quiet "$UP_REMOTE" "HEAD:$UP_BRANCH" 2>>"$err" || { cat "$err" >&2; rm -f "$err"; die "git push rejected. Not forcing. Fix and run: $0 post"; }
      }
      rm -f "$err"
      log "$TAG pushed $BRANCH -> $UPSTREAM."
    else
      [ "$COMMITTED" = 1 ] || { log "$TAG nothing to push."; exit 0; }
      list="$(mktemp)"; git log --format= --name-only HEAD | sed '/^$/d' | sort -u > "$list"
      if ! tier_only "$list"; then rm -f "$list"; warn "branch '$BRANCH' has no upstream and holds non-memory commits; not pushing"; exit 0; fi
      rm -f "$list"
      err="$(mktemp)"
      git push --quiet -u "$REMOTE" "$BRANCH" 2>"$err" || { cat "$err" >&2; rm -f "$err"; die "initial push failed"; }
      rm -f "$err"
      log "$TAG pushed $BRANCH -> $REMOTE."
    fi
    ;;

  status)
    printf '%s repo=%s tier=%s notes=%s branch=%s remote=%s upstream=%s\n' "$TAG" "$REPO_ROOT" "$PROJECT_KIND" "$REL_NOTES" "$BRANCH" "$HAS_REMOTE" "$HAS_UPSTREAM"
    if [ "$HAS_UPSTREAM" = 1 ]; then git fetch --quiet "$REMOTE" 2>/dev/null || true; printf 'ahead/behind upstream: %s\n' "$(git rev-list --left-right --count '@{u}...HEAD' 2>/dev/null | awk '{print "behind="$1" ahead="$2}')"; fi
    printf 'uncommitted memory changes:\n'; git status --porcelain -- "$REL_NOTES" | sed 's/^/  /';
    if command -v basic-memory >/dev/null 2>&1; then basic-memory project list --json 2>/dev/null | grep -Eq "\"name\"[[:space:]]*:[[:space:]]*\"$PROJECT_NAME\"" && printf '  Basic Memory project "%s" registered\n' "$PROJECT_NAME" || printf '  Basic Memory project "%s" NOT registered\n' "$PROJECT_NAME"; fi
    ;;

  *) die "usage: $0 pre|post|status" ;;
esac
exit 0
