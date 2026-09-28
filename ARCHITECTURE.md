---
title: System Architecture
type: context
tags: [architecture, audit, canonical]
level: L2
confidentiality: internal
created: 2026-09-23
updated: 2026-09-28
---
# System Architecture

cairn is a shared memory for a small team's AI agents: Markdown notes in a private git
repository that every agent reads before it works and writes to after, with the rules about who may
change what enforced in code at commit time rather than requested in a prompt. This document
describes every part of it, how the parts connect, what each one guarantees, how that was tested,
and what is still unverified. It is written for an agent or a person auditing the system.

**Status as of 2026-09-25, after an independent security audit of Cairn.** The audit found that
several controls this document had called hard gates were client-side, self-authenticating,
fail-open or bypassable. Its reports are not part of this repository; finding ids such as `01-F1`
or "area 06" in code comments and tests refer to them. Phases 0-2 of its remediation are done: containment,
a trusted-base security boundary, a closed publication schema, repaired sync, and concurrency-safe
local state. **On 2026-09-28 a re-check of every finding against the code** found the open Phase 3-4
items plus new ones (a non-ASCII path skipping every guard check, executable and instruction files
outside the protected floor, a note's author being reassignable, Atlas leaks through titles and
activity, sync failures after a squash merge). All of them are fixed, each with a regression test
that was run against the code before the fix and failed; section 10 lists what remains by design.

What is still true regardless: **nothing here is a security boundary until the repository is on
GitHub with branch protection on `main` requiring Code Owner review and the `memory-gate` check.**
Everything that runs on a laptop is a guard-rail for honest agents. On GitHub, `tests` (Linux and
the Windows PowerShell sync) has passed on the template's pushes; `memory-gate` has not yet judged a
real pull request. Section 11 says how each figure was measured; section 12 lists what was not.

**Two supported setups.** *Simple* (the recommended start): `main` unprotected, `enforcement.mode`
`direct`, notes reach `main` at the end of every turn, and the guard on each laptop is the only check.
*Protected*: a ruleset on `main`, `mode` `pr`, notes travel through one pull request per person and
the base revision's gate judges them. README 2.5 states the trade in the user's terms: Simple stops
honest mistakes, not a determined person, and that includes the hooks every teammate's machine runs.

**Containment in force:** nothing auto-merges until an owner adds a level to
`enforcement.auto_merge_levels`; the public atlas is published by hand only. Agents' automatic
`post` on Windows is on (it was paused until the PowerShell chain passed on Windows; CI now runs it
on every change); `MEMORY_SYNC_WINDOWS_POST=0` pauses it on one machine.

**The 2026-09-27 review** found that protecting `main` stopped agents' notes from reaching it (the
sync pushed only to `main`), that a project tier had no gate on GitHub, that one variable let an
agent act as a person, and that two injection phrasings passed. All four are fixed below, each with
a regression test shown to fail without its fix.

Legend: **[verified]** = executed and observed when this was written; **[unverified]** = written from docs or
reasoning and never executed; **[estimate]** = a number without a precise measurement.

---

## 1. What the product does, in one screen

1. **Stores what the team knows** as notes in folders whose path decides who may change them:
   observations (L0), project planning (L1), strategy (L2), governance (L3).
2. **Gives each agent the right context in the right order.** One command, `mem load "<the ask>"`,
   loads the big picture (`CORE.md`) first, works out which feature the ask is about, and loads
   that feature's neighbourhood *by dependency direction*: what it relies on for a build task, what
   relies on it for a change. Nothing is loaded twice in a session.
3. **Lets agents write only observations.** Agents are capped at L0 whoever drives them. Anything
   higher becomes a proposal a person with the role approves. A guard enforces this at commit.
4. **Treats each fact as an addressable claim** (`- [fact] text ^a1b2c3`) with a stable id that
   survives rewording, so a fact can be recalled, retired, pinned, tested, and traced.
5. **Supports experiments on the memory itself** (trials): a change visible only to named people,
   with an expiry, that is kept (through the normal rules) or dropped (with a recorded result).
6. **Tests its own retrieval** (evals): "this question must find that claim", "this ask must
   resolve to that feature in that mode", runnable before and after any change.
7. **Shows the memory as a map** (Memory Atlas): a static web page built from a redacted
   `graph.json`, safe to publish.
8. **Replicates per project**: a code repository gets its own `memory/` tier with the same rules,
   engine and agent wiring, via one scaffold script.

It costs nothing to run: Basic Memory (local, AGPL, used unmodified as a separate process), git,
Python standard library, and GitHub's free tier. No hosted or paid service is used.

---

## 2. The shape of the system

```
                         +--------------------------- one git repo per tier ---------------------------+
                         |  cairn/ (company)            <code repo>/memory/ (one per project)      |
                         |  CORE.md  features/  context/  decisions/  projects/  log/  trials/  evals/  |
                         |  governance/roles.json  <- the only policy file                              |
                         +------------------------------------------------------------------------------+
                                   ^ read                    ^ read/write              ^ build
                                   |                         |                         |
  agent (Claude Code, Kiro,  --> mem.py load/recall/...  --> memory_guard.py  <--  build_atlas.py --> graph.json --> web/
  Cursor) + hooks             (reader, verbs, trials,     (enforcer: levels,     (redacted map)        (Memory Atlas)
                               evals, local cache)         ids, safety, format)
                                   |                         ^
                                   v                         | stamp + check at every commit
                              .memory/ (gitignored,     sync-memory.py pre|post  (pull / stamp, check, commit, push)
                              per machine: cache,            ^
                              ledgers, bundles, pack)        | also runs in CI: memory-gate.yml (PRs), tests.yml
                                                             |
                         Basic Memory MCP server (local) indexes the same Markdown for search_notes/read_note
```

Two programs matter most. **`scripts/memory_guard.py`** (1,897 lines) is the enforcer; it runs on
every commit locally and on every pull request in CI. **`scripts/mem.py`** (2,227 lines) is the
reader and the verbs; it imports every parser from the guard, so the two cannot disagree about what
a note says. Both are Python 3.9+, standard library only.

---

## 3. The storage model

### 3.1 Tiers

| Tier | Where | Holds | Notes root found by |
|---|---|---|---|
| Company | the `cairn` repo root | company canon, cross-project decisions, this system's own features | `.basic-memory/project.json` in cwd or a parent |
| Project | `<code repo>/memory/` | that project's features, decisions, observations | same, **or** `./memory/.basic-memory/project.json` when run from the code repo's root (added 2026-09-23; tested) |

Scope decides the tier: a fact meaningful only inside one repo belongs in that repo's tier.

### 3.2 Folders and levels

A note's level is **a pure function of its path** and `governance/roles.json` `paths.rules` (first
match wins; default L0). Frontmatter never grants a level; a declared `level:` that disagrees with
the path fails the check (`LEVEL-MISMATCH`).

| Path | Level | Holds |
|---|---|---|
| `governance/**`, `.github/**`, `.claude/**`, `.kiro/**`, `.cursor/**`, `.agents/**`, `scripts/**`, `tools/**`, `web/**`, `CODEOWNERS`, `CLAUDE.md`, `log/CHANGELOG.md` | L3 | rules, hooks, CI, the scripts hooks run, the tests that prove them, the public site. Most are also in the code's protected floor, which no policy can lower |
| `web/data/**` | bot | the generated public map: only CI's bot writes it |
| `.claude/skills/**`, `.kiro/skills/**` | derived | allowed only while byte-identical to `.agents/skills/**` |
| `CORE.md`, `ARCHITECTURE.md`, `decisions/**`, `context/**`, `templates/**`, `README.md`, `RUNBOOK.md` | L2 | canon, strategy, onboarding |
| `features/**` | L1 | the feature spine |
| `log/journal/**`, `log/proposals/**`, `log/gaps/**`, `log/**`, `projects/**`, `trials/**`, `evals/**` | L0 | observations, proposals, gaps, experiments, tests |

Roles (`roles.order`): `agent` (max L0) < `reader` < `contributor` < `maintainer` < `steward` <
`owner` (max L3). A person's role is a maximum; `projects` can narrow a maintainer's L1 rights.
**An agent is `agent` regardless of who drives it**: the human's rights apply when the human
commits, not when their agent does.

### 3.3 Note format

```markdown
---
title: Unique Title Case Name          # required, unique across the tier (relations resolve by title)
type: note | context | decision | feature | trial | gaps | proposal | gotcha | ...
tags: [..]
# stamped by the guard from the git identity, never trusted from the writer:
author: alex
updated_by: alex
created: 2026-09-23
updated: 2026-09-23
level: L2                               # optional; must match the path
confidentiality: open | internal | restricted
# type-specific: status, owner, covers, aliases (feature); hypothesis, for, expires (trial)
---

# Title

One-paragraph summary (its first sentence is the note's "brief").

## Observations
- [category] one fact per line ^a1b2c3

## Relations
- depends_on [[Another Note Title]]
```

