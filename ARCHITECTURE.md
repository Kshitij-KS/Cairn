---
title: System Architecture
type: context
tags: [architecture, audit, canonical]
level: L2
confidentiality: internal
created: 2026-09-23
updated: 2026-09-27
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
local state. Phases 3-4 (claim-id integrity, retrieval quality, scaffolding)
are NOT done; their open items are listed in section 10.

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
`sha1(note_id + "\n" + normalised text)`, with a `#n` suffix on collision.

- **Assignment**: `memory_guard.py stamp` gives unmarked claims an id. `sync-memory post` runs it
  before every commit.
- **Carry-forward**: when a claim is edited, stamp compares the new unmarked line with the claims
  that disappeared from `HEAD`'s version of the note. It keeps the old id if similarity (the max of
  token Jaccard and `difflib` ratio) is at least **0.5**, or if exactly one id vanished and exactly
  one unmarked line appeared (a one-for-one swap). Measured: 4 of 5 realistic rewordings keep their
  id at the threshold; a full rewrite gets a new id **[verified, test_guard]**.
- **References**: a line that ends with another note's id (`includes ^be2885`) is treated as a
  reference and gets its own id appended. Writing references in parentheses avoids the ambiguity
  (`includes (^be2885)`). An id used by claims in two notes fails the check.
- **Retirement**: `mem retire ^id` moves the line to `## Retired` with `(retired DATE: why)`; it is
  kept for history and excluded from recall.

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
`web/`, `CLAUDE.md`, `CODEOWNERS` and deployment config at L3 (`web/data/**` stays bot-only). A policy
that is empty, partial, has a catch-all rule, or gives agents more than L0 is refused (exit 6).

**Paths are normalised before matching** (01-F4): separators, `.`/`..` segments, Unicode NFKC and
case are folded, so `Context/x`, `context\x` and a long-s `\u017fcripts/` are all classified as the
protected folder. **A rename counts as a deletion of its source** (01-F3), so moving canon into
`log/journal/` needs the source's level.

**Attribution** (01-F5/F6, 10-F3): a new note's `author` is set from git by `stamp` and checked
against the introducing identity; in range mode every changed note is checked against the author
of the last commit touching it, and a commit by an unregistered email fails. A blank git email is a
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
  cache/<hash32>-<depth>.md          rendered note blocks, each with an envelope: note hash, depth, sha256
  bundles/<sha256-of-bytes>.md       the file an agent reads for one load; content-addressed, immutable
  session/current                    fallback session id
  session/<prefix>-<hash16>.json     ledger (version 2): ref, turn, {note: depth, hash, contract, turn, evicted}
  session/<key>.receipt.json         the last receipt of that session
  session/<key>.moved                that session's `mem moved` throttle stamp
  session/<key>.lock                 per-session lock for read-modify-write
  pack/claims.jsonl, features.json   compiled by `mem compile`
  logs/recall-YYYY-MM.jsonl          ids shown + reasons, query salted-hashed
  prefs.json                         personal pins and mutes
  salt                               per-machine random salt
