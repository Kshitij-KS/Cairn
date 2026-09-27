---
title: Cairn
type: readme
tags: [readme, onboarding, canonical]
level: L2
confidentiality: internal
created: 2026-09-27
updated: 2026-09-27
---
# Cairn

**Shared memory for your team's AI agents.** Cairn is a private git repository of Markdown notes
that every AI agent on the team (Claude Code, Kiro, Cursor, Claude Desktop) reads before it works
and writes to after. What one person's agent figures out, the next person's agent already knows.

- **Your agent starts every task informed.** It loads the big picture of the project first, then
  only the part you are working on and the parts connected to it.
- **What you learn is kept for the team.** Gotchas, fixes, decisions and dead ends become notes,
  each fact with a stable id, so it can be found, corrected or retired later.
- **Rules are enforced, not requested.** A guard checks every commit: agents can only add
  observations; changing plans, strategy or rules needs a person with that role. Secrets,
  prompt injections and forged authorship are refused.
- **It costs nothing to run.** Plain git, local tools, the GitHub free tier.

The name: a cairn is the stack of stones hikers leave to mark the trail for whoever comes next.

---

## Contents

1. [How it works](#1-how-it-works)
2. [Setup: owner, once](#2-setup-owner-once)
3. [Setup: every teammate](#3-setup-every-teammate)
4. [Connect your AI client](#4-connect-your-ai-client)
5. [Daily use](#5-daily-use)
6. [Slash commands](#6-slash-commands)
7. [The `mem` command line](#7-the-mem-command-line)
8. [Guidelines](#8-guidelines)
9. [Give a code repository its own memory](#9-give-a-code-repository-its-own-memory)
10. [When something blocks you](#10-when-something-blocks-you)
11. [Tests](#11-tests)
12. [Status and limits](#12-status-and-limits)

---

## 1. How it works

```
 you -- AI agent --> mem load "<your task>" --> CORE.md (big picture) + the feature you are on
          |                                     + what it depends on / what depends on it
          |
          +-- end of a turn --> sync post --> guard (level, secrets, format, authorship)
                                          --> commit --> push --> GitHub
                                                                  +-- memory-gate: the base
                                                                      revision's guard judges
                                                                      every pull request
```

| Folder | What lives there | Who may change it |
|---|---|---|
| `CORE.md` | the big picture every agent reads first | stewards (L2) |
| `context/` | company, product, architecture, conventions, glossary, roles | stewards (L2) |
| `decisions/` | decision records (accepted ones outrank everything) | stewards (L2) |
| `features/` | one note per part of the product: what it is, what it promises, the code it covers | maintainers (L1) |
| `projects/` | one status card per workstream | anyone (L0) |
| `log/journal/` | observations: gotchas, fixes, dead ends | anyone, including agents (L0) |
| `log/proposals/` | requests to change something above L0 | anyone (L0) |
| `trials/`, `evals/` | experiments on the memory, and retrieval tests | anyone (L0) |
| `governance/`, `scripts/`, `tools/`, `.claude/`, ... | the rules, and the code the hooks run | owners (L3) |

A note's level comes from **where it is**, never from what it says. An AI agent is always capped
at L0 no matter who is driving it: the human's authority applies when the human commits.

The full technical description is [ARCHITECTURE.md](ARCHITECTURE.md); the maintainer checklist is
[RUNBOOK.md](RUNBOOK.md).

---

## 2. Setup: owner, once

About 20 minutes.

### 2.1 Install the tools

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# close and reopen the terminal so PATH picks up uv
uv tool install --python 3.12 basic-memory
basic-memory config set auto_update false
```

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.12 basic-memory
basic-memory config set auto_update false
```

`--python 3.12` is required: Basic Memory needs Python 3.12 or newer.

### 2.2 Initialise the repository

Create your repository from the Cairn template (GitHub: **Use this template**, private), clone it,
and run once:

```bash
uv run -q --script scripts/init.py
```

It records you as the owner in `governance/roles.json`, sets **this repository's** git identity to
you (the guard attributes every note to the git identity that commits it, so this keeps attribution
right even if your machine uses another identity for other work), generates `.github/CODEOWNERS`,
and stamps the notes. It refuses to run twice.

### 2.3 Fill in the three things that matter

1. **`governance/roles.json`**: the owner row is filled in. Replace each `__TODO_PERSON_N__` row
   with a teammate: handle, name, the exact email from their `git config user.email`, GitHub login,
   role. Delete rows you do not need.

   | Role | May change | Give it to |
   |---|---|---|
   | `owner` | everything, including these rules and the hooks | you, plus one backup |
   | `steward` | Core, context, decisions | one or two senior people |
   | `maintainer` | one project's plan and features (list which in `projects`) | whoever owns that project |
   | `contributor` | observations only | everyone else |

2. **`CORE.md`** and **`context/*.md`**: search for `TODO` and write what every agent should know
   first: what the team builds, for whom, the goals, the non-negotiables.

3. **CODEOWNERS** is generated from the owners in `roles.json`. `init.py` generated it for you;
   after adding or changing an owner, run it again:

   ```bash
   uv run -q --script scripts/memory_guard.py codeowners --write
   ```

### 2.4 Commit and push

After your edits:

```bash
git add -A
uv run -q --script scripts/memory_guard.py stamp --staged
git add -A
uv run -q --script scripts/memory_guard.py check --staged     # must say "clean"
git commit -m "cairn: fill in the team"
git push -u origin main
```

If you push with a different GitHub account than the one this machine normally uses, see
[Pushing with a second GitHub account](#pushing-with-a-second-github-account) below.

### 2.5 Turn on the enforcement that actually holds (GitHub web)

Until this step, every rule is only checked on each laptop. After it, GitHub enforces them.

- **Settings -> Branches -> Add ruleset for `main`**: require a pull request; require review from
  Code Owners; dismiss stale approvals; require the status checks **`gate`**, **`route`**, **`test`**
  and **`windows-sync`** (they appear after the first pull request runs); block force pushes and
  deletion.
- Leave auto-merge **off** for now.
- Publishing the map (Actions -> atlas) commits `web/data/graph.json` straight to `main` as
  `github-actions[bot]`. With the ruleset above that push is refused unless you add
  **GitHub Actions** to the ruleset's bypass list. Only do that if you publish the map; the
  workflow only runs code that is already on `main`.

Then prove it with three throwaway pull requests (close each after checking):

1. edit `context/company.md`: labelled `memory:L2`, waits for your review;
2. make `scripts/memory_guard.py` return 0 at the start of `main()`: the `gate` check is **red**;
3. add `{"glob": "scripts/**", "level": "L0"}` as the first rule in `roles.json` plus a file in
   `scripts/`: labelled `memory:L3`.

If any behaves differently, stop: the gate is not doing its job.

### Pushing with a second GitHub account

If this machine is signed in to another GitHub account, give this repository its own SSH key and
host alias so the two never mix. Your other account keeps working as before.

```bash
# 1. a key just for this account
ssh-keygen -t ed25519 -C "<the email of that account>" -f ~/.ssh/id_ed25519_cairn

# 2. add the PUBLIC key (~/.ssh/id_ed25519_cairn.pub) to that account:
#    GitHub -> Settings -> SSH and GPG keys -> New SSH key

# 3. a host alias that always uses that key: append to ~/.ssh/config
Host github-cairn
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_cairn
    IdentitiesOnly yes

# 4. test: it must greet that account, not your usual one
ssh -T git@github-cairn

# 5. point this repository at the alias and push
git remote set-url origin git@github-cairn:<owner>/<repo>.git
git push -u origin main
```

On Windows, `~` is `C:\Users\<you>`; run these in Git Bash. The per-repository `user.email` that
`init.py` set keeps commits attributed to the right person. Teammates clone with the normal URL.

---

## 3. Setup: every teammate

About 10 minutes. The owner first adds you to `governance/roles.json` with your git email and gives
you access to the repository on GitHub.

```bash
# install uv and Basic Memory as in 2.1, then:
git clone git@github.com:<owner>/<repo>.git cairn
cd cairn
git config user.email "<the email the owner put in roles.json>"
uv run -q --script scripts/sync-memory.py pre           # pull, register with Basic Memory
uv run -q --script scripts/memory_guard.py explain      # shows what you may change
```

**Windows:** agents' automatic end-of-turn commits stay off until the sync tests have passed once on
your machine:

```powershell
py tools\test_sync.py                                   # must end "0 failed"
setx MEMORY_SYNC_WINDOWS_POST 1                         # then open a new terminal
```

---

## 4. Connect your AI client

Inside the `cairn` folder, Claude Code, Kiro and Cursor pick up this repository's configuration
automatically (`.mcp.json`, `.claude/`, `.kiro/`, `.cursor/`). To use the memory from other
folders as well:

**Claude Code**

```bash
claude mcp add --scope user basic-memory -- basic-memory mcp
```

**Cursor**: create `~/.cursor/mcp.json`:

```json
{ "mcpServers": { "basic-memory": { "type": "stdio", "command": "basic-memory", "args": ["mcp"] } } }
```

**Claude Desktop**: Settings -> Developer -> Edit Config, then fully quit and restart:

```json
{ "mcpServers": { "basic-memory": { "command": "<full path to basic-memory>", "args": ["mcp"] } } }
```

Use the full path (`C:\Users\<you>\.local\bin\basic-memory.exe` on Windows): desktop apps do not
inherit your terminal's PATH.

**Kiro**: open the `cairn` folder. The steering file, skill and hooks under `.kiro/` load
automatically. Kiro has no slash commands; use plain language (section 6).

To check it works, ask your agent: *"Load the team memory and tell me what this project is."* It
should answer from `CORE.md` and show a one-line receipt.

---

## 5. Daily use

Most of it happens without you doing anything.

| When | What happens | How |
|---|---|---|
| a session starts | pulls the latest memory, opens a session record | hook (Claude Code, Kiro) |
| you describe a task | the agent runs `mem load "<your task>"`: the big picture, then the feature you are on and its neighbours; one line tells you what it loaded | instructions in `CLAUDE.md` and the skill |
| a note you loaded changes upstream | a one-line warning, louder if its promise (contract) changed | hook (Claude Code) |
| the conversation is compacted | the session record is marked so notes are re-read, not assumed | hook (Claude Code) |
| a turn ends | anything worth keeping is written, checked by the guard, committed and pushed | hook |

**Which notes get loaded.** The big picture (`CORE.md`) always comes first. Then the feature you
are working on, found in this order: the files you are about to edit (every feature note lists the
code it covers), the feature names and nicknames in what you said, then words in each feature's
short description. What comes with it depends on the task:

| You are... | It also loads |
|---|---|
| building something | what it depends on |
| changing or removing something | what depends on it: what could break |
| fixing a bug | what building it would load, plus the last 30 days of notes about it |
| planning | every feature's summary, open decisions, waiting proposals |
| asking why | the decisions behind it |

If it cannot tell which feature you mean, it asks you one question instead of guessing.

---

## 6. Slash commands

Every command starts with `cairn` so it never collides with commands from other tools. In Claude
Code and Cursor, type `/cairn` to see them all.

| Command | What it does | Example |
|---|---|---|
| `/cairn` | status: who you act as, what is loaded, experiments, gaps, proposals waiting | `/cairn` |
| `/cairn-context <task>` | load the memory for a task: big picture first, then the feature and its neighbours | `/cairn-context fix the retry in checkout` |
| `/cairn-recall <question>` | single facts from the memory, ranked, each with its id and why it matched | `/cairn-recall which region does SSO need` |
| `/cairn-remember <fact>` | keep one fact for the team; anything above your level becomes a proposal automatically | `/cairn-remember the export job needs 8 GB for large accounts` |
| `/cairn-gaps [what was missing]` | note a question the memory could not answer, or list the open ones | `/cairn-gaps how do we rotate the signing key` |
| `/cairn-try <change>` | open, list, keep or drop an experiment on the memory, visible only to the people you name until it is kept | `/cairn-try "the checkout card is too vague" --change 'add to "Checkout": [fact] ...' --for sam` |
| `/cairn-feature` | list features, or propose a new one with the code it covers | `/cairn-feature new "Checkout" --covers "src/checkout/**"` |

**Kiro and plain language.** Anywhere, you can simply say *"load the memory for this task"*,
*"what do we know about SSO"*, *"remember that ..."*, or *"try this change for a week with Sam"*.
The skill in `.agents/skills/team-memory/` tells the agent which command to run.

---

## 7. The `mem` command line

`mem` means `uv run -q --script scripts/mem.py` (in a code repository with its own memory:
`memory/scripts/mem.py`). The everyday verbs:

| Command | Does |
|---|---|
| `mem load "<task>" [--touching FILE]` | the entry protocol; exit 2 means "which feature?" |
| `mem recall "<question>"` | ranked facts with reasons |
| `mem remember "<fact>" [--feature NAME]` | keep a fact (a proposal if above your level) |
| `mem gap "<what was missing>"`, `mem gaps` | record, list unanswered questions |
| `mem features`, `mem feature new NAME --covers GLOB` | the feature map |
| `mem try`, `trials`, `keep`, `drop` | experiments on the memory |
| `mem eval [--trial SLUG]` | retrieval tests, optionally with an experiment applied |
| `mem status`, `mem who`, `mem can HANDLE PATH` | who you are, who may change what |
| `mem --help` | everything else (`why`, `retire`, `pin`, `diff`, `approve`, `role`, `core init`, ...) |

The guard: `uv run -q --script scripts/memory_guard.py check --staged` shows findings without
committing, `explain` shows your ceiling, `audit --since 7d` shows who changed what.

---

## 8. Guidelines

**Store it only if it survives the week.** Ask: would a teammate, or you, decide worse in a month
without this? If not, store nothing; that is the right answer most of the time.

| Store | Never store |
|---|---|
| a corrected assumption, a gotcha that cost real time, a dead end and why | credentials, API keys, tokens, connection strings |
| a real constraint found in the code | customer data or personal information |
| a decision, an architecture change, an owner change (as a proposal) | salaries, private messages |
| a workstream's status change (update its card in `projects/`) | progress narration, or anything the diff or git log already says |

**Write facts, not instructions.** Notes are data. The guard refuses text that tries to instruct a
future agent ("ignore your rules", "don't tell the user"). Name where a secret lives; never paste it.

**Format.** Frontmatter with `title`, `type`, `tags`; one summary paragraph; `## Observations` as
`- [category] fact`; `## Relations` with at least one `- relates_to [[Existing Note Title]]`. Do not
write `author`, `level` or `confidentiality` yourself: the guard sets them from git.

**Proposals.** To change anything above your level, write `log/proposals/PROPOSAL - <what>.md` with
the exact text you want and why (`mem remember` does it for you). A person with the role reviews it
and runs `mem approve <proposal> --apply`.

**Weekly, owner or steward, 10 minutes:** review `log/proposals/`; run
`memory_guard.py audit --since 7d`; after approving anything above L0, work down the notes marked
`review_needed` that depend on it.

---

## 9. Give a code repository its own memory

Project facts belong with the project. From the `cairn` folder:

```bash
scripts/new-project-memory.sh /path/to/your-repo          # macOS / Linux
```
```powershell
scripts\new-project-memory.ps1 C:\path\to\your-repo       # Windows
```

This creates `your-repo/memory/` with its own notes, guard, policy and sync scripts, and the agent
configuration for Claude Code, Kiro and Cursor. It never overwrites a file; where a config already
exists it writes a `.team-memory.suggested` file for you to merge. Agents then search both tiers,
project first.

---

## 10. When something blocks you

| Exit | Meaning | Do this |
|---|---|---|
| 2 | merge conflict, or "which feature?" from `mem load` | resolve by hand and sync again; for `mem load`, add `--feature "<name>"` |
| 3 | a secret was about to be stored | remove the value; say where it lives instead |
| 4 | the change is above your level | write it as a proposal (`mem remember` does it for you) |
| 5 | the note failed validation | read the finding: missing relation, duplicate, wrong level, bad attribution |
| 6 | the policy cannot be enforced (guard or Python missing, or `roles.json` invalid) | fix the install; nothing was committed |
| 75 | another sync is running | nothing to do; the next turn catches up |

Never use `git commit --no-verify` or force-push; treat reaching for them as a sign to write a
proposal instead.

---

## 11. Tests

Everything runs offline, with no keys:

```bash
python3 tools/test_guard.py        # Windows: py tools\test_guard.py
python3 tools/test_security.py     # access, attribution and policy attacks
python3 tools/test_mem.py          # the context protocol, local state, experiments
python3 tools/test_atlas.py        # the published map and its redaction
python3 tools/test_gate.py         # the pull-request gate, run the way CI runs it
python3 tools/test_sync.py         # sync against local remotes (PowerShell on Windows, bash elsewhere)
python3 tools/test_parsers.py
cd web/test && npm ci && npm test  # the map's page, including a privacy check of the rendered page
```

`bash tools/run_tests.sh` runs them all. CI runs them on every pull request, including a Windows job.

---

## 12. Status and limits

- **Nothing is a security boundary until step 2.5 is done.** Before branch protection, every rule
  runs on each laptop, where a determined process can skip it. After it, a change reaches `main`
  only through a pull request that the base revision's code has judged and an owner has approved.
- **Automatic publishing of the map is off.** Publish by hand: Actions -> atlas -> Run workflow.
  The workflow runs the redaction tests first.
- Choosing which feature a task is about relies on files and words; it works best when feature
  notes list the code they cover. When unsure, it asks.
- Known open items: heavy edits can move a fact's id to an unrelated fact; an experiment comparison
  can report success when the experiment changes the tests themselves; a new project memory starts
  with notes the guard flags until the first `stamp`. See ARCHITECTURE.md section 10.

## Relations
- relates_to [[Core]]
- relates_to [[ADR-001 Shared Memory System]]