Parsers ignore fenced and inline code (`strip_code`), so example syntax inside a code block is not
read as a real claim or relation (fixed after it produced phantom broken links; `tools/test_parsers.py`).

### 3.4 Claims and their ids

A **claim** is an observation line `- [category] text ^id`. The id is six hex characters of
`sha1(note_id + "\n" + text)`, the text Unicode-normalised (NFKC) and case-folded, so NFC and NFD
spellings of one line agree; a new id is never one used anywhere in the tier, now or at `HEAD`.

The rule behind every choice below: a LOST id is visible and can be put back; a TRANSFERRED id is
silent, and every pin, eval and trial then points at the wrong fact. So carrying an id forward must
be close and unambiguous, or it does not happen. **[verified, tools/test_claims.py]**

- **Assignment**: `memory_guard.py stamp` gives unmarked claims an id. `sync-memory post` runs it
  before every commit.
- **Carry-forward**: an unmarked line is compared with the claims that disappeared from `HEAD`'s
  version of the note. Pairs are taken best first; a pair is kept only if it reaches similarity
  **0.5** (the highest of token Jaccard with light stemming, containment and `difflib` ratio) AND
  exceeds every rival for either side by 0.08 on a stricter score (the mean of Jaccard and ratio), and
  a changed category counts against it. There is no one-for-one rule: an unrelated line that
  replaces a deleted one gets a new id (02-F3), and two reordered, edited lines keep their own
  (02-F2). A claim that left one note and appears nearly unchanged (0.8) in another note of the
  same change keeps its id (02-F4).
- **Loss is reported**: the guard warns `claim id(s) gone from this note` naming them. The recheck's
  20 deep paraphrases keep 9 ids and move none; the rest need a person to put the old `^id` back.
- **Collisions and references**: a line ending with another note's id is an eval reference
  (`includes ^be2885`, kept, with its own id appended) or a collision. In a collision the claim the
  tier had at `HEAD` keeps the id and the newcomer gets a new one; the old repair did the opposite and
  silently moved every reference (02-F6). `stamp --all` repairs it; the guard fails until then.
- **Malformed ids** (`^ABCDEF`, `^12345g`): stamp normalises a recognisable one and replaces the rest;
  the guard warns about any left (02-F9).
- **Retirement**: `mem retire ^id` moves the line to `## Retired` with `(retired DATE: why)`. The id
  still belongs to that line, is never stamped again or reused (02-F5), and is excluded from recall.
  `mem why ^id` says "retired" only for such a line; an id that is merely cited says so.

### 3.5 Relations and direction

Relations are `- <type> [[Title]]` lines. **Dependency** types (`roles.json`
`cascade.relation_types_followed`: `depends_on`, `implements`, `part_of`, `supersedes`) have a
direction; `relates_to` means "see also" and is **never followed** by the protocol or the cascade.
For a note X: *upstream* = what X relies on (X --depends_on--> Y); *downstream* = what relies on X.

### 3.6 Special folders

| Folder | Level | Purpose | Validated by the guard |
|---|---|---|---|
| `CORE.md` | L2 | the big picture every agent reads first | `CORE-SIZE` warns above `protocol.core_max_tokens` (3,000, estimate) |
| `features/` | L1 | one note per part of the product: `## Card` (<= 150 words), `## Contract` (what it promises), `covers:` code globs, `owner`, `status`, `aliases` | `FEATURE` (status, owner, card), `FEATURE-COVERS` (each glob must match a real file under the code root), `WRITEBACK` (covered code changed, feature note did not) |
| `trials/` | L0 | an experiment: `hypothesis`, `for:` people, `expires`, `## Changes` lines | `TRIAL` (status, required fields, date) |
| `evals/` | L0 | retrieval and resolution tests as `[eval]` claims | claim-id rules |
| `log/gaps/` | L0 | what agents needed and did not find, one note per feature | - |
| `log/proposals/` | L0 | `PROPOSAL - <what>`: target path, exact text, reason | - |

**Code root** (where `covers:` resolve): `MEMORY_CODE_ROOT` env, else `roles.json`
`protocol.code_root` relative to the repo root (cairn sets `"."` so its features cover its own
scripts), else the code repo when the tier is `memory/` inside it.

### 3.7 Confidentiality and significance

`confidentiality` (default `internal`): `open` may be published; `internal` stays in the private
repo; `restricted` is not stored in this repo at all: it lives in a separate private repository
mounted as a git submodule at `context/restricted/`, so access is a GitHub permission, not a
convention. `mem load` and `mem recall` withhold restricted notes from anyone without
`restricted_read` in `roles.json`; that is advisory on a laptop that has the files (section 9).

Significance (A decision / B signal / C summary / D discard, `governance/SIGNIFICANCE.md`) decides
*whether* to store; the Stop hook runs `memory_guard.py significance` to prompt, deterministically,
at most once per session.

---

## 4. Components

### 4.1 `memory_guard.py`: the enforcer

Subcommands: `stamp`, `check`, `classify`, `codeowners`, `cascade`, `significance`, `explain`, `audit`.
Exit codes: `0` ok, `3` secret, `4` access denied, `5` validation failure, `6` policy unusable / internal error.

**Which policy judges a change (2026-09 audit, 01-F1/F2, 10-F1).** Never the copy the change edits.
`check` and `classify` load `governance/roles.json` **as of a trusted revision**: `HEAD` for staged
and working-tree checks, the merge base for `--range`, or `--policy-ref` / `MEMORY_POLICY_REF`. The
working copy is used only when there is no commit yet. While `roles.json` itself is changing, a path
needs the level **both** policies require. On top of any policy, a hard-coded **protected floor**
keeps `governance/`, `scripts/`, `tools/`, `.github/`, `.claude/`, `.kiro/`, `.cursor/`, `.agents/`,
`web/`, `CLAUDE.md`, `CODEOWNERS` and deployment config at L3 (`web/data/**` stays bot-only), and a
**structural floor** holds by what a path IS, wherever it sits: any dot-file or dot-folder segment
(`.vscode`, `.envrc`, `.githooks`, `.gitattributes`, ...), any non-Markdown file at the tier root,
agent instruction files at any depth (`AGENTS.md`, `GEMINI.md`, a nested `CLAUDE.md`), script,
build and configuration files at any depth, template hooks, and names a filesystem could resolve
differently than they are classified (control or invisible characters, `:` streams, a trailing dot
or space, 8.3 names like `SCRIPT~1`) are all L3; so is a symbolic link or submodule pointer
(recheck U3). A name list is always one entry short, so the floor does not depend on one. A policy
that is empty, partial, has a catch-all rule, or gives agents more than L0 is refused (exit 6).
`.memory/` (mem's per-machine state) is refused for everyone (`LOCAL-STATE`).

**What is judged is what is committed.** git's file listings are read NUL-separated with
`core.quotePath=false`: with git's defaults a non-ASCII name came back quoted and escaped, matched
no rule and passed as L0, and a secret in `café.md` was never scanned (recheck U1). `check
--staged` reads the index and `--range` the head of the range, not the working tree, so a staged
file that was edited or deleted on disk is still checked.

**Paths are normalised before matching** (01-F4): separators, `.`/`..` segments, Unicode NFKC and
case are folded, so `Context/x`, `context\x` and a long-s `\u017fcripts/` are all classified as the
protected folder. **A rename counts as a deletion of its source** (01-F3), so moving canon into
`log/journal/` needs the source's level.

**Attribution** (01-F5/F6, 10-F3): a new note's `author` is set from git by `stamp` and checked
against the introducing identity; an existing note's `author` never changes (stamp restores it; a
change to it fails, recheck U2); in range mode every changed note, new ones included, is checked
against the author of the last commit touching it (U4), and a commit by an unregistered email fails. A blank git email is a
blocking `IDENTITY` failure; placeholder people with blank emails never match anyone. Derived skill
copies are compared **byte for byte** (01-F7).

**`classify`** prints the highest level a change needs (trusted policy, floor, both sides of
renames; any policy change is L3). CI routes review on it. **`codeowners`** generates
`.github/CODEOWNERS` from the owners in `roles.json` and refuses placeholder GitHub logins.

**Who is acting.** `MEMORY_ACTOR_KIND` (`human` | `agent` | `bot`). If unset, the actor is `agent`
whenever an agent runtime's marker is in the environment (`CLAUDE_CODE_SESSION_ID`, `CLAUDECODE`,
`CLAUDE_CODE_ENTRYPOINT`, `KIRO_AGENT`, `CURSOR_AGENT`, `MEMORY_AGENT`), else `human` (added
2026-09-23: an agent running `git commit` from its own shell was previously judged as the human).
Identity is the git `user.email` matched against `roles.json` `people`.

**What `check` enforces** (FAIL blocks, WARN advises):

