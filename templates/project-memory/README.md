---
title: Project Memory Template
type: template
permalink: templates/project-memory/readme
tags: [template, project-memory, process]
---

# templates/project-memory — give any project its own memory

One command turns any git repo into a second memory tier that lives **inside that repo**
(`<repo>/memory/`), registered with Basic Memory as its own project, with the same
context/decisions/log layout, the same six agent rules, and the same Claude Code / Cursor /
Kiro / Claude Desktop wiring as cairn. The project's memory travels with the project's git
history; cairn stays company-wide.

```bash
# macOS / Linux
scripts/new-project-memory.sh /path/to/my-app            # name defaults to the folder name, kebab-cased
scripts/new-project-memory.sh /path/to/repo my-project-name
```
```powershell
# Windows
scripts\new-project-memory.ps1 C:\path\to\my-app
```

## What it does (idempotent, never overwrites)

| Step | Result in the target repo |
|---|---|
| copies `memory/` | `memory/{context,decisions,log}/` (templates are stored as `*.md.tmpl` so cairn's index never sees them; the suffix is dropped on copy), `memory/README.md`, `memory/AGENT-RULES.md`, `memory/.basic-memory/project.json` (placeholders filled: `__PROJECT_NAME__`, `__PROJECT_TITLE__`, `__DATE__`) |
| copies sync scripts | `memory/scripts/sync-memory.{sh,ps1,py}` (copied from cairn — re-run the bootstrap to refresh) |
| copies the skill | `memory/.agents/skills/team-memory/SKILL.md` (canonical for that repo) → mirrored into `.claude/skills/` and `.kiro/skills/` by the sync script |
| client configs | `.cursor/rules/memory.mdc`, `.kiro/steering/memory.md`, `.kiro/hooks/memory-*.json`, and — **only if absent** — `.mcp.json`, `.cursor/mcp.json`, `.kiro/settings/mcp.json`, `.claude/settings.json`. If one already exists, the script writes `<file>.team-memory.suggested` next to it and prints what to merge. |
| `CLAUDE.md` | appends `@memory/AGENT-RULES.md` (Claude Code import) if the line is missing; creates a minimal `CLAUDE.md` if none exists |
| Basic Memory | `basic-memory project add <name> <repo>/memory` if `basic-memory` is on PATH |

Then: review `git status`, commit, push. Every teammate who pulls gets the project memory and
the hooks; on their machine the first `sync-memory pre` (hook or manual) registers the project.

## Layout of a project's memory

```
<repo>/
  memory/
    .basic-memory/project.json     {"name": "<repo-name>", "kind": "project"}
    README.md                      what this memory is, trust order incl. cairn
    AGENT-RULES.md                 the six rules, project edition (imported by CLAUDE.md)
    context/overview.md            what the project is, status, links
    context/architecture.md        system design of THIS project
    context/conventions.md         project-specific coding/process rules
    context/glossary.md            project jargon
    decisions/README.md + ADR-000-template.md
    log/README.md + CHANGELOG.md   (CHANGELOG is only auto-appended if the repo adopts the cairn workflow)
    scripts/sync-memory.{sh,ps1,py}
    .agents/skills/team-memory/SKILL.md
  .claude/settings.json (hooks)    .claude/skills/team-memory/SKILL.md (copy)
  .cursor/rules/memory.mdc         .cursor/mcp.json
  .kiro/steering/memory.md         .kiro/settings/mcp.json   .kiro/hooks/memory-*.json   .kiro/skills/team-memory/SKILL.md (copy)
  .mcp.json                        CLAUDE.md (+ @memory/AGENT-RULES.md)
```

## Sync behaviour in project mode

`memory/scripts/sync-memory.* post` stages and commits **only `memory/`**, on whatever branch is
checked out, then pushes to that branch's upstream. It never touches source files. If `main` is
protected, memory commits land on the feature branch and reach `main` with the PR — that is the
intended behaviour. Conflicts inside `memory/` stop the script exactly as in cairn.

## Observations
- [rule] One Basic Memory project per repo, named after the repo, rooted at `<repo>/memory/`
- [rule] The bootstrap never overwrites existing files; existing client configs get a `.team-memory.suggested` sibling
- [rule] Project memory commits only touch `memory/`; they ride the current branch
- [rule] Cairn's rules apply unchanged; scope decides the tier

## Relations
- relates_to [[Conventions]]
- relates_to [[ADR-001 Shared Memory System]]
- relates_to [[Projects Index]]