```

**Concurrency and integrity (audit area 04).** Every write goes to a unique temporary file, is
fsynced and atomically renamed. A session's ledger is read-modified-written under a per-session
lock, and it is written **last**, so a load that fails to save marks nothing as delivered. Bundles
are named by the hash of their bytes, so no session or repeat load can overwrite another's. A cache
block is served only if its envelope names the exact note version and depth and its digest
matches; anything else is regenerated. A ledger of the wrong shape is quarantined (renamed
`.corrupt-<time>`) with one warning and rebuilt. Cached copies and bundles untouched for 14 days are
deleted at each `session start`; `mem session purge` deletes them all.
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
unpushed memory commits to the person's own branch `memory/<who>` (from `user.email`) and keeps one
pull request open for it with `gh`, or prints the compare link. In direct mode a push the server
refuses because the branch is protected is exit 7 from the native script, and the dispatcher takes
the same path. `main` is never force-pushed; `memory/<who>` is rewritten only with
`--force-with-lease`, and only after checking that every file the remote branch changed is already
in `HEAD` with the same content (so a squash-merged pull request is fine and a teammate's unique
commit is refused, exit 1). Once the pull request merges, the next `pre` drops the local copies
(git rebase skips changes already upstream). On a feature branch nothing changes: a project tier's
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

`scripts/build_atlas.py` builds `web/data/graph.json` (schema 3); `web/` renders it (vanilla JS +
d3, layout precomputed in Python, no layout in the browser).

- **Public build** (default): restricted notes omitted, and so is **every trace of them**: links to
  them are dropped rather than reported as broken, their paths are removed from activity, and the
  build refuses to write a file in which any restricted id, path or title appears anywhere (07-F1).
  A note under `context/restricted/` is restricted whatever its label says (07-F7). Bodies withheld
  unless `confidentiality: open`; summaries, feature cards and proposal summaries withheld above
  `publication.brief_levels` (L0); contracts, commit messages, trial and eval content, trial
  hypotheses and audience names, gap text, feature `covers` and local session ledgers withheld.
  Author, editor, agent and owner fields are withheld when `publication.publish_authors` is false
  (07-F4). A note whose title is itself sensitive sets `public_title:` or `publish_title: false`
  (07-F6); titles otherwise publish, by design, because they are the map.
- **Full build** (`--full`, local only): everything, plus the last 10 session ledgers.
- **Verification** (07-F2/F3): `build_atlas.py --verify FILE` checks a **closed schema** (every key
  and type allowed at every level; unknown fields, duplicate JSON keys, duplicate ids and references
  to non-public notes all fail), then every publication rule. `--against-source` also rebuilds the
  public graph from the notes and requires the file to match it exactly (apart from
  `generated_at`). `tools/test_atlas.py` proves 25 tampering cases fail.
- **Rendered page** (07-F5): `web/test` uses the full build of the same corpus as an oracle; every
  withheld string becomes a marker and none may appear in the page's text or markup; a negative
  test renders one on purpose and must be caught. Dependencies are pinned by `package-lock.json`.
- **Publication is manual** during containment (`atlas.yml` is `workflow_dispatch` only), and runs
  the redaction tests and the page tests before generating.

### 4.6 Project scaffolding

`scripts/new-project-memory.sh|.ps1 <repo> [name]` creates `memory/` (notes from
`templates/project-memory/memory/`, `CORE.md`, empty `features/ trials/ evals/`, `.gitignore`),
copies `sync-memory.*`, **`memory_guard.py`, `mem.py`** and `governance/roles.json` into
`memory/`, installs the agent configs (Claude settings and slash commands pointed at
`memory/scripts/mem.py`, Kiro hooks and steering, Cursor rule, MCP configs) and registers the Basic
Memory project. On GitHub it adds `.github/workflows/memory-gate.yml` (scoped to `memory/**`; the
base revision's `memory/scripts/memory_guard.py` judges the PR with the base policy and labels its
level) and a marked block of `/memory/...` lines in `.github/CODEOWNERS`, which
`memory_guard.py --notes-root memory codeowners --write` maintains without touching the product's
own lines. It never overwrites; an existing file gets a `.team-memory.suggested` twin, and a file
already holding exactly what it would write is left alone, so a second run changes nothing.
Before 2026-09-23 the guard was not copied, so project tiers committed with the policy unenforced
**[fixed]**; before 2026-09-27 a project tier had no gate on GitHub at all (08-F2) **[fixed;
tools/test_scaffold.py]**.

### 4.7 Agent integration

| | Claude Code | Kiro IDE | Cursor | Claude Desktop |
|---|---|---|---|---|
| Rules | `CLAUDE.md` | `.kiro/steering/memory.md` | `.cursor/rules/memory.mdc` | project instructions |
| Procedure | skill `.claude/skills/team-memory` | skill `.kiro/skills/team-memory` | `.agents/skills` (native) | - |
| Pull + ledger at start | `SessionStart` startup/resume/clear: `sync pre --agent`, `mem --hook session start` | `SessionStart`: same (IDE only) | by hand | by hand |
| After compaction | `SessionStart` matcher `compact`: `mem --hook session evict` | none | none | none |
| Context moved | `UserPromptSubmit`: `mem --hook moved --quiet --fetch --throttle 300` | `UserPromptSubmit` hook **[unverified trigger]** | by hand | - |
| Commit at end | `Stop`: significance prompt, `sync post --agent` | `Stop`: same | by hand | by hand |
| Commands | `/cairn /cairn-context /cairn-recall /cairn-remember /cairn-gaps /cairn-try /cairn-feature` (`.claude/commands/`) | - | `.cursor/commands/` **[unverified format]** | - |
| Permissions | allow `mem.py`, guard, sync, read-only Basic Memory tools; deny `delete_note`, `delete_project`, force-push, `--no-verify` | autoApprove read tools | - | - |

Claude Code behaviour above was checked against the current docs on 2026-09-23 (hook events and
matchers including `compact`, plain stdout added to context for SessionStart and
UserPromptSubmit, `.claude/commands/` still supported, `CLAUDE_CODE_SESSION_ID` from CLI 2.1.132)
through a documentation lookup, not by running Claude Code.

### 4.8 CI workflows (not yet exercised on GitHub)

`memory-gate`, `cascade`, `changelog` and `atlas` start with an `instance` job that reads
`governance/roles.json` (from the base revision, for the gate) and skip their real job unless
`"instance": true`. The unconfigured template has no owner and no CODEOWNERS, so these gates could
only fail there; `scripts/init.py` sets the flag. `tests` always runs.

| Workflow | Trigger | Does |
|---|---|---|
| `memory-gate.yml` | pull request | checks out the **trusted base revision** and the PR separately; the base's guard judges the PR's data with the base's policy (safety, format, per-commit attribution; `--no-access` because review enforces the level); runs the base's `test_security.py` **against the PR's guard**, so a PR that weakens the guard goes red; checks CODEOWNERS is generated and names real people; `classify` decides the review level. A second job, which runs no PR code, labels the PR (fails if labelling fails) and, when the level is in the BASE policy's `enforcement.auto_merge_levels`, enables GitHub auto-merge (squash). Empty by default, so nothing auto-merges until an owner opts in. |
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
non-empty, `codeowners` stops writing the owner catch-all: each path rule above those levels names
the people whose role reaches it, auto-merge levels name nobody, the protected floor names the
owners, and the lines are written in reverse because GitHub applies the last matching line while
roles.json applies the first **[verified: test_security, including a policy that demotes
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
| `tools/test_security.py` | 29 | the audit's access/attribution BLOCKERs as regressions: policy self-demotion, empty policy, the floor, renames, case and Unicode tricks (range mode too), forged and blank authors, derived bytes, public paths, CODEOWNERS (catch-all and level-aware), open-under-restricted; the actor override inside an agent runtime; injection phrasings, with a benign negative. Never imports the guard under test (a guard that exits 0 at import once ended a run green) |
| `tools/test_gate.py` | 6 | the memory-gate job in its two-checkout shape: the 10-F1 attack PR, a quiet policy demotion, a demoting rename, an honest L0 note |
| `tools/test_mem.py` | 106 | resolution and modes (including CI and AI-quality symptoms, asking instead of guessing, `mem asks`, team `extra_symptoms`), directional scope, ledger, cache, privilege, hooks, moved and refs, **area-04 concurrency and damage** (parallel loads, bundle isolation, UTF-8 past refs, cache tamper, session-id collisions and injection, per-session throttle, failed-save retry, corrupt ledgers, purge), write verbs, trials, evals |
| `tools/test_parsers.py` | 6 | fenced/inline code ignored by claim and relation parsers |
| `tools/test_atlas.py` | 47 | content, restricted traces, open-under-restricted, publish_authors, 25 tampering cases, duplicate keys, `--against-source`, bare `--out` |
| `tools/test_init.py` | 16 | `init.py` on a fresh copy: owner row, instance flag, CODEOWNERS, filled placeholders, stamps, git identity, template-only files removed, a clean guard check and first commit; refuses a second run, a bad email, a bad login, `--yes` without `--github` |
| `tools/test_sync.py` | 25 per platform (bash on Linux/macOS, PowerShell on Windows); 38 with `--impl all` | 11 area-06 scenarios plus a protected main (exit 7, commit-only) per implementation against bare remotes; dispatcher mode/lock/usage; pull-request mode end to end (fallback, one branch per person, squash-merge then pre, refusal to overwrite, gh with a fake CLI); ASCII-only PowerShell |
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
| Path tricks (case, Unicode, renames) | normalisation and rename-source classification | local + CI | symlinks on Windows untested (needs Developer Mode) |
| Note content hijacks an agent | "notes are data" rule; `INJECTION` patterns (overrides, pipe-to-shell, guard variables, `--no-verify`, bypassing a control, text addressed to agents, concealment from the user) | commit | patterns are a list: 0 false positives over 97 real notes, but new phrasings will pass; the instruction is the main control |
| A code PR rewrites a project tier | the project repo's `memory-gate` (base guard, base policy) and its CODEOWNERS memory block | CI + review, once protected | only if the scaffold's workflow and CODEOWNERS block were committed |
| Hooks as a remote-code path | hook, script and config roots at L3 under the floor | CI + review | - |
| Secrets committed | guard `SECRET-*`; sync secret scan on the exact committed tree | local + CI | regex-based; novel formats pass; gitleaks removed from CI |
| Out-of-tier files ride along a sync | temporary index; tier-only push | local | the Windows CI job has not yet run on GitHub |
| Restricted leakage | private submodule (a GitHub permission); `restricted_read` filter; atlas omits every trace | GitHub access is real; the filter is advisory on a laptop that has the files | anyone with submodule access reads the files |
| Public atlas leakage | closed schema; source comparison; restricted-token sweep; page oracle; manual publication | CI | titles publish by design unless `public_title`/`publish_title: false` |
| Misattribution | stamp from git; new-note author check; per-commit check in CI; blank email blocks | local + CI | a person can commit under a teammate's email locally; GitHub shows the pusher, review catches it |
| Local tampering with cache or ledger | cache envelopes; ledger validation and quarantine | local | anyone who can write the checkout can write the notes too |

---

---

## 10. Known limitations

- Mode detection is lexical. A bug report that names neither an intent nor a listed symptom
  ("drops captions") gets no confident mode, so `mem load` asks the person instead of loading
  (exit 2, `ask_the_person`, below); with `protocol.ask_on_guess: false` it loads build and the
  receipt says `A GUESS`. Measured on a real 13-feature project tier with asks written before running (2026-09-27): the
  tuned 15 at 14/15; a first held-out 10 at 6/10 before the change (2 silent wrong modes, 2 not
  confident); a second held-out 8, written after the change, at 7/8 with the feature right 8 of 8
  (the miss is the flagged guess above). A verb that is also a feature name ("the **export** is
  wrong" when Export is a feature) pulls that feature.
- Resolution picks one target when the runner-up scores below 85% of the top, even when the ask
  genuinely spans two features.
- Carry-forward keeps ids for about 4 in 5 of the builder's rewordings, but the audit measured 8 of
  20 on its own set, and found the one-for-one rule gives an unrelated replacement the deleted
  claim's id and that reordering can swap ids (02-F1..F3). Not fixed (Phase 3).
- Retrieval: a held-out set of 20 asks written by the auditor scored 6/20; at 200 features the feature
  map alone costs ~7,700 tokens (03-F8/F9). Not fixed (Phase 3).
- Trials: the eval comparison can fail open when the overlay changes the eval set, and an agent's
  `keep` of an L1 change is denied instead of becoming a proposal (05-F1/F2). Not fixed (Phase 3).
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
| claim-id carry-forward | 4/5 rewordings keep their id | test_guard fixture |

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
- `new-project-memory.ps1` and a generated project tier's hooks on Windows (`sync-memory.ps1` itself
  was verified on Windows on 2026-09-25).
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
8. Tamper with a public `graph.json` (any field in section 4.5): `build_atlas --verify` exits 1.
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
| `scripts/memory_guard.py` | 1,897 | enforcer |
| `scripts/mem.py` | 2,227 | protocol engine and verbs |
| `scripts/build_atlas.py` | 1,388 | atlas data and redaction gate |
| `scripts/sync-memory.py/.sh/.ps1` | 159 / 307 / 350 | sync dispatcher and implementations |
| `scripts/new-project-memory.sh/.ps1` | 101 / 112 | project scaffold |
| `scripts/init.py` | 219 | turns the template into an instance: owner row, placeholders, git identity, CODEOWNERS, stamps, removes template-only files |
| `LICENSE`, `LICENSE-NOTES`, `NOTICE`, `.github/README.md`, `.github/CONTRIBUTING.md`, `.github/SECURITY.md` | - | the licences (Apache-2.0 for code, MIT-0 for notes, templates and agent configuration; `NOTICE` has the split) and the open-source front page; `init.py` removes the three `.github/` files in an instance |
| `governance/roles.json` | 478 | all policy |
| `governance/ACCESS.md`, `SIGNIFICANCE.md` | 171 / 125 | policy in prose |
| `CLAUDE.md`, `.cursor/rules/memory.mdc`, `.kiro/steering/memory.md` | 203 / 83 / 80 | agent rules |
| `.agents/skills/team-memory/SKILL.md` (+2 copies) | 180 | agent procedure |
| `.claude/commands/*.md` | 7 files | slash commands |
| `.claude/settings.json`, `.kiro/hooks/*.json` | 83 / 3 files | hooks and permissions |
| `.github/workflows/*.yml`, `CODEOWNERS` | 5 workflows + generated CODEOWNERS | CI |
| `CORE.md`, `features/*.md` | 36 / 6 files | big picture and this system's feature spine |
| `decisions/ADR-001..004` | 28-127 | decision records |
| `templates/project-memory/**` | 26 files | project tier seed |
| `tools/test_*.py`, `tools/testpolicy.py`, `tools/run_tests.sh`, `tools/gen_fixture.py` | 2,312 total | tests; `testpolicy.py` supplies the fictional owner (`alex`) the suites run as |
| `web/` | app 1,767, style 654, index 211 | the atlas page; `web/test/` UI suite |


## Relations
- relates_to [[Core]]
- relates_to [[ADR-001 Shared Memory System]]
- relates_to [[ADR-002 Memory Governance And Access Tiers]]
- relates_to [[ADR-003 Claims Recall And Trials]]
- relates_to [[ADR-004 Context Protocol]]
- relates_to [[Memory Guard]]
- relates_to [[Context Protocol]]