| Kind | Code | What |
|---|---|---|
| FAIL | `ACCESS-LEVEL`, `ACCESS-PROJECT`, `ACCESS-DERIVED`, `ACCESS-BOT` | write above the actor's level (skipped with `--no-access`, which CI uses because review enforces the level); outside a maintainer's projects; a derived skill copy that differs by any byte; a bot-only path (a warning only in a repository's first commit) |
| FAIL | `SECRET-FILE`, `SECRET-CONTENT` | `.env`, keys, and ten credential patterns (exit 3) |
| FAIL | `INJECTION` | imperatives aimed at future agents (override, pipe-to-shell, force-push, conceal), outside instruction paths |
| FAIL | `SENSITIVITY`, `LEVEL-MISMATCH`, `FRONTMATTER`, `ATTRIBUTION` | wrong tier for a confidentiality; declared level vs path; missing fields; `author`/`updated_by` not matching the committer |
| FAIL | `GRAPH`, `DUPLICATE`, `NOISE`, `ADR-STATUS` | no relations; >= 85% similar to an existing note; journal > 80 lines or a pasted transcript; bad ADR status |
| FAIL/WARN | `CLAIM-ID`, `FEATURE`, `FEATURE-COVERS`, `TRIAL`, `CORE-SIZE`, `WRITEBACK` | section 3.4 and 3.6 |
| FAIL | `IDENTITY` | git `user.email` is blank (when attribution is checked) |
| WARN | `IDENTITY`, `GRAPH`, `POLICY` | unregistered identity; forward reference to a note that does not exist yet; this change edits `roles.json` |
| FAIL | `SENSITIVITY` (location) | a note under `context/restricted/` that is not `confidentiality: restricted` (07-F7) |

**`cascade`**: when an L1-L3 note changes, stamps `review_needed` on notes that depend on it
(dependency edges only, depth 1, capped at 8). Agents reading a stamped note must say so.

### 4.2 `mem.py`: the reader and the verbs

**Read**

| Verb | Does |
|---|---|
| `load [<ask>] [--mode M] [--feature T] [--touching P] [--add T] [--ref R] [--full] [--print] [--json]` | the entry protocol (4.2.1). Exit 0 loaded, 2 ambiguous |
| `resolve <ask> [--touching P]` | which feature(s) and which mode, with scores and reasons |
| `recall <query> [--ideas]` | ranked claims with ids and a reason each (4.2.4) |
| `context` / `session start\|evict\|show` / `moved [--fetch] [--throttle N]` | ledger, lifecycle, "did anything I loaded change upstream" |
| `compile` | writes `.memory/pack/claims.jsonl` and `features.json` |

**Write**: `remember <claim> [--feature T | --note P] [--category C]` (routes above-L0 to a
proposal automatically), `retire ^id [--by ^id]`, `gap <what> [--feature T]`, `gaps`,
`feature new <name> --covers G [--owner H] [--depends T] [--status S]`, `features`,
`propose <title> --target P --text T [--why W]`, `approve <proposal> [--apply]` (people only).

**Steer**: `pin|unpin|mute|unmute <^id | title>` (personal, `.memory/prefs.json`), `why ^id`.

**Experiment**: `try <hypothesis> --change L [--for H] [--days N] [--evals F]`, `trials`,
`keep <slug>`, `drop <slug> --result R`, `expire`, `eval [--trial S] [--file P]`,
`diff [--since R] [--to R]` (what the team *believes* changed, claim by claim).

**Govern**: `status`, `brief`, `who`, `can <handle> <path>`, `role <handle> <role>` (owner only,
edits `roles.json` in place), `core init`.

Exit codes: `0` ok, `1` a test/check failed, `2` ambiguous (ask one question), `4` not permitted,
`5` invalid input.

#### 4.2.1 The entry protocol, step by step

```
WHO      acting person/role/function/restricted_read; actor kind; write cap
REF      latest (<branch>@HEAD, the working tree) unless --ref: a sha, a date (main@YYYY-MM-DD ->
         last commit that day), a branch, or trial/<slug>. Past refs read files via `git show`.
         A live trial whose `for:` names this person is overlaid automatically (canary).
CORE     CORE.md in full, and the feature map (computed on every load from features/).
RESOLVE  score every feature (4.2.2); confident -> target(s); not confident -> exit 2 with the
         top three and the exact re-run command. Explain asks fall back to decisions (4.2.2).
MODE     earliest intent word in the ask (4.2.3).
SCOPE    by mode and direction (4.2.3).
FILTER   personal pins added, mutes removed, restricted notes withheld without restricted_read.
LEDGER   skip notes already in this session's context at >= the needed depth and same hash.
CACHE    render each note block once per (content hash, depth) into .memory/cache/.
BUNDLE   one Markdown file .memory/bundles/<hash>.md: receipt, then blocks in role order.
RECEIPT  printed: ref, mode and why, notes by role with depth, how it resolved, token estimate,
         cache hits, already-in-context, withheld, and how to steer.
```

The agent's instructions (`CLAUDE.md` section 1, the skill, the Cursor rule, the Kiro steering)
say: run it, read the one bundle, post the receipt's first line, ask one question on exit 2.

#### 4.2.2 Resolution scoring (`resolve`)

| Signal | Score |
|---|---|
| `--feature` names it | +100 |
| a `--touching` path matches its `covers:` | +12 per path |
| a file path in the ask is covered by it | +10 |
| its title appears verbatim | +9 |
| a word of its title | +4 per word |
| an alias matches as a phrase | +7, +3 per extra word (a phrase beats a file stem) |
| a word in the ask is the stem of a file it covers (>= 4 letters, not generic) | +7 per stem, max 2 |
| words shared with its card | +1 per word, max 4 |

Confident when the top score is >= 7 and either the runner-up is <= 60% of it or the top is >= 12.
A second target is added when the runner-up is >= 85% of the top. For **explain** asks with no
confident feature, decisions are ranked by title words (x4) and body words (x1, max 6); confident
when the top is >= 4 and >= 1.5x the runner-up. **Orient** never asks: a confidently resolved
feature's card is added (role `about`), otherwise the core alone.

#### 4.2.3 Modes and scope

Mode = the intent word that appears **earliest** in the ask (orient, plan, review, explain, debug,
change, build word lists in `detect_mode`). With no intent word, a **symptom** ("has no", "keeps
...ing", "wrong", "times out", "too slow", ..., plus the team's own `protocol.extra_symptoms` patterns
from `roles.json`) means debug; otherwise `plan` for a person whose
`function` is `pm`, else `build`.

| Mode | Loads beyond the core |
|---|---|
| orient | nothing (plus the `about` card if resolved) |
| build | target full; **upstream** 2 hops full; downstream 1 hop as cards |
| change | target full; **downstream** 2 hops full; upstream 1 hop as cards |
| debug | build's scope + `log/` notes from the last 30 days that link to or mention the scope |
| review | targets (their contracts) + downstream 1 hop as cards |
| plan | every feature card, proposed decisions, open proposals (titles), gaps, 14 days of journal titles |
| explain | target + the decisions it `implements`/`supersedes` and their supersede chain; features implementing a decision target as cards |

Hop counts and windows are `roles.json` `protocol` values. `relates_to` is never followed.

**Asking instead of guessing.** When the mode is a guess (no intent word, no symptom, no `--mode`,
no `--feature`) or the feature is unclear, `mem load` loads nothing and exits 2 with one prompt of at
most two questions, `mode` and `feature`, each with ranked options (best guess first) carrying the
args to rerun with; `--json` prints them as `{"ask_the_person": [{id, header, question, options:
[{label, description, args}]}], "rerun"}` so Claude Code can show them with AskUserQuestion. The
feature question always offers "None of these" (`--mode orient`). The question and the later answer
are logged locally in `.memory/logs/asks-YYYY-MM.jsonl` under a salted hash of the ask, never its
text; `mem asks` reports how often each guess was accepted or corrected and names the fix
(`protocol.extra_symptoms`, feature `aliases:`). `protocol.ask_on_guess: false` restores the
guess-and-flag behaviour. **[verified: tools/test_mem.py, including that the log holds no ask
text]**

#### 4.2.4 Recall ranking

`score = relevance x authority x freshness x state` (+100 if pinned). Relevance is the share of the
query's information the claim covers, IDF-weighted over all claim texts (claim-word matches count
fully, note-title matches half). Authority: CORE 1.0, accepted decisions and features 0.9, context
0.8, projects 0.6, unaccepted decisions 0.6, unlisted paths 0.5, log 0.3, trials 0.2, evals 0 (evals
are excluded anyway). Freshness halves every 30 days for L0 notes and is 1.0 for L1+ ("an old
strategy is not a wrong strategy"). Recall logs the ids shown and why to `.memory/logs/`, with the
query **hashed with a per-machine salt**, never stored in clear.

#### 4.2.5 Trials

A trial note lists changes, one per line: `add to "Note": [cat] text`, `replace ^id with: [cat]
text`, `retire ^id`. Loading applies them as an overlay to an in-memory corpus (never to files).
It applies automatically to people in `for:` (canary), or to anyone with `--ref trial/<slug>`.
`mem keep` applies the changes to the real notes **through the level rules** (an agent keeping an
L1 change gets a proposal); `mem drop` closes it and writes the result to the journal; expired
trials are closed by `mem expire` (run after every `sync pre`). Overlapping live trials that touch
the same claim are warned about when opened.

#### 4.2.6 Evals

`- [eval] recall "<q>" includes (^a ^b) [excludes (^c)] [top N]` and
`- [eval] resolve "<ask>" [touching "<path>"] feature "<title>" [mode M]`. `mem eval` runs all of
them (exit 1 on any failure); `mem eval --trial <slug>` runs them with the trial overlaid and
reports what it changes, so a trial can be judged before anyone keeps it.

### 4.3 Local state: `.memory/` (gitignored, per checkout)

```
.memory/
  cache/<hash32>-<depth>.md          rendered note blocks, each with an envelope: note hash, depth, HMAC
  bundles/<sha256-of-bytes>.md       the file an agent reads for one load; content-addressed, immutable
  session/current                    fallback session id
  session/<prefix>-<hash16>.json     ledger (version 2): ref, turn, {note: depth, hash, contract, turn, evicted}
  session/<key>.receipt.json         the last receipt of that session
  session/<key>.moved                that session's `mem moved` throttle stamp
  session/<key>.lock                 per-session lock for read-modify-write
  pack/claims.jsonl, features.json   compiled by `mem compile`
  logs/recall-YYYY-MM.jsonl          ids shown + reasons, query salted-hashed
  prefs.json                         personal pins and mutes
  placeholders.json                  playbook <PLACEHOLDER> values (never credential-like ones)
  locks/<hash>.lock                  one writer at a time for a playbook or its run log
  prompted-<key>.json, playbook-begin-<key>.json   per-session marks
  salt                               per-machine random secret (0600), the key of the cache HMAC
```

**Concurrency and integrity (audit area 04).** Every write goes to a unique temporary file, is
fsynced and atomically renamed. A session's ledger is read-modified-written under a per-session
lock, and it is written **last**, so a load that fails to save marks nothing as delivered. Bundles
are named by the hash of their bytes, so no session or repeat load can overwrite another's. A cache
block is served only if its envelope names the exact note version and depth and its HMAC, keyed
by `salt`, matches; a block re-signed with a recomputed sha256 is not served (04-F4). Anything else
is regenerated. A ledger of the wrong shape is quarantined (renamed `.corrupt-<time>`) with one
warning and rebuilt; any other local file of the wrong shape or with a bad byte is ignored, never a
traceback (N4, N5). `mem playbook log`, `caveat` and `approve` run under a per-file lock and write
atomically: 32 concurrent `log` calls keep all 32 lines (N2). Locks are stale when their owner
process is gone or after 60 s, and are stolen by rename, so two waiters cannot both take one.
Cached copies, bundles, placeholder values and per-session marks untouched for 14 days are deleted
at each `session start`; `mem session purge` deletes them all (N6).
**[verified: 8 concurrent loads into one session and into eight sessions, all succeed, none lost]**

**Session id** resolution: `--session`, then `MEMORY_SESSION`, then `CLAUDE_CODE_SESSION_ID`
(Claude Code exports it to Bash tool commands, and hooks receive the same id on stdin, read with
`--hook`), then `session/current`. An id must be a string of 1-200 characters with no control
characters (a bad hook id is exit 5); its file name is a readable prefix plus a hash of the exact
id, so distinct ids never share a ledger. Claude Code keeps separate ledgers for two sessions in
one checkout; Kiro and Cursor share one ledger per checkout.

**Contract alerts**: the ledger stores each loaded note's content hash and `## Contract` hash.
`mem moved` compares them with the working tree and (with `--fetch`) the upstream branch, and
prints `memory: YOUR CONTEXT MOVED` plus `CONTRACT CHANGED` when the promise itself changed. Its
throttle is per session and advances only after a completed comparison.

### 4.4 `sync-memory.*`: moving notes between machines

`sync-memory.py` is the dispatcher every hook calls. It normalises the mode (no argument = `pre`,
any case), holds **one lock** across native `pre`, `mem compile` and `mem expire` (a busy lock is
exit 75, never a silent success), sets `MEMORY_ACTOR_KIND=agent` with `--agent`, and runs Windows
PowerShell 5.1 (`powershell`, falling back to `pwsh`) on Windows, bash elsewhere.
On Windows an agent hook's `post` commits like everywhere else; `MEMORY_SYNC_WINDOWS_POST=0`
pauses it on one machine.

**Pull-request mode.** With `enforcement.mode: "pr"` in the policy at HEAD (or
`MEMORY_SYNC_MODE=pr`), `post` on the default branch commits and rebases locally as usual
(`MEMORY_SYNC_DIRECT_PUSH=0` tells the native script not to push), then the dispatcher pushes the
unpushed memory commits to the person's own branch `memory/<who>` (their handle in `roles.json`, or
for an unregistered address its local part plus a short hash, so alex@a and alex@b never share a
branch) and keeps one
pull request open for it with `gh`, or prints the compare link. In direct mode a push the server
refuses because the branch is protected is exit 7 from the native script, and the dispatcher takes
the same path. `main` is never force-pushed; `memory/<who>` is rewritten only with
`--force-with-lease`, and only after checking that every file the remote branch changed already
has that content in `HEAD` or in the base branch (so the branch a squash-merged pull request left
behind is reused, and a teammate's unique commit is refused, exit 1). Before every `pre` and `post`
with unpushed commits, the dispatcher fetches and moves past local commits whose files already read
the same upstream: a squash merge lands as one new commit, and replaying the second of two edits
to one file onto it used to conflict with its own result (recheck P1). A pull's autostash no longer
unstages what the person staged: the dispatcher saves the index and restores every entry upstream
did not change (N1). The lock is stale only when its owner is a process on this machine that is
gone, or when it is 30 minutes old and its owner is not known to be alive; stealing renames it
first, so two waiters cannot both take it. On a feature branch nothing changes: a project tier's
notes ride the code pull request. **[verified: tools/test_sync.py, a protected bare remote, both
native scripts for exit 7 and commit-only, the dispatcher for fallback, reuse, squash-merge,
refusal and the gh path with a fake CLI]**

- **pre**: refuses a detached HEAD; `pull --rebase --autostash` against the **configured upstream**;
  any unmerged path afterwards (including a failed autostash re-apply) is exit 2 naming the files;
  registers the Basic Memory project, refreshes skill copies, prints one summary line.
- **post**: fails closed (exit 6) if the guard or a Python 3.9+ interpreter is missing. Builds the
  commit in a **temporary index** holding `HEAD` plus this tier's working-tree changes only, so
  nothing the user staged elsewhere can ride along and the user's own index is never reset; runs
  `guard stamp` and `guard check` (exit 3/4/5/6 stops) and a secret scan on exactly that tree;
  commits with `Sync-Actor`/`Sync-Agent`/`Sync-Host` trailers. Pushes to the configured upstream only
  if **every** unpushed commit stays inside this tier (a project-tier hook no longer pushes
  application commits). Never force-pushes.
- Exit codes: 0 ok, 1 error, 2 conflict, 3 secret, 4 denied, 5 invalid, 6 policy unenforceable,
  7 push refused by a protected branch (native scripts; the dispatcher opens a pull request),
  64 bad usage (dispatcher), 75 busy.

**[verified: bash, 11 scenarios from audit area 06 against local bare remotes, tools/test_sync.py]**
**[verified: PowerShell, the same 11 scenarios on Windows PowerShell 5.1, 2026-09-25, run on a Windows
machine. The file stays pure ASCII, enforced by a test.]** `test_sync.py`
tests the dispatcher's implementation for the platform by default; `--impl all` tests both.

### 4.5 Memory Atlas

`scripts/build_atlas.py` builds `web/data/graph.json` (schema 4: schema 3 plus a `playbooks` array with derived trust and counts only); `web/` renders it. The page is a
React app in `web/app/` built by Vite into ONE committed file, `web/index.html` (every script and
style inlined; `npm run check-build` fails if it drifts from its source), whose two inline scripts
are pinned by sha256 in the `vercel.json` CSP. Its main view draws the memory as a sky on a canvas:
a deterministic sunflower layout per cluster computed in the browser from the notes, so nothing ever
overlaps; a grid of cards is the plain alternative. `web/SPEC.md` has the design and its proofs.

- **Public build** (default): restricted notes omitted, and so is **every trace of them**: links to
  them are dropped rather than reported as broken, their paths are removed from activity, and the
  build refuses to write a file in which any restricted id, path or title appears anywhere (07-F1).
  A note under `context/restricted/` is restricted whatever its label says (07-F7). Bodies withheld
  unless `confidentiality: open`; summaries, feature cards and proposal summaries withheld above
  `publication.brief_levels` (L0); contracts, commit messages, trial and eval content, trial
  hypotheses and audience names, gap text, feature `covers` and local session ledgers withheld.
  Author, editor, agent and owner fields are withheld when `publication.publish_authors` is false
  (07-F4). A note whose title is itself sensitive sets `public_title:` or `publish_title: false`
  (07-F6): it is then published under an opaque id and path (`decisions/withheld-1`), relations to
  it still resolve by its real title, and its real title, id and path join the leak sweep. Titles
  otherwise publish, by design, because they are the map. Activity lists only the paths of notes the
  map publishes, under their public names: never code paths, never a note's earlier path.
- **Full build** (`--full`, local only): everything, plus the last 10 session ledgers.
- **Verification** (07-F2/F3): `build_atlas.py --verify FILE` checks a **closed schema** (every key
  and type allowed at every level, list items and dict values included; unknown fields, duplicate
  JSON keys, duplicate ids and references to non-public notes all fail), then every publication rule
  against the POLICY's publication settings, never the file's own claim, then rebuilds the public
  graph from the notes and requires the file to match it exactly (apart from `generated_at`).
  `--shape-only` skips the rebuild and uses the strictest settings unless `--policy` names a
  `roles.json`. `tools/test_atlas.py` proves every tampering case fails.
- **Rendered page** (07-F5): `web/test` uses the full build of the same corpus as an oracle; every
  withheld string becomes a marker and none may appear in the page's text or markup; a withheld
  NAME is a marker whatever its length, matched as a whole word, and the redacted fixture omits
  notes so that check has a denominator; negative tests render a long and a short marker on purpose
  and both must be caught. `web/test/browser.mjs` repeats the geometry checks in a real Chrome and
  loads the page under the deployed CSP. Dependencies are pinned by `web/package-lock.json`.
- **Publication is manual** during containment (`atlas.yml` is `workflow_dispatch` only), and runs
  the redaction tests and the page tests before generating.

### 4.6 Project scaffolding

`scripts/new_project_memory.py <repo> [name] [--update] [--no-hook]` (the `.sh` and `.ps1` files
are thin wrappers that find Python and run it: one implementation for every platform, after the
two shell copies drifted apart and each had its own bugs, 08-F3..F10) creates `memory/` (notes from
`templates/project-memory/memory/`), copies `sync-memory.*`, `memory_guard.py`, `mem.py` and
`governance/roles.json`, and gives the code repository the **same** agent wiring as the company
tier: `.claude/settings.json`, `.kiro/hooks/*`, `.claude/commands` and `.cursor/commands` are
derived from the company tier's own files with every script path pointed at `memory/scripts/`, so
the Stop significance hook and the Kiro prompt hook are there too. On GitHub it adds
`.github/workflows/memory-gate.yml` and the memory block of `.github/CODEOWNERS`, which also owns
the gate workflow and CODEOWNERS itself and must be the file's last lines.

Behaviour, each with a test in `tools/test_scaffold.py`:
- the new tier is stamped from the git identity and passes its own guard before anything is committed;
- the printed commands commit everything the tier needs, `.github` included, with
  `sync-memory.sh` executable;
- a local `.git/hooks/pre-commit` runs the guard for commits that touch `memory/` (never replacing
  an existing hook or a configured `core.hooksPath`);
- a name with `/`, `&`, quotes, capitals or no usable letters is refused before anything is written,
  and the title is inserted literally (no sed);
- an existing file is never overwritten: it gets a `.team-memory.suggested` twin that the report
  names; a folder in the way (a `.claude` FILE) is an error, exit 7, and nothing under it is
  reported as created;
- rerunning reports DRIFT when the company's engine or policy changed; `--update` refreshes the
  engine (scripts and skill), never the notes or `roles.json`;
- an invalid `memory/governance/roles.json` stops it (exit 6).

In a project tier `context/`, `decisions/` and `CORE.md` are **L1** (`paths.project_rules`), as
`levels.L1` has always said; they are L2 only in the company tier (11-F5).

### 4.7 Agent integration

| | Claude Code | Kiro IDE | Cursor | Claude Desktop |
|---|---|---|---|---|
| Rules | `CLAUDE.md` | `.kiro/steering/memory.md` | `.cursor/rules/memory.mdc` | project instructions |
| Procedure | skill `.claude/skills/team-memory` | skill `.kiro/skills/team-memory` | `.agents/skills` (native) | - |
| Pull + ledger at start | `SessionStart` startup/resume/clear: `sync pre --agent`, `mem --hook session start` | `SessionStart`: ONE action, `sync pre --agent --then-session`, so the order is fixed (IDE only) | by hand | by hand |
| After compaction | `SessionStart` matcher `compact`: `mem --hook session evict` | none | none | none |
| Context moved | `UserPromptSubmit`: `mem --hook moved --quiet --fetch --throttle 300` | `UserPromptSubmit` hook **[unverified trigger]** | by hand | - |
| Commit at end | `Stop`: significance prompt, `sync post --agent` | `Stop`: ONE action, `sync post --agent --significance` | by hand | by hand |
| Commands | `/cairn /cairn-context /cairn-recall /cairn-remember /cairn-gaps /cairn-try /cairn-feature` (`.claude/commands/`) | - | `.cursor/commands/` **[unverified format]** | - |
| Permissions | allow named `mem.py` verbs (load, recall, why, remember, gap, try, keep, playbook find/run/log, ...), guard check/stamp/classify/significance, sync, read-only Basic Memory tools; deny `mem role`, `mem playbook approve`, `mem core init`, `codeowners --write`, `delete_note`, `delete_project`, force-push, `--no-verify` | autoApprove read tools | - | - |

Claude Code behaviour above was checked against the current docs on 2026-09-23 (hook events and
matchers including `compact`, plain stdout added to context for SessionStart and
UserPromptSubmit, `.claude/commands/` still supported, `CLAUDE_CODE_SESSION_ID` from CLI 2.1.132)
through a documentation lookup, not by running Claude Code.

A project tier gets this same wiring, derived from these files (section 4.6). Slash commands pass
their arguments as one string; `mem load`, `gap` and `remember` take flags written inside it
(`/cairn-context fix the export --mode debug`) as flags (09-F5). `mem status` and `mem context`
print who is acting and how high they may write (09-F7). An agent's `mem keep` of a trial above
its level writes a proposal instead of the change (05-F2), and `mem remember --category decision`
writes a proposal, never a journal observation (09-F4).

### 4.9 Playbooks (ADR-005)

A playbook is `playbooks/PB-XXXX-<slug>.md` (type `playbook`, L0) with `## Before you start`,
`## Steps` (`### N. title [check|local|external]`, each with `Run:` and `Check:`), `## Caveats`
(`- [blocker|fix|warning] (step N) text`), `## Verify`; its run log is `PB-XXXX-<slug>.runs`, one
line per run: `YYYY-MM-DD <handle> success|failed|partial <steps hash> <note>`, merged with git's
`union` driver (`.gitattributes`).

- **Guard** (`validate_playbook`, `check_playbook_approval`, `check_runlog`; staged and range
  mode): id `PB-` + 4 Crockford base32, unique in the tier; steps numbered 1..N; known markers;
  a step without `Check:` or a marker is a warning; home paths, 12-digit numbers, private IPs and
  unknown emails are warnings (placeholders); pipe-to-shell is a warning in a playbook and
  highlighted at replay, other injection patterns still fail; run logs are append-only (removal,
  edit or deletion fails) and every new line names the committing person (per commit in a range);
  `approved_by` / `approved_steps` may be set only by a person (never an agent, including a commit
  with `Sync-Actor: agent`) whose level reaches `approve_level` (L1 project tier, L2 company tier),
  naming themselves, against the current steps hash.
- **Trust** (`playbook_trust`, shared by the guard, `mem` and the Atlas): `approved` if the
  approval is valid for the current `steps_hash`; else `reproduced` if someone other than the
  author logged a success against it; else `unreviewed`; `stale` when the last success is over 90
  days old.
- **`mem playbook`**: `save` (validates exactly as the guard will, assigns an id, exit 2 on a
  similar playbook with `--update`/`--new`, exit 3 on a secret, exit 5 on a bad draft), `find`
  (title > tags > steps > caveats, typo tolerant, `--regex` with a length cap, `--tag`, both
  tiers), `show`, `run` (a guided-run bundle: banner, trust, environment mismatch, placeholders
  with `--set` remembered per machine, each caveat before its step, ask-first labels, pipe-to-shell
  highlighted), `log`, `caveat`, `approve`, `stats` (the ADR-005 target), `begin`/`since`,
  `export` (a checklist), `list`. `mem` never executes playbook content.
- **Tiers:** from a project tier, the company tier is found per machine through
  `MEMORY_COMPANY_ROOT`, `memory/.memory/company-root` (written by the scaffold) or Basic Memory's
  project list; results list the project tier first.
- **Discovery:** `mem load` names up to two confident matches in its receipt and in its question;
  the Stop hook, once per session after 8 or more shell tool calls with no playbook saved, asks the
  agent to *offer* `/playbook-save` (it counts tool calls in the host's transcript file and reads
  nothing else from it).

**[verified: tools/test_playbooks.py, 51 checks, each rule shown to fail its tests when removed]**

### 4.10 First-prompt load

Claude Code's `UserPromptSubmit` hook runs `mem --hook prompt`: on the first prompt of a session
(not a slash command, and only if nothing was loaded yet) it runs the entry protocol for that
prompt and prints the receipt, or the question, which Claude Code adds to the agent's context. So
context arrives even when an agent skips its instructions. The session is marked only once the
receipt or the question was delivered, so a failed first load is retried on the next prompt (N3).
Later prompts, and any error (a bad session id included), print nothing and exit 0;
`protocol.load_on_first_prompt: false` turns it off. Kiro and Cursor still rely on the
agent following its rules. **[verified: test_playbooks.py discovery checks]**

### 4.8 CI workflows (not yet exercised on GitHub)

`memory-gate`, `cascade`, `changelog` and `atlas` start with an `instance` job that reads
`governance/roles.json` (from the base revision, for the gate) and skip their real job unless
`"instance": true`. The unconfigured template has no owner and no CODEOWNERS, so these gates could
only fail there; `scripts/init.py` sets the flag. `tests` always runs.

| Workflow | Trigger | Does |
|---|---|---|
| `memory-gate.yml` | pull request | checks out the **trusted base revision** and the PR separately; the base's guard judges the PR's data with the base's policy (safety, format, per-commit attribution; `--no-access` because review enforces the level); runs the base's `test_security.py` **against the PR's guard**, so a PR that weakens the guard goes red; checks CODEOWNERS is generated and names real people; `classify --require-owned` decides the review level and fails when a path above the auto-merge levels would need no CODEOWNERS review (a spelling CODEOWNERS cannot express, such as `AgEnTs.md`). A second job, which runs no PR code, labels the PR (fails if labelling fails) and, when the level is in the BASE policy's `enforcement.auto_merge_levels`, enables GitHub auto-merge (squash). Empty by default, so nothing auto-merges until an owner opts in. |
| `tests.yml` | every PR and push to main | `tools/run_tests.sh` plus the UI suite (`npm ci`) |
| `atlas.yml` | **manual only** (containment) | redaction tests, page tests, build, `--verify --against-source`, commit as the bot |
| `cascade.yml` | push to main | stamps `review_needed` on dependents of a landed planning change and opens one issue (moved out of memory-gate, where it could never run: 10-F6) |
| `changelog.yml` | push to main | appends to `log/CHANGELOG.md` |

All writers to `main` share one concurrency group. The gitleaks action was removed from
memory-gate because it scans the workspace root, which is no longer the PR; the guard's
SECRET-FILE / SECRET-CONTENT scan covers every file in the range.
`tools/test_gate.py` runs the memory-gate job's commands locally in its two-checkout shape against
the audit's 10-F1 attack PR and quieter variants **[verified locally; never run on GitHub]**.

**What makes any of this binding:** `scripts/init.py` records the owner's GitHub login in `roles.json` and writes
CODEOWNERS (or run `memory_guard.py codeowners --write` after changing owners), pushes, and protects `main` (require PRs, Code Owner review and
the `memory-gate` check; dismiss stale approvals) and sets `enforcement.mode` to `pr`, which the
sync reads (formerly 11-F6: the field was documented and unread). With `auto_merge_levels`
non-empty, `codeowners` still writes the owner catch-all FIRST (so a path no rule names is never
unowned), then each path rule in reverse (above those levels naming the people whose role reaches
it, auto-merge levels naming nobody), then the protected floor and the structural floor's patterns
(dot-files, instruction files, scripts at any depth) naming the owners, because GitHub applies the
last matching line while roles.json applies the first **[verified: test_security, including a policy that demotes
`scripts/` still leaving it owned]**.

---

## 5. Flows

**A session in Claude Code.** Start: pull, open ledger. First task: `mem load "<ask>" --touching
<files>` -> read the bundle -> post the receipt line -> plan and execute. Mid-task: `mem load --add`,
`mem recall`. Each prompt: `mem moved` speaks only if something loaded changed upstream.
Compaction: ledger marked evicted; the next `load` re-reads from cache. End of turn: significance
prompt; `sync post` stamps, checks, commits, pushes.

**An agent learns something.** L0 fact: `mem remember "<fact>"` -> journal note with an id, linked
to the resolved feature. Fact about a feature: `mem remember "<fact>" --feature X` -> the feature is
L1, so a proposal is written with the exact line and target. A person with the role runs `mem
approve <proposal> --apply`. Changed covered code without updating the feature -> `WRITEBACK` warns.

**A planning change.** An L1-L3 note changes -> `cascade` stamps `review_needed` on its dependents
-> agents loading those notes report it -> a steward re-reads and clears.

**An experiment.** `mem try "<hypothesis>" --change '...' --for ana --days 14` -> Ana's loads see
the change; nobody else's do -> `mem eval --trial <slug>` compares retrieval -> `mem keep` (through
the level rules) or `mem drop --result "..."` -> expiry closes it otherwise.

**A past version.** `mem load "<ask>" --ref main@2026-09-01` reads every note as of the last commit
that day; the ledger resets when the ref changes, so versions are never mixed.

---

## 6. Configuration reference

`governance/roles.json` sections: `levels` (labels, examples, paths, who may change), `people`
(handle -> name, email, github, role, function, restricted_read, projects), `roles` (order, max
level, may propose up to), `paths` (rules, default), `sensitivity`, `cascade`, `protocol`
(default_ref, upstream_hops 2, downstream_hops 2, card_max_words 150, debug_journal_days 30,
plan_recent_days 14, moved_check_every_seconds 300, core_max_tokens 3000, code_root), `publication`
(brief_levels, publish_commit_messages, publish_authors), `significance` (tiers, journal_max_lines
80, duplicate_similarity_threshold 0.85), `enforcement` (mode direct|pr, auto_merge_levels).

Environment: `MEMORY_ACTOR_KIND`, `MEMORY_ACTOR_EMAIL`, `MEMORY_AGENT`, `MEMORY_SESSION`,
`MEMORY_SESSION_ID` (significance hook), `MEMORY_CODE_ROOT`, `MEMORY_SYNC_QUIET`,
`MEMORY_SYNC_NO_PUSH`, `MEMORY_SYNC_REMOTE`; read from runtimes: `CLAUDE_CODE_SESSION_ID`,
`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `KIRO_AGENT`, `CURSOR_AGENT`.

---

## 7. Invariants

Each with where it is enforced and the test that shows it failing when broken.

1. **A note's level comes from its path, never from what it declares, and never from a policy the
   same change edits.** Guard `LEVEL-MISMATCH`, `ACCESS-LEVEL`, trusted-base policy, protected floor,
   path normalisation, rename-source check. test_guard, test_security, test_gate.
2. **An agent never writes above L0**, with or without `MEMORY_ACTOR_KIND`. Guard; `mem approve`,
   `mem role` refuse agents; `mem remember`/`keep` route to proposals. test_guard ("agent marker ->
   DENIED"), test_mem write verbs; end to end through `sync post` with only `CLAUDE_CODE_SESSION_ID`
   set: exit 4 **[verified]**.
3. **Attribution comes from the git identity**, for new notes too, and never from a blank email.
   Guard `stamp`/`ATTRIBUTION`/`IDENTITY`; range mode checks every note against its commit author.
   test_security.
4. **A claim id never names two different claims in one tier** at one moment. Guard `CLAIM-ID`.
   test_guard. **Not yet true over time:** the one-for-one carry rule can hand an id to an unrelated
   fact, and reordering can swap ids (audit 02-F2/F3, Phase 3, not fixed).
5. **`relates_to` is never followed** by scope or cascade. test_mem ("Billing see-also never
   included").
6. **Scope is directional**: build never loads downstream in full; change never loads upstream in
   full. test_mem directional scope.
7. **Nothing already in context is repeated** in a session unless it changed, deepened, or was
   evicted. test_mem ledger.
8. **Versions are never mixed**: a ref change resets the ledger; past refs read from git objects.
   test_mem refs.
9. **Restricted content never reaches a person without `restricted_read`** through `load` or
   `recall`, and never reaches a public atlas. test_mem, test_atlas.
10. **A trial changes no file until kept, and keeping obeys the level rules.** test_mem trials.
11. **The public atlas contains nothing withheld**, including derived fields, and has no field the
    schema does not name. Build-time restricted-token sweep; `build_atlas --verify` (closed schema)
    and `--against-source`; test_atlas (25 tampering cases, each red); web/test privacy oracle.
14. **The judge is never the judged.** In CI the base revision's guard, policy, classifier and
    security tests judge the PR. test_gate (the audit's 10-F1 PR is red and classified L3).
15. **A commit made by sync contains only its tier**, and a push only memory commits. test_sync.
16. **A failed load marks nothing as delivered; concurrent loads lose nothing.** test_mem area 04.
12. **The reader and the enforcer parse notes identically**: `mem.py` imports the guard's parsers.
13. **Skill copies are byte-identical to the canonical skill.** Guard `ACCESS-DERIVED`;
    `run_tests.sh`.

---

## 8. Test coverage

| Suite | Count | Covers |
|---|---|---|
| `tools/test_guard.py` | 22 | claim ids and carry-forward, trailing references, features and write-back, levels for new folders, agent-marker default, project tier from repo root |
| `tools/test_security.py` | 57 | the audit's access/attribution BLOCKERs as regressions; a key prefix must start a token (a CSS name like `mask-image-linear-to-color` is not a key): policy self-demotion, empty policy, the floor, renames, case and Unicode tricks (range mode too), forged and blank authors, derived bytes, public paths, CODEOWNERS (catch-all and level-aware), open-under-restricted; the actor override inside an agent runtime; injection phrasings, with a benign negative. Never imports the guard under test (a guard that exits 0 at import once ended a run green) |
| `tools/test_gate.py` | 6 | the memory-gate job in its two-checkout shape: the 10-F1 attack PR, a quiet policy demotion, a demoting rename, an honest L0 note |
| `tools/test_mem.py` | 106 | resolution and modes (including CI and AI-quality symptoms, asking instead of guessing, `mem asks`, team `extra_symptoms`), directional scope, ledger, cache, privilege, hooks, moved and refs, **area-04 concurrency and damage** (parallel loads, bundle isolation, UTF-8 past refs, cache tamper, session-id collisions and injection, per-session throttle, failed-save retry, corrupt ledgers, purge), write verbs, trials, evals |
| `tools/test_parsers.py` | 6 | fenced/inline code ignored by claim and relation parsers |
| `tools/test_atlas.py` | 47 | content, restricted traces, open-under-restricted, publish_authors, 25 tampering cases, duplicate keys, `--against-source`, bare `--out` |
| `tools/test_init.py` | 16 | `init.py` on a fresh copy: owner row, instance flag, CODEOWNERS, filled placeholders, stamps, git identity, template-only files removed, a clean guard check and first commit; refuses a second run, a bad email, a bad login, `--yes` without `--github` |
| `tools/test_sync.py` | 25 per platform (bash on Linux/macOS, PowerShell on Windows); 38 with `--impl all` | 11 area-06 scenarios plus a protected main (exit 7, commit-only) per implementation against bare remotes; dispatcher mode/lock/usage; pull-request mode end to end (fallback, one branch per person, squash-merge then pre, refusal to overwrite, gh with a fake CLI); ASCII-only PowerShell |
| `tools/test_playbooks.py` | 51 | save (id, author, similar, update, no steps, secret), find (ranking, typos, regex), run (banner, caveat placement, markers, placeholders, environment, export), trust (own run, another's run, approval levels, caveats keep it, edits drop it, stats), every guard rule as a negative in staged mode and three in CI range mode, concurrent run logs merged by union, cross-tier find from a scaffolded project, load receipt, first-prompt hook, Stop-hook offer, Atlas trust against a forged label, begin/since |
| `tools/test_scaffold.py` | 7 per platform | a project tier gets its guard, policy, `memory-gate` workflow and CODEOWNERS block; an existing CODEOWNERS is untouched (`.suggested`); a second run changes nothing; the new tier passes its guard |
| `web/test` (`npm test`) | 110 + 9 | UI caps, camera-independent type, **rendered-page privacy oracle** (529 withheld markers on the template corpus), reduced motion, negative tests including a deliberate leak |

Every Python suite checks that the expected number of assertions ran, so a run that stops early is
red. Each new regression was shown to fail against the pre-audit scripts. `tools/run_tests.sh` runs
the Python suites and the UI suite when `web/test/node_modules` exists.

**Not covered by tests:** the Windows CI job has not yet run on GitHub (the PowerShell sync was run by hand on Windows), Kiro and Cursor
behaviour, Basic Memory's handling of `^id` suffixes, the GitHub workflows on GitHub, real
multi-person use, `new-project-memory.ps1`.

---

## 9. Security and threat model

**Assets**: canon (L1-L3 notes), the rules and hooks (L3), restricted content, the integrity of
attribution, and teammates' machines (hooks execute commands there).

**The boundary.** Once `main` is protected (PRs required, Code Owner review, `memory-gate` required),
the boundary is GitHub: a change reaches canon only through a PR that the base revision's code has
judged and an owner has approved. Before that, there is no boundary; the guard on each laptop is a
guard-rail that an agent following its instructions will respect and a hostile process can skip.

| Threat | Control | Holds | Gap |
|---|---|---|---|
| An agent rewrites canon | L0 cap; proposals; review of every PR above the auto-merge levels; `MEMORY_ACTOR_KIND=human` ignored inside an agent runtime with no terminal | CI + review, once protected | locally, a process that drops the runtime's markers, or skips the hook, still writes; only review catches it |
| A PR neutralises the gate (replaces guard, tests, policy) | base-revision checkout judges; base security tests run against the PR's guard; `classify` from the base policy; policy changes are L3 | CI | GitHub behaviour of the two-checkout job never run |
| A policy change authorises itself | trusted-base policy; both policies must allow; protected floor; catch-all and empty policies refused | local + CI | - |
| Path tricks (case, Unicode, renames, quoting) | git listings are NUL-separated and never quoted (a non-ASCII name like `scripts/évil.py` was quoted by git, matched no rule and passed as L0); normalisation (NFKC, case-fold, dot segments); rename sources classified; a symbolic link or submodule pointer is L3 anywhere | local + CI | symlinks on Windows untested (needs Developer Mode) |
| Executable or instruction files where notes go | a structural floor: any dot-file or dot-folder, any non-Markdown file at the tier root, agent instruction files at any depth (`AGENTS.md`, `GEMINI.md`, a nested `CLAUDE.md`), script, build and config files at any depth, template hooks, and names a filesystem could alias (`:` streams, trailing dots, `SCRIPT~1`, invisible characters) are L3; CODEOWNERS owns them, and `classify --require-owned` stops a spelling CODEOWNERS cannot express | local + CI | - |
| What the guard reads differs from what is committed | `check --staged` reads the index, `--range` the head of the range; a staged secret hidden by a clean or deleted working file is caught | local + CI | - |
| mem's local state committed | `.memory/` is refused for everyone (`LOCAL-STATE`) | local + CI | - |
| Note content hijacks an agent | "notes are data" rule; `INJECTION` patterns (overrides, pipe-to-shell, guard variables, `--no-verify`, bypassing a control, text addressed to agents, concealment from the user) | commit | patterns are a list: 0 false positives over 97 real notes, but new phrasings will pass; the instruction is the main control |
| A code PR rewrites a project tier | the project repo's `memory-gate` (base guard, base policy) and its CODEOWNERS memory block, which also owns `memory-gate.yml` and CODEOWNERS itself and must be the file's last lines; the printed commit includes `.github` | CI + review, once protected | the pull request that ADDS `memory/` has no trusted guard to judge it: it is labelled L3 and an owner reviews it by hand |
| Hooks as a remote-code path | hook, script and config roots at L3 under the floor | CI + review | - |
| Secrets committed | guard `SECRET-*`; sync secret scan on the exact committed tree | local + CI | regex-based; novel formats pass; gitleaks removed from CI |
| Out-of-tier files ride along a sync | temporary index; tier-only push | local | the Windows CI job has not yet run on GitHub |
| Restricted leakage | private submodule (a GitHub permission); `restricted_read` filter; atlas omits every trace | GitHub access is real; the filter is advisory on a laptop that has the files | anyone with submodule access reads the files |
| Public atlas leakage | closed schema with typed list items and values; `--verify` compares with a fresh build by default and never trusts the file's own `publication` block; restricted-name sweep (whole words, case-insensitive); a withheld title gets an opaque id and path; activity lists only published note paths (never code paths, never a note's old path); page oracle including short names; manual publication | CI | titles publish by design unless `public_title`/`publish_title: false` |
| Misattribution | stamp from git; a new note's author must be its introducer; an existing note's `author` never changes; every later committer in a range must be recorded in `updated_by`; blank email blocks | local + CI | a person can commit under a teammate's email locally; GitHub shows the pusher, review catches it |
| Local tampering with cache or ledger | cache blocks carry an HMAC keyed by this machine's salt; ledger validation and quarantine; damaged local files are ignored, never a crash | local | a process that can read `.memory/salt` can forge a block, and can edit the notes anyway |
| Credentials in playbook placeholders | a value that looks like a credential fills the output and is never written down; saved values are purged with the session | local | - |

---

---

## 10. Known limitations

- Mode detection is lexical. A bug report that names neither an intent nor a listed symptom
  ("drops captions") gets no confident mode, so `mem load` asks the person instead of loading
  (exit 2, `ask_the_person`); with `protocol.ask_on_guess: false` it loads build and the receipt
  says `A GUESS`. "debug", "investigate", "troubleshoot" and "diagnose" are debug words. A verb that
  is also a feature name ("the **export** is wrong" when Export is a feature) pulls that feature.
- When two features score within 15% of each other, `mem load` asks which one (plan mode too); an
  orient ask shows both cards. With `ask_on_guess: false` it loads both.
- Claim ids are carried by lexical similarity. A true paraphrase that shares few words ("Idle
  sessions expire after 15 minutes" -> "A token with no activity for 15 minutes is revoked") gets a
  new id: the recheck's 20 paraphrases keep 9 ids and move none to another fact. A lost id is
  reported by the guard (`claim id(s) gone from this note`) so a person can put it back; a wrongly
  transferred id would be silent, which is why ambiguous matches get a new id.
- Past 40 features the feature map in a bundle lists the ones near the ask and names the rest.
- A project tier's notes ride the code pull request, so the code review approves them; its
  `memory-gate` labels the level but does not auto-merge.
- Kiro and Cursor share one session ledger per checkout; two concurrent sessions there collide.
- `CORE-SIZE`, token counts in receipts and all "tokens" figures are characters / 3.8 estimates.
- cairn's own `features/` notes were written by an agent from its own code; review them.
- In the template, `roles.json` has an owner placeholder (filled by `scripts/init.py`) and four teammate
  placeholders to replace or delete.

---

## 11. Measurements and results

| Claim | Number | How |
|---|---|---|
| any-link neighbourhood at 3 hops, 3,020-note synthetic corpus | p95 333, max 826 notes | one-off measurement over `tools/gen_fixture.py` output (script not shipped) |
| directed 2 hops on the same corpus | upstream p95 8, downstream p95 12 | same |
| composition of cairn's own notes at the time | 72.7% prose, 18.6% claims (chars) | one-off measurement (script not shipped) |
| claim-id carry-forward | 4/5 realistic edits keep their id; 9/20 deep paraphrases, 0 moved to another fact | test_guard fixture; test_claims (the recheck's 20 pairs, a ratchet) |
| feature map at 208 features | under 3,000 tokens for a build load | test_protocol |

---

## 12. Unverified claims

- Kiro: the `UserPromptSubmit` trigger in `.kiro/hooks/memory-prompt-moved.json`, and whether Kiro
  adds command output to context. Cursor: that `.cursor/commands/*.md` are picked up, and that it
  has no session hooks.
- Claude Code specifics were confirmed from documentation, not by running Claude Code.
- Basic Memory's treatment of the `^id` suffix on observation lines and of our extra frontmatter.
- Provider prompt caching reducing the cost of repeated bundles.
- GitHub Action versions (`actions/checkout@v7`, `setup-python@v6`, `setup-node@v5`), the
  two-checkout memory-gate job, label creation permissions, and fork-PR token behaviour. (The gate no
  longer relies on `pull_request.user.email`.)
- `new-project-memory.ps1` (now a wrapper around `new_project_memory.py`) and a generated project
  tier's hooks on Windows, the owner check of the PowerShell lock, and Windows PowerShell's handling
  of non-ASCII git output after `[Console]::OutputEncoding` is set to UTF-8. `sync-memory.ps1` itself
  was verified on Windows on 2026-09-25; the windows-sync CI job runs the new cases.
- Windows code pages in general: UTF-8 is now explicit for git output (04-F3), verified only by
  simulating a non-UTF-8 locale on Linux.
- The synthetic corpora approximate a larger team's structure; real graphs will differ.

---

## 13. Where the build differs from the ADRs

- The ADRs are short records of each decision; this document is the detailed description and wins
  where they differ.
- ADR-002 describes L0 pull requests merging automatically. As built, that is opt-in:
  `enforcement.auto_merge_levels` is empty until an owner adds `L0` after proving the gate.
- ADR-003's recall is a verb; the primary read path is ADR-004's protocol (`mem load`).
- ADR-003 and ADR-004 are `status: proposed` in the template: accept or revise them for your team.

---

## 14. Audit checklist

Things worth trying to break, each with the expected result:

1. As an agent (`CLAUDE_CODE_SESSION_ID=x`, no `MEMORY_ACTOR_KIND`), edit `features/*.md` and run
   `sync-memory post`: exit 4, nothing committed.
2. Set `MEMORY_ACTOR_KIND=human` in the same shell: the commit passes. This is the documented
   honest-agent limit (section 9); only owner review on a protected `main` catches it.
3. Put `restricted` content in a normal folder: `SENSITIVITY` fails.
4. Put an API key in a journal note: exit 3.
5. Write a claim ending in another note's id: stamp appends an own id; a shared id fails `CLAIM-ID`.
6. Load with `--ref` of a date before a change, then latest in the same session: the ledger
   resets and says so.
7. Load as a person without `restricted_read`: restricted notes are counted as withheld, not shown.
8. Tamper with a public `graph.json` (any field in section 4.5): `build_atlas --verify` exits 1. It
   compares with a fresh build of the notes by default; `--shape-only` checks the file alone and
   cannot see a note relabelled `open` or an edited title, so it is never enough to publish.
16. As an agent, stage `scripts/évil.py`, `AGENTS.md`, `.vscode/tasks.json` or `log/journal/.envrc`:
    exit 4 each.
17. Stage a secret, then edit or delete the file on disk, and run `check --staged`: exit 3.
9. Open a trial for another person, load as yourself: your bundle is unaffected.
10. Check that `mem.py` has no network access other than `git fetch` in `moved --fetch`, and no
    write outside the notes root and `.memory/`.
11. Run the scaffold on a repo that already has `.claude/settings.json`: it writes a
    `.suggested` file and leaves the original untouched.
12. Read `governance/roles.json` for any path that is more permissive than section 3.2 says.
13. Re-run the regression suites in `tools/` after any change to the guard, sync or atlas; each
    negative test must still fail when its rule is removed.
14. On Windows: `py tools\test_sync.py` must show a `powershell` section with 11 passing scenarios
    (it did on 2026-09-25).
15. Build a PR that edits `scripts/memory_guard.py` to always exit 0 and run `tools/test_gate.py`'s
    commands against it: the gate must be red.

---

## 15. File inventory

| Path | Lines | Role |
|---|---|---|
| `scripts/memory_guard.py` | 2,787 | enforcer |
| `scripts/mem.py` | 3,379 | protocol engine and verbs |
| `scripts/build_atlas.py` | 1,565 | atlas data and redaction gate |
| `scripts/sync-memory.py/.sh/.ps1` | 536 / 334 / 380 | sync dispatcher and implementations |
| `scripts/new_project_memory.py` (+ `.sh`/`.ps1` wrappers) | 436 / 18 / 27 | project scaffold, one implementation for every platform |
| `playbooks/`, `decisions/ADR-005-playbooks.md` | - | the playbook folder note and the decision record |
| `scripts/init.py` | 219 | turns the template into an instance: owner row, placeholders, git identity, CODEOWNERS, stamps, removes template-only files |
| `LICENSE`, `LICENSE-NOTES`, `NOTICE`, `.github/README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `ISSUE_TEMPLATE/`, `pull_request_template.md`, `assets/` | - | the licences (Apache-2.0 for code, MIT-0 for notes, templates and agent configuration; `NOTICE` has the split) and the open-source project's front page, contribution files and social preview; `init.py` removes the `.github/` ones in an instance |
| `governance/roles.json` | 518 | all policy |
| `governance/ACCESS.md`, `SIGNIFICANCE.md` | 171 / 125 | policy in prose |
| `CLAUDE.md`, `.cursor/rules/memory.mdc`, `.kiro/steering/memory.md` | 203 / 83 / 80 | agent rules |
| `.agents/skills/team-memory/SKILL.md` (+2 copies) | 180 | agent procedure |
| `.claude/commands/*.md` | 7 files | slash commands |
| `.claude/settings.json`, `.kiro/hooks/*.json` | 83 / 3 files | hooks and permissions |
| `.github/workflows/*.yml`, `CODEOWNERS` | 5 workflows + generated CODEOWNERS | CI |
| `CORE.md`, `features/*.md` | 36 / 6 files | big picture and this system's feature spine |
| `decisions/ADR-001..004` | 28-127 | decision records |
| `templates/project-memory/**` | 26 files | project tier seed |
| `tools/test_*.py` (13 suites), `tools/testpolicy.py`, `tools/run_tests.sh`, `tools/gen_fixture.py` | 4,443 total | tests; `testpolicy.py` supplies the fictional owner (`alex`) the suites run as |
| `web/` | app source 3,058 (`web/app/src`), tests 917; `index.html` is built | the atlas page; `web/test/` UI suite |


## Relations
- relates_to [[Core]]
- relates_to [[ADR-001 Shared Memory System]]
- relates_to [[ADR-002 Memory Governance And Access Tiers]]
- relates_to [[ADR-003 Claims Recall And Trials]]
- relates_to [[ADR-004 Context Protocol]]
- relates_to [[Memory Guard]]
- relates_to [[Context Protocol]]
