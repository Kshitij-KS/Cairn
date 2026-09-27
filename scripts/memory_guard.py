# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
memory_guard.py — the one enforcement engine for the shared memory.

The same code runs in two places, which is the point: what blocks your commit locally is
byte-identical to what blocks the merge in CI, so a guard cannot pass on your laptop and fail
in the pipeline (or, far worse, the reverse).

    memory_guard.py stamp   [--staged]            write attribution/level from git identity
    memory_guard.py check   [--staged | --range A..B]   enforce level, role, quality, safety
    memory_guard.py cascade [--range A..B] [--apply]    stamp review_needed on dependents
    memory_guard.py significance                  Stop-hook detector (reads hook JSON on stdin)
    memory_guard.py explain [--actor <handle>]    print what an actor may change
    memory_guard.py audit   [--since 30d] [--path P]    who changed what, when

Policy lives in governance/roles.json — never in this file. Read that to change the rules;
read this only to change how they are enforced.

Exit codes:  0 ok · 3 secret/never-store · 4 access denied (level/role) · 5 validation failure
             (6 = internal error). `--warn-only` downgrades 4 and 5 to warnings.

Standard library only, so it runs on a fresh machine with no network and no install step.
"""

import argparse
import difflib
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone

LEVEL_ORDER = ["L0", "L1", "L2", "L3"]
EXIT_OK, EXIT_SECRET, EXIT_DENIED, EXIT_INVALID, EXIT_INTERNAL = 0, 3, 4, 5, 6

NOTE_DIRS = ("context", "decisions", "projects", "log", "governance", "templates",
             "features", "trials", "evals", "playbooks")

# --------------------------------------------------------------------------- shell helpers


def git(*args, cwd=None, check=False):
    """Run git and return stdout as text. Never raises unless check=True."""
    # UTF-8 explicitly: on Windows the default locale codec is cp1252, and `git show` of a real
    # (non-ASCII) note crashed historical-ref loads (audit 04-F3).
    p = subprocess.run(
        ["git", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    if check and p.returncode != 0:
        die("git " + " ".join(args) + " failed: " + p.stderr.strip(), EXIT_INTERNAL)
    return p.stdout


def die(msg, code=EXIT_INTERNAL):
    sys.stderr.write("memory-guard: ERROR %s\n" % msg)
    sys.exit(code)


# --------------------------------------------------------------------------- globs


def glob_to_re(pattern):
    """Translate a git-style glob to a regex. fnmatch does not understand `**`."""
    out, i, n = [], 0, len(pattern)
    while i < n:
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(pattern, path):
    return glob_to_re(pattern).match(path) is not None


# --------------------------------------------------------------------------- context


# Paths whose level no policy can lower. A change to roles.json is judged by the TRUSTED policy (the
# base revision), and on top of that these floors hold even if the trusted policy itself were wrong:
# a policy that could demote the rules, the scripts that enforce them, or the hooks that run on every
# teammate's machine would let one commit authorise itself (audit 01-F1, 10-F1, 10-F10).
PROTECTED_FLOOR = [
    ("governance/**", "L3"), ("scripts/**", "L3"), ("tools/**", "L3"), (".github/**", "L3"),
    ("CODEOWNERS", "L3"), (".claude/**", "L3"), (".kiro/**", "L3"), (".cursor/**", "L3"),
    (".agents/**", "L3"), ("CLAUDE.md", "L3"), ("web/**", "L3"), (".gitignore", "L3"),
    (".mcp.json", "L3"), (".basic-memory/**", "L3"), ("vercel.json", "L3"), ("netlify.toml", "L3"),
    ("package.json", "L3"), ("*.config.js", "L3"), ("*.config.mjs", "L3"),
]
# Stricter policy outcomes a floor never overrides: a derived copy must equal its source byte for
# byte, and a bot-only path is closed to every person.
FLOOR_KEEPS = ("derived", "bot")


def norm_path(path):
    """Canonical, case-folded repo-relative path used for EVERY policy comparison.

    `Context/x`, `CONTEXT/x`, `./context/x`, `context\\x` and `\u017fcripts/x` (long s) all name, or
    look like, a protected folder; classifying the raw spelling put each of them at the permissive
    default L0 (audit 01-F4). NFKC folds compatibility characters, casefold folds case, and the
    segments are resolved so `a/../context/x` is `context/x`.
    """
    p = unicodedata.normalize("NFKC", (path or "").replace("\\", "/")).casefold()
    out = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
            continue
        out.append(seg)
    return "/".join(out)


class PolicyError(Exception):
    pass


def validate_policy(pol):
    """Fail closed. An empty or partial policy used to mean 'everything is L0' (audit 01-F2)."""
    if not isinstance(pol, dict):
        raise PolicyError("policy is not a JSON object")
    paths = pol.get("paths")
    if not isinstance(paths, dict) or not isinstance(paths.get("rules"), list) or not paths["rules"]:
        raise PolicyError("paths.rules must be a non-empty list")
    for r in paths["rules"]:
        if not isinstance(r, dict) or not isinstance(r.get("glob"), str) or not r["glob"].strip():
            raise PolicyError("every path rule needs a glob: %r" % (r,))
        if r.get("level") not in LEVEL_ORDER + ["derived", "bot"]:
            raise PolicyError("rule %r has an unknown level %r" % (r.get("glob"), r.get("level")))
        if r.get("glob").strip() in ("**", "*", "**/*"):
            raise PolicyError("a catch-all rule (%r) would override every protected path" % r["glob"])
    if paths.get("default", "L0") not in LEVEL_ORDER:
        raise PolicyError("paths.default must be one of %s" % LEVEL_ORDER)
    roles = pol.get("roles")
    if not isinstance(roles, dict) or not isinstance(roles.get("order"), list) or not roles["order"]:
        raise PolicyError("roles.order must be a non-empty list")
    for name in roles["order"]:
        if not isinstance(roles.get(name), dict):
            raise PolicyError("role %r is listed in roles.order but not defined" % name)
        ml = roles[name].get("max_level")
        if ml is not None and ml not in LEVEL_ORDER:
            raise PolicyError("role %r has an unknown max_level %r" % (name, ml))
    if (roles.get("agent") or {}).get("max_level") != "L0":
        raise PolicyError("roles.agent.max_level must be L0: agents write observations only")
    if not isinstance(pol.get("people"), dict):
        raise PolicyError("people must be an object")
    sens = pol.get("sensitivity")
    if not isinstance(sens, dict) or not isinstance(sens.get("tiers"), dict) or sens.get("default") not in (sens.get("tiers") or {}):
        raise PolicyError("sensitivity needs tiers and a default that is one of them")
    return pol


def usable_email(email):
    """A blank or placeholder address never identifies anyone (audit 01-F6)."""
    e = (email or "").strip().lower()
    return bool(e) and "@" in e and "__todo" not in e


def floor_level(npath):
    best = None
    for g, lvl in PROTECTED_FLOOR:
        if glob_match(g.casefold(), npath) and (best is None or LEVEL_ORDER.index(lvl) > LEVEL_ORDER.index(best)):
            best = lvl
    return best


AGENT_MARKERS = ("CLAUDE_CODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "KIRO_AGENT",
                 "CURSOR_AGENT", "MEMORY_AGENT")


def _interactive():
    """A person at a terminal: both stdin and stderr are TTYs. Hooks and agent shell tools have neither."""
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except (AttributeError, ValueError, OSError):
        return False


class Ctx:
    """Everything the checks need: where we are, who we are, and what the policy says."""

    def __init__(self, notes_root=None):
        start = os.path.abspath(notes_root or os.getcwd())
        self.notes_root = self._find_notes_root(start)
        top = git("-C", self.notes_root, "rev-parse", "--show-toplevel").strip()
        if not top:
            die("%s is not inside a git repository" % self.notes_root)
        self.repo_root = os.path.abspath(top)
        rel = os.path.relpath(self.notes_root, self.repo_root).replace(os.sep, "/")
        self.prefix = "" if rel == "." else rel + "/"

        self.manifest = self._load_json(
            os.path.join(self.notes_root, ".basic-memory", "project.json"), {}
        )
        self.project_name = self.manifest.get("name", os.path.basename(self.repo_root))
        self.worktree_policy = self._load_policy()
        # The policy that JUDGES a change is the one at the trusted base revision, never the copy the
        # change itself may have edited (audit 01-F1). Default base: HEAD. CI passes the merge base
        # via MEMORY_POLICY_REF (or `check --policy-ref`). A repository with no commit yet has no base,
        # so the working copy is used - validated, and still under PROTECTED_FLOOR.
        self.policy_ref = None
        self.policy = self.load_trusted_policy(os.environ.get("MEMORY_POLICY_REF") or "HEAD")

        # An agent that runs `git commit` or `mem approve` from its own shell tool never goes through
        # sync-memory.py --agent, so MEMORY_ACTOR_KIND would be unset and it would be treated as the
        # human whose git identity it borrows. Default to "agent" whenever the process carries an agent
        # runtime's marker. CLAUDE_CODE_SESSION_ID is documented (Claude Code env-vars, CLI >= 2.1.132);
        # the others are best-effort and UNVERIFIED. This is a guard-rail for honest agents, not a
        # security boundary: a process can always set MEMORY_ACTOR_KIND=human. The boundary is review
        # plus branch protection on the remote (ARCHITECTURE.md, threat model).
        markers = [k for k in AGENT_MARKERS if os.environ.get(k)]
        default_kind = "agent" if markers else "human"
        self.actor_kind = (os.environ.get("MEMORY_ACTOR_KIND") or default_kind).strip().lower()
        if self.actor_kind not in ("human", "agent", "bot"):
            self.actor_kind = "human"
        # An agent claiming to be a person (or the CI bot) with one environment variable was the
        # cheapest escalation there was. Inside an agent runtime, with no terminal attached, the
        # claim is ignored: a person typing at a terminal still commits as themselves. Raises the
        # bar only - a process can also drop the markers - so review stays the boundary.
        if self.actor_kind in ("human", "bot") and markers and not _interactive():
            sys.stderr.write("memory-guard: MEMORY_ACTOR_KIND=%s ignored: an AI agent runtime is present (%s) and no "
                             "terminal is attached, so this runs as agent. Commit from your own terminal to act "
                             "as yourself.\n" % (self.actor_kind, ", ".join(markers)))
            self.actor_kind = "agent"
        self.agent_name = (
            os.environ.get("MEMORY_AGENT")
            or ("claude-code" if os.environ.get("CLAUDE_CODE_ENTRYPOINT") else "")
            or ("kiro" if os.environ.get("KIRO_AGENT") else "")
            or "unknown"
        )
        self.email = (
            os.environ.get("MEMORY_ACTOR_EMAIL")
            or git("-C", self.repo_root, "config", "user.email").strip()
        )
        self.handle, self.person = self._resolve_person(self.email)

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def _find_notes_root(start):
        # Run from a code repo's root, the project tier is the CHILD memory/ - hooks and agents run
        # from the repo root, so look there before walking up.
        if (not os.path.isfile(os.path.join(start, ".basic-memory", "project.json"))
                and os.path.isfile(os.path.join(start, "memory", ".basic-memory", "project.json"))):
            return os.path.join(start, "memory")
        d = start
        while True:
            if os.path.isfile(os.path.join(d, ".basic-memory", "project.json")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                return start  # no manifest: treat cwd as the notes root
            d = parent

    @staticmethod
    def _load_json(path, default=None):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            if default is None:
                die("policy file not found: %s" % path)
            return default
        except json.JSONDecodeError as e:
            die("%s is not valid JSON: %s" % (path, e))

    def _load_policy(self):
        for cand in (
            os.path.join(self.notes_root, "governance", "roles.json"),
            os.path.join(self.repo_root, "governance", "roles.json"),
            os.path.join(self.repo_root, "memory", "governance", "roles.json"),
        ):
            if os.path.isfile(cand):
                self.policy_path = cand
                pol = self._load_json(cand)
                try:
                    return validate_policy(pol)
                except PolicyError as e:
                    die("%s is not a usable policy: %s. Refusing to check anything with it." % (cand, e))
        die(
            "governance/roles.json not found (looked beside the notes root and at the repo root).\n"
            "  Every write is policed by that file; without it the guard cannot know who may change what."
        )

    def load_trusted_policy(self, ref):
        """roles.json as of `ref`. Falls back to the (validated) working copy only when `ref` has no
        policy at all - a first commit. Returns the validated policy."""
        rel = os.path.relpath(self.policy_path, self.repo_root).replace(os.sep, "/")
        if (ref or "").upper() == "WORKTREE":
            # scripts/init.py only: the owner is being written into the working copy right now.
            self.policy_ref = None
            return self.worktree_policy
        text = git("-C", self.repo_root, "show", "%s:%s" % (ref, rel)) if ref else ""
        if not text.strip():
            self.policy_ref = None
            return self.worktree_policy
        try:
            pol = validate_policy(json.loads(text))
        except (ValueError, PolicyError) as e:
            die("the trusted policy at %s:%s is not usable: %s" % (ref, rel, e))
        self.policy_ref = ref
        return pol

    def use_policy_ref(self, ref):
        self.policy = self.load_trusted_policy(ref)
        self.handle, self.person = self._resolve_person(self.email)

    def policy_changed(self):
        return self.policy_ref is not None and self.worktree_policy != self.policy

    def _resolve_person(self, email):
        if not usable_email(email):
            return None, None
        people = self.policy.get("people", {})
        for handle, p in people.items():
            if handle.startswith("$") or not isinstance(p, dict):
                continue
            if not usable_email(p.get("email")):
                continue
            if p.get("email", "").strip().lower() == (email or "").strip().lower():
                return handle, p
        return None, None

    # -- policy lookups ----------------------------------------------------
    def _tier_rel(self, repo_rel_path):
        """Normalised path relative to the notes root, or None when it is outside this tier."""
        n = norm_path(repo_rel_path)
        pre = norm_path(self.prefix)
        if pre:
            if n == pre or not n.startswith(pre + "/"):
                return None
            return n[len(pre) + 1:]
        return n

    @staticmethod
    def _policy_level(policy, p):
        for rule in policy.get("paths", {}).get("rules", []):
            if glob_match(rule["glob"].casefold(), p):
                return rule["level"], rule
        return policy.get("paths", {}).get("default", "L0"), None

    def path_level(self, repo_rel_path, policy=None):
        """Level required to write this path: the trusted policy's answer, raised to the protected
        floor. Matching is on the normalised, case-folded path (audit 01-F4)."""
        p = self._tier_rel(repo_rel_path)
        if p is None:
            return None  # outside this tier's notes root: not our business
        lvl, _rule = self._policy_level(policy or self.policy, p)
        if lvl in FLOOR_KEEPS:
            return lvl
        fl = floor_level(p)
        if fl and level_rank(fl) > level_rank(lvl):
            return fl
        return lvl

    def required_level(self, repo_rel_path):
        """While roles.json itself is being changed, a path needs whatever BOTH the trusted and the
        proposed policy require, so a policy edit can neither demote nor quietly promote around the
        check (audit 01-F1)."""
        a = self.path_level(repo_rel_path)
        if not self.policy_changed() or a is None:
            return a
        b = self.path_level(repo_rel_path, self.worktree_policy)
        if a in FLOOR_KEEPS:
            return a
        if b in FLOOR_KEEPS:
            return b
        return a if level_rank(a) >= level_rank(b) else b

    def path_rule(self, repo_rel_path):
        p = self._tier_rel(repo_rel_path)
        return None if p is None else self._policy_level(self.policy, p)[1]

    def path_reason(self, repo_rel_path):
        rule = self.path_rule(repo_rel_path) or {}
        return rule.get("reason", "")

    def effective_max_level(self):
        """The highest level this actor may write *right now*.

        An agent is capped at L0 no matter who launched it. That is the whole point: the
        driver's authority applies when the human commits, not when their agent does.
        """
        if self.actor_kind == "bot":
            return "L3"
        role = (self.person or {}).get("role", "contributor" if self.actor_kind == "human" else "agent")
        roles = self.policy.get("roles", {})
        role_max = (roles.get(role) or {}).get("max_level")
        if self.actor_kind == "agent":
            agent_max = (roles.get("agent") or {}).get("max_level", "L0")
            return min_level(role_max, agent_max)
        return role_max

    def role_name(self):
        if self.actor_kind == "bot":
            return "bot"
        base = (self.person or {}).get("role", "unregistered")
        return "agent (driven by %s)" % base if self.actor_kind == "agent" else base

    def maintains(self, project):
        allowed = (self.person or {}).get("projects", [])
        return "*" in allowed or project in allowed


def level_rank(level):
    return LEVEL_ORDER.index(level) if level in LEVEL_ORDER else -1


def min_level(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if level_rank(a) <= level_rank(b) else b


def level_allows(actor_max, required):
    if required == "bot":
        return False
    if actor_max is None:
        return False
    return level_rank(required) <= level_rank(actor_max)


# --------------------------------------------------------------------------- frontmatter


def split_frontmatter(text):
    """Return (list_of_frontmatter_lines, body). Frontmatter lines exclude the --- fences."""
    if not text.startswith("---"):
        return None, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    return None, text


def fm_get(fm_lines, key):
    """Read a frontmatter value, inline or block.

    Basic Memory normalises `tags: [a, b]` into a YAML block sequence when it reindexes, so a
    parser that only understands the inline form reports every note it has touched as missing
    its tags. Both forms have to work.
    """
    if fm_lines is None:
        return None
    pat = re.compile(r"^%s\s*:\s*(.*)$" % re.escape(key))
    for i, ln in enumerate(fm_lines):
        m = pat.match(ln)
        if not m:
            continue
        val = m.group(1).strip().strip("'\"")
        if val:
            return val
        items = []
        for nxt in fm_lines[i + 1:]:
            if re.match(r"^\s*-\s+", nxt):
                items.append(nxt.strip()[1:].strip().strip("'\""))
            elif nxt.strip() == "":
                continue
            else:
                break
        return ", ".join(items) if items else ""
    return None


def fm_set(fm_lines, key, value):
    """Set a key in place, preserving every other line and its order."""
    out, done = [], False
    pat = re.compile(r"^%s\s*:" % re.escape(key))
    for ln in fm_lines:
        if pat.match(ln) and not done:
            out.append("%s: %s" % (key, value))
            done = True
        else:
            out.append(ln)
    if not done:
        out.append("%s: %s" % (key, value))
    return out


def render(fm_lines, body):
    return "---\n" + "\n".join(fm_lines) + "\n---\n" + body.lstrip("\n")


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# --------------------------------------------------------------------------- change sets


def changed_files(ctx, staged=False, rng=None):
    """(status, path) pairs, paths relative to the repo root."""
    if rng:
        out = git("-C", ctx.repo_root, "diff", "--name-status", "-M", rng)
    elif staged:
        out = git("-C", ctx.repo_root, "diff", "--cached", "--name-status", "-M")
    else:
        out = git("-C", ctx.repo_root, "diff", "--name-status", "-M", "HEAD")
    files, seen = [], set()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0][0], parts[-1]
        if path not in seen:
            seen.add(path)
            files.append((status, path))
        # A rename is a deletion of its source as well as a write of its destination. Classifying
        # only the destination let `git mv context/x log/journal/x` remove L2 canon as L0
        # (audit 01-F3, 01-F4 case-only renames, 10-F4).
        if status == "R" and len(parts) >= 3 and parts[1] not in seen:
            seen.add(parts[1])
            files.append(("D", parts[1]))
    if not rng and not staged:
        # A brand-new note is untracked, and `git diff` never shows it. Missing them would
        # mean the guard silently ignored exactly the files it exists to police.
        for path in git("-C", ctx.repo_root, "ls-files", "--others",
                        "--exclude-standard").splitlines():
            path = path.strip()
            if path and path not in seen:
                seen.add(path)
                files.append(("A", path))
    return files


def is_note(ctx, repo_rel):
    """A note is any Markdown in a note folder — or at the notes root.

    README.md, CLAUDE.md and RUNBOOK.md are notes: other notes link to them, so leaving them out
    meant they were never stamped, never validated, and showed up as broken relations in the
    graph. Anything under a dot-folder is config, not knowledge.
    """
    if not repo_rel.endswith(".md"):
        return False
    rel = repo_rel[len(ctx.prefix):] if ctx.prefix and repo_rel.startswith(ctx.prefix) else repo_rel
    if rel.startswith("."):
        return False
    head = rel.split("/")
    return head[0] in NOTE_DIRS if len(head) > 1 else True


# --------------------------------------------------------------------------- findings


class Findings:
    def __init__(self):
        self.items = []  # (severity, code, path, message, hint)

    def add(self, severity, code, path, message, hint=""):
        self.items.append((severity, code, path, message, hint))

    def worst_exit(self, warn_only=False):
        if warn_only:
            return EXIT_OK
        codes = {c for s, c, _, _, _ in self.items if s == "FAIL"}
        if any(c.startswith("SECRET") for c in codes):
            return EXIT_SECRET
        if any(c.startswith("ACCESS") for c in codes):
            return EXIT_DENIED
        if codes:
            return EXIT_INVALID
        return EXIT_OK

    def report(self, warn_only=False):
        fails = [i for i in self.items if i[0] == "FAIL"]
        warns = [i for i in self.items if i[0] == "WARN"]
        for sev, code, path, msg, hint in fails + warns:
            label = "FAIL" if (sev == "FAIL" and not warn_only) else "WARN"
            sys.stderr.write("  [%s %s] %s\n        %s\n" % (label, code, path, msg))
            if hint:
                sys.stderr.write("        -> %s\n" % hint)
        if fails and not warn_only:
            sys.stderr.write(
                "\nmemory-guard: %d blocking finding(s), %d warning(s). Nothing was committed.\n"
                % (len(fails), len(warns))
            )
        elif fails or warns:
            sys.stderr.write(
                "memory-guard: %d finding(s) (advisory).\n" % (len(fails) + len(warns))
            )


# --------------------------------------------------------------------------- safety scanners

SECRET_FILE_RE = re.compile(
    r"(^|/)\.env($|\.)|\.(pem|key|p12|pfx|jks)$|(^|/)id_(rsa|dsa|ecdsa|ed25519)$|credentials\.json$",
    re.I,
)
SECRET_CONTENT = [
    (r"sk-[A-Za-z0-9_\-]{20,}", "OpenAI-style API key"),
    (r"sk-ant-[A-Za-z0-9_\-]{20,}", "Anthropic API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"ASIA[0-9A-Z]{16}", "AWS temporary access key id"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"AIza[0-9A-Za-z_\-]{35}", "Google API key"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    (r"(?i)\b(postgres|postgresql|mysql|mongodb(\+srv)?)://[^\s:@/]+:[^\s:@/]+@", "connection string with password"),
    (r"(?i)\b(aws_secret_access_key|client_secret|api[_-]?key|password)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]", "hardcoded credential"),
]

# A note is DATA. Anything that reads as an instruction aimed at a future agent is an injection
# surface, because every agent on the team loads these files as context.
INJECTION_PATTERNS = [
    (r"(?i)ignore (all |any )?(your |the )?(previous|prior|above|earlier) (instructions|rules|prompts)", "instruction override"),
    (r"(?i)disregard (the |your )?(rules|instructions|system prompt)", "instruction override"),
    (r"(?i)you (must|should) (now )?(run|execute|curl|wget|pipe)\b", "imperative command to a future agent"),
    (r"(?i)\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b|\b(irm|iwr|invoke-restmethod|invoke-webrequest)\b[^|\n]*\|\s*iex\b", "pipe-to-shell"),
    (r"(?i)\brm\s+-rf\s+/(?!tmp)", "destructive command"),
    (r"(?i)\bgit\s+push\s+(--force|-f)\b", "force-push instruction"),
    (r"(?i)without (asking|confirming|telling) (the )?(user|human)", "instruction to bypass the human"),
    (r"(?i)\bdo not (tell|inform|mention to) the (user|human)", "instruction to conceal"),
    # 2026-09 review: the two phrasings that passed were a note telling agents to claim to be a
    # person, and one telling them to keep guard warnings from the user. Measured: 0 false
    # positives over the template's and a real instance's 97 notes.
    ('(?i)\\b(set|export|use|pass|add)\\b[^.\\n]{0,40}\\bMEMORY_(ACTOR_KIND|ACTOR_EMAIL|POLICY_REF|SYNC_MODE)\\b', "instruction to change the guard's view of who is acting"),
    ('(?i)--no-verify\\b', 'instruction to skip the commit gate'),
    ('(?i)\\b(skip|bypass|disable|turn off|get around|work around)\\b[^.\\n]{0,25}\\b(the )?(memory )?(guard|gate|hooks?|pre-commit|branch protection|code ?owners)\\b', 'instruction to bypass a control'),
    ('(?i)\\b(note|message|reminder|instructions?) (to|for) (all |any |the |future |other )*(ai |coding )?(agents?|assistants?|models?|llms?|claude|copilots?)\\b', 'text addressed to future agents'),
    ("(?i)\\b(do not|don't|never|avoid)\\b[^.\\n]{0,15}\\b(mention|report|show|surface|tell|reveal|flag|raise)\\b[^.\\n]{0,40}\\b(to )?(the )?(user|human|person|owner|reviewer)s?\\b", 'instruction to conceal'),
    ('(?i)\\b(hide|conceal|suppress|silence)\\b[^.\\n]{0,30}\\b(warnings?|errors?|findings?|guard|blocks?)\\b[^.\\n]{0,20}\\b(from )?(the )?(user|human|reviewer)', 'instruction to conceal'),
]
# Paths that legitimately contain instructions to agents.
# ARCHITECTURE.md documents the deny-list and the threat model, so it quotes the very commands the
# patterns look for; it is L2 (a person with the role writes it), never agent-written.
INSTRUCTION_PATHS = ("governance/", "CLAUDE.md", ".claude/", ".kiro/", ".cursor/", ".agents/", "README.md", "templates/",
                     "ARCHITECTURE.md", "RUNBOOK.md")


def scan_secrets(f, path, text):
    if SECRET_FILE_RE.search(path):
        f.add("FAIL", "SECRET-FILE", path, "file name looks like a credential store",
              "credentials never enter memory at any level; reference the source by name instead")
        return
    for pat, label in SECRET_CONTENT:
        m = re.search(pat, text)
        if m:
            snippet = m.group(0)[:12] + "..."
            f.add("FAIL", "SECRET-CONTENT", path, "%s detected (%s)" % (label, snippet),
                  "remove the value; name the source instead (e.g. 'the key in AWS Secrets Manager')")
            return


def scan_injection(ctx, f, path, text):
    rel = path[len(ctx.prefix):] if ctx.prefix and path.startswith(ctx.prefix) else path
    if any(rel == p or rel.startswith(p) for p in INSTRUCTION_PATHS):
        return  # these files are supposed to instruct agents
    playbook = rel.startswith("playbooks/")
    for pat, label in INJECTION_PATTERNS:
        m = re.search(pat, text)
        if m and playbook and label == "pipe-to-shell":
            # Real installers do this; a playbook records what worked. Replay shows it highlighted.
            f.add("WARN", "PLAYBOOK-PIPE", path,
                  "a step pipes a download into a shell: %r" % m.group(0)[:70],
                  "replay shows this step highlighted and asks before running it")
            continue
        if m:
            f.add("FAIL", "INJECTION", path,
                  "note contains what reads as an instruction to a future agent (%s): %r"
                  % (label, m.group(0)[:70]),
                  "memory notes are data, not instructions. State the fact; if an agent must be "
                  "told to behave differently, that is a governance change (L3)")
            return


def strip_code(text, inline=False):
    """Blank out fenced code blocks and inline code spans, keeping line count.

    A note that SHOWS an example - a feature template, a sample relation - must not be read as
    DECLARING it. Before this, an example `- depends_on [[Billing]]` inside a ``` fence created a
    phantom graph edge, a phantom cascade target, and a phantom observation on the note that merely
    documented the syntax."""
    out, fence = [], None
    for ln in text.split("\n"):
        m = re.match(r"^\s*(`{3,}|~{3,})", ln)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append("")
            continue
        if m:
            fence = m.group(1)
            out.append("")
            continue
        # Inline spans only when asked: stripping them from an observation would delete the
        # backticked words from the claim itself.
        out.append(re.sub(r"`[^`\n]*`", "", ln) if inline else ln)
    return "\n".join(out)


# --------------------------------------------------------------------------- duplicate detection


def observation_tokens(text):
    lines = [ln.strip().lower() for ln in strip_code(text).split("\n") if ln.strip().startswith("- ")]
    toks = set()
    for ln in lines:
        toks |= {w for w in re.findall(r"[a-z0-9_.\-/]{3,}", ln)}
    return toks


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def check_duplicate(ctx, f, path, text):
    sig = ctx.policy.get("significance", {})
    threshold = sig.get("duplicate_similarity_threshold", 0.85)
    days = sig.get("duplicate_lookback_days", 30)
    journal_dir = os.path.join(ctx.notes_root, "log", "journal")
    if not os.path.isdir(journal_dir):
        return
    new_toks = observation_tokens(text)
    if len(new_toks) < 8:
        return  # too small to judge
    cutoff = time.time() - days * 86400
    target = os.path.abspath(os.path.join(ctx.repo_root, path))
    for name in os.listdir(journal_dir):
        if not name.endswith(".md"):
            continue
        other = os.path.join(journal_dir, name)
        if os.path.abspath(other) == target:
            continue
        try:
            if os.path.getmtime(other) < cutoff:
                continue
            sim = jaccard(new_toks, observation_tokens(read_text(other)))
        except OSError:
            continue
        if sim >= threshold:
            f.add("FAIL", "DUPLICATE", path,
                  "%.0f%% of this note's observations already exist in log/journal/%s" % (sim * 100, name),
                  "update that note instead of adding a second one; memory that repeats itself "
                  "is memory nobody reads")
            return


# --------------------------------------------------------------------------- claims

# A claim is an observation line: `- [category] text ^id`. The id is permanent: assigned once by
# `stamp`, carried forward when the line is edited, never recomputed. Everything that refers to a
# single fact - pins, mutes, trials, evals, recall logs, `why` - refers to this id.
CLAIM_LINE = re.compile(r"^(\s*-\s*\[([a-zA-Z][\w-]*)\]\s*)(.*?)(?:\s+\^([0-9a-f]{6}))?\s*$")
CARRY_THRESHOLD = 0.5


def parse_claims(body):
    """[(line_index, category, text, id_or_None, section)] for every claim outside code."""
    out, section = [], ""
    for i, ln in enumerate(strip_code(body or "").split("\n")):
        h = re.match(r"^##\s+(.+?)\s*$", ln)
        if h:
            section = h.group(1).strip().lower()
            continue
        m = CLAIM_LINE.match(ln)
        if m and m.group(3).strip():
            out.append((i, m.group(2).lower(), m.group(3).strip(), m.group(4), section))
    return out


def note_sections(body):
    """{lowercased heading: text} for every `## ` section outside code."""
    lines = (body or "").split("\n")
    plain = strip_code(body or "").split("\n")
    out, cur, buf = {}, None, []
    for raw, ln in zip(lines, plain):
        h = re.match(r"^##\s+(.+?)\s*$", ln)
        if h:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = h.group(1).strip().lower(), []
        elif cur is not None:
            buf.append(raw)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def fm_list(fm_lines, key):
    raw = fm_get(fm_lines, key) or ""
    return [x.strip().strip("'\"") for x in raw.strip("[]").split(",") if x.strip().strip("'\"")]


def _claim_tokens(text):
    return {w for w in re.findall(r"[a-z0-9_.\-/]{3,}", (text or "").lower())}


def _claim_similarity(a, b):
    """Token overlap OR character similarity, whichever is higher. Jaccard alone misses the
    common agent edit - a typo fixed, a number updated, a clause appended - where most words
    survive but the set changes; SequenceMatcher alone misses reordered sentences."""
    return max(jaccard(_claim_tokens(a), _claim_tokens(b)),
               difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio())


def new_claim_id(note_id, text, taken):
    seed = note_id + "\n" + re.sub(r"\s+", " ", (text or "").strip().lower())
    n = 0
    while True:
        cid = hashlib.sha1((seed + ("" if n == 0 else "#%d" % n)).encode("utf-8")).hexdigest()[:6]
        if cid not in taken:
            return cid
        n += 1


def all_claim_ids(ctx):
    """{claim_id: repo_rel_path} for every claim in this tier's working tree."""
    out = {}
    for _st, path in all_notes_as_changes(ctx):
        try:
            _fm, body = split_frontmatter(read_text(os.path.join(ctx.repo_root, path)))
        except OSError:
            continue
        for (_i, _c, _t, cid, _s) in parse_claims(body):
            if cid:
                out.setdefault(cid, path)
    return out


def stamp_claim_ids(note_id, body, prev_body=None, foreign=None):
    """Give every claim an id, carrying ids forward across edits. Returns (body, stamped, carried).

    The failure this exists to prevent: an agent rewrites a line and drops its `^id`, and every
    pin, trial and log entry pointing at that fact silently detaches. An unmarked line is matched
    against the ids that vanished from this note since HEAD; a close enough match inherits the id.
    A one-for-one swap - one id gone, one unmarked line - is treated as an edit regardless of how
    different the words are, because that is overwhelmingly what it is."""
    lines = (body or "").split("\n")
    claims = parse_claims(body)
    # A line ENDING with another note's claim id is referencing it, not claiming its identity -
    # `recall "..." includes ^be2885`. Left alone, the reference would be read as this line's own
    # id and two facts would share one name. Such a line keeps the reference in its text and gets
    # its own id appended after it.
    foreign = foreign or set()
    for (i, _c, _t, cid, _s) in claims:
        if cid and cid in foreign:
            lines[i] = lines[i].rstrip() + " ^" + new_claim_id(note_id, lines[i], foreign | {cid})
    claims = parse_claims("\n".join(lines))
    seen, dupes = set(), set()
    for (i, _c, _t, cid, _s) in claims:
        if cid and cid in seen:
            dupes.add(i)
        elif cid:
            seen.add(cid)
    for i in dupes:  # a copy-pasted line keeps nothing of its original's identity
        lines[i] = re.sub(r"\s+\^[0-9a-f]{6}\s*$", "", lines[i])
    claims = parse_claims("\n".join(lines))
    have = {c[3] for c in claims if c[3]}
    orphans = [c for c in parse_claims(prev_body)] if prev_body else []
    orphans = [c for c in orphans if c[3] and c[3] not in have]
    unmarked = [c for c in claims if not c[3]]
    used, taken, stamped, carried = set(), set(have), 0, 0
    one_for_one = len(unmarked) == 1 and len(orphans) == 1
    for (i, _cat, text, _cid, _sec) in unmarked:
        best, best_sim = None, 0.0
        for (pi, _pc, ptext, pid, _ps) in orphans:
            if pid in used:
                continue
            sim = _claim_similarity(text, ptext)
            if sim > best_sim:
                best, best_sim = pid, sim
        if best and (best_sim >= CARRY_THRESHOLD or one_for_one):
            cid = best
            used.add(best)
            carried += 1
        else:
            cid = new_claim_id(note_id, text, taken)
        taken.add(cid)
        lines[i] = lines[i].rstrip() + " ^" + cid
        stamped += 1
    return "\n".join(lines), stamped, carried


def estimate_tokens(text):
    """An ESTIMATE, characters / 3.8. No tokenizer ships with the standard library."""
    return int(round(len(text or "") / 3.8))


# --------------------------------------------------------------------------- features

FEATURE_STATUSES = ("planned", "building", "live", "retired")
TRIAL_STATUSES = ("live", "kept", "dropped")


def code_root(ctx):
    """Where `covers:` globs are resolved. A project's memory lives inside the code repo, so the
    code root is that repo; the company tier has no code unless MEMORY_CODE_ROOT says otherwise."""
    env = os.environ.get("MEMORY_CODE_ROOT")
    if env:
        return os.path.abspath(env)
    rel = (ctx.policy.get("protocol") or {}).get("code_root")
    if rel is not None:
        # relative to the repo root: "." when the notes repo documents its own scripts (cairn)
        return os.path.normpath(os.path.join(ctx.repo_root, rel))
    return ctx.repo_root if ctx.prefix else None


_CODE_FILES = {}


def code_files(root):
    """Every tracked file under the code root, relative to it. git ls-files when possible, since
    it respects .gitignore and is fast; a bounded walk otherwise."""
    if root in _CODE_FILES:
        return _CODE_FILES[root]
    out = [x for x in git("-C", root, "ls-files").splitlines() if x.strip()]
    if not out:
        skip = {".git", "node_modules", ".venv", "venv", "__pycache__", ".memory", "dist", "build"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for fn in filenames:
                out.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
                if len(out) > 200000:
                    break
    _CODE_FILES[root] = out
    return out


def load_features(ctx):
    """[(repo_rel_path, title, covers, status)] for every feature note in this tier."""
    out = []
    root = os.path.join(ctx.notes_root, "features")
    if not os.path.isdir(root):
        return out
    for dirpath, _dn, filenames in os.walk(root):
        for fn in sorted(filenames):
            if not fn.endswith(".md"):
                continue
            abs_path = os.path.join(dirpath, fn)
            try:
                fm, _ = split_frontmatter(read_text(abs_path))
            except OSError:
                continue
            if fm is None:
                continue
            rel = os.path.relpath(abs_path, ctx.repo_root).replace(os.sep, "/")
            out.append((rel, (fm_get(fm, "title") or fn[:-3]).strip(),
                        fm_list(fm, "covers"), fm_get(fm, "status")))
    return out


# --------------------------------------------------------------------------- note validation

REQUIRED_KEYS = ("title", "type", "tags")
ADR_STATUSES = ("proposed", "accepted", "rejected", "deprecated", "superseded", "template")


def repo_titles(ctx):
    """Every note title in this tier — used to check that [[wikilinks]] resolve."""
    titles = set()
    # Root notes count too: CORE.md, README.md and RUNBOOK.md are linked to by everything, and
    # leaving them out reported every such link as pointing at a note that does not exist.
    for fn in os.listdir(ctx.notes_root):
        if fn.endswith(".md") and os.path.isfile(os.path.join(ctx.notes_root, fn)):
            try:
                fm, _ = split_frontmatter(read_text(os.path.join(ctx.notes_root, fn)))
            except OSError:
                continue
            t = fm_get(fm, "title") if fm else None
            if t:
                titles.add(t.strip())
    for d in NOTE_DIRS:
        root = os.path.join(ctx.notes_root, d)
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                try:
                    fm, _ = split_frontmatter(read_text(os.path.join(dirpath, fn)))
                except OSError:
                    continue
                t = fm_get(fm, "title") if fm else None
                if t:
                    titles.add(t.strip())
    return titles


def validate_note(ctx, f, path, text, known_titles, strict_attribution):
    fm, body = split_frontmatter(text)
    if fm is None:
        f.add("FAIL", "FRONTMATTER", path, "note has no YAML frontmatter",
              "add title, type, tags, level, confidentiality — `memory_guard.py stamp` does it for you")
        return
    for key in REQUIRED_KEYS:
        if not fm_get(fm, key):
            f.add("FAIL", "FRONTMATTER", path, "frontmatter is missing `%s`" % key,
                  "run: uv run -q --script scripts/memory_guard.py stamp --staged")

    required_level = ctx.path_level(path)
    declared = fm_get(fm, "level")
    if declared and required_level and required_level != "bot" and declared != required_level:
        f.add("FAIL", "LEVEL-MISMATCH", path,
              "frontmatter declares level %s but its location is %s" % (declared, required_level),
              "a note cannot declare a level its folder does not grant. Move the note, or correct "
              "the declaration")

    conf = fm_get(fm, "confidentiality") or ctx.policy["sensitivity"]["default"]
    restricted_home = (ctx.policy["sensitivity"]["tiers"].get("restricted") or {}).get("allowed_paths", [])
    rel_n = norm_path(path[len(ctx.prefix):] if ctx.prefix else path)
    if conf != "restricted" and any(glob_match(g.casefold(), rel_n) for g in restricted_home):
        # The restricted location wins over the label: one `confidentiality: open` line there
        # published a full restricted body (audit 07-F7).
        f.add("FAIL", "SENSITIVITY", path,
              "notes under %s must be `confidentiality: restricted` (this one says %r)" % (", ".join(restricted_home), conf),
              "publish a restricted fact by writing a separate, reviewed note outside the restricted folder")
    tier = ctx.policy["sensitivity"]["tiers"].get(conf)
    if tier is None:
        f.add("FAIL", "SENSITIVITY", path, "unknown confidentiality %r" % conf,
              "one of: " + ", ".join(ctx.policy["sensitivity"]["tiers"]))
    else:
        rel = path[len(ctx.prefix):] if ctx.prefix else path
        if not any(glob_match(g, rel) for g in tier.get("allowed_paths", ["**"])):
            f.add("FAIL", "SENSITIVITY", path,
                  "confidentiality `%s` is not permitted at this path" % conf,
                  "allowed: %s. `restricted` content belongs in the separate private submodule, "
                  "never in this repo" % ", ".join(tier.get("allowed_paths", [])))

    if strict_attribution:
        people = {k for k in ctx.policy.get("people", {}) if not k.startswith("$")}
        author = fm_get(fm, "author")            # who created it
        editor = fm_get(fm, "updated_by")        # who last changed it
        if not author:
            f.add("FAIL", "ATTRIBUTION", path, "note does not say who wrote it",
                  "every stored fact carries a name; `stamp` sets it from your git identity")
        elif author not in people:
            f.add("FAIL", "ATTRIBUTION", path,
                  "author %r is not a handle in governance/roles.json" % author,
                  "add the person to roles.json, or correct the handle")
        if editor and editor not in people:
            f.add("FAIL", "ATTRIBUTION", path,
                  "updated_by %r is not a handle in governance/roles.json" % editor,
                  "add the person to roles.json, or correct the handle")
        elif ctx.handle and ctx.actor_kind != "bot" and editor != ctx.handle:
            f.add("FAIL", "ATTRIBUTION", path,
                  "note records updated_by=%r but the committing identity is %r (%s)"
                  % (editor, ctx.handle, ctx.email),
                  "attribution is taken from git, not from the note - it cannot be reassigned by "
                  "hand. Run `stamp --staged` and commit again")

    rel = path[len(ctx.prefix):] if ctx.prefix else path
    if rel.startswith("decisions/") and os.path.basename(rel).startswith("ADR-"):
        st = fm_get(fm, "status")
        if st not in ADR_STATUSES:
            f.add("FAIL", "ADR-STATUS", path, "ADR status %r is not in the lifecycle" % st,
                  "one of: " + ", ".join(ADR_STATUSES))

    declared = strip_code(body, inline=True)
    rels = re.findall(r"^\s*-\s+(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)?\s*\[\[([^\]]+)\]\]",
                      declared, re.M)
    inline = re.findall(r"\[\[([^\]]+)\]\]", declared)
    if not rels and not inline:
        f.add("FAIL", "GRAPH", path, "note has no relations, so nothing links to it",
              "add at least one `- relates_to [[Existing Note Title]]` under ## Relations — an "
              "unlinked note is invisible to graph traversal and will not be found")
    else:
        for target in set(rels):
            t = target.strip()
            if t.startswith("<") or t.startswith("__"):
                continue  # template placeholder
            if t not in known_titles:
                f.add("WARN", "GRAPH", path, "relation target [[%s]] does not exist yet" % t,
                      "forward references are allowed and resolve when the note is created — "
                      "check the spelling if that was not intentional")

    # --- claims --------------------------------------------------------
    claims = parse_claims(body)
    ids = [c[3] for c in claims if c[3]]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        f.add("FAIL", "CLAIM-ID", path, "claim id(s) used twice in one note: %s" % ", ".join(dupes),
              "an id names ONE fact; `stamp` gives a copy-pasted line a fresh id")
    unmarked = sum(1 for c in claims if not c[3])
    if unmarked:
        f.add("WARN", "CLAIM-ID", path, "%d claim(s) have no id yet" % unmarked,
              "`stamp` assigns ids; sync-memory post runs it before every commit")

    proto = ctx.policy.get("protocol", {})
    if rel == "CORE.md":
        est = estimate_tokens(text)
        cap = proto.get("core_max_tokens", 3000)
        if est > cap:
            f.add("WARN", "CORE-SIZE", path,
                  "CORE.md is ~%d tokens (estimate); the ceiling is %d" % (est, cap),
                  "every agent reads the core first on every task. Move detail into features/ or "
                  "context/ and keep the core to what everyone must know")

    if rel.startswith("features/"):
        st = fm_get(fm, "status")
        if st not in FEATURE_STATUSES:
            f.add("FAIL", "FEATURE", path, "feature status %r is not one of %s"
                  % (st, ", ".join(FEATURE_STATUSES)), "planned | building | live | retired")
        if not fm_get(fm, "owner"):
            f.add("FAIL", "FEATURE", path, "feature has no owner",
                  "a feature with no owner is a feature nobody keeps current")
        secs = note_sections(body)
        card = secs.get("card")
        if card is None:
            f.add("FAIL", "FEATURE", path, "feature has no `## Card` section",
                  "the card is what a plan-mode read loads for every feature: what it is, who it "
                  "serves, current state, what is in flight")
        else:
            words = len(re.findall(r"\S+", strip_code(card)))
            limit = proto.get("card_max_words", 150)
            if words > limit:
                f.add("WARN", "FEATURE", path, "card is %d words (limit %d)" % (words, limit),
                      "a card is read for every feature at once; detail belongs below it")
        if st == "live" and "contract" not in secs:
            f.add("WARN", "FEATURE", path, "live feature has no `## Contract` section",
                  "the contract is what downstream agents are alerted about when it changes")
        covers = fm_list(fm, "covers")
        if not covers and st in ("building", "live"):
            f.add("WARN", "FEATURE-COVERS", path, "feature covers no code",
                  "without `covers:` an agent editing this feature's files cannot find it")
        root = code_root(ctx)
        if root and covers:
            files = code_files(root)
            for g in covers:
                if not any(glob_match(g, x) for x in files):
                    f.add("WARN", "FEATURE-COVERS", path,
                          "covers glob %r matches no file under %s" % (g, root),
                          "the code moved or was deleted: a stale feature announces itself here")

    if rel.startswith("trials/"):
        st = fm_get(fm, "status")
        if st not in TRIAL_STATUSES:
            f.add("FAIL", "TRIAL", path, "trial status %r is not one of %s"
                  % (st, ", ".join(TRIAL_STATUSES)), "live | kept | dropped")
        for key in ("hypothesis", "owner", "expires"):
            if not fm_get(fm, key):
                f.add("FAIL", "TRIAL", path, "trial is missing `%s`" % key,
                      "a trial states what it expects, whose it is, and when it ends")
        exp = fm_get(fm, "expires")
        if st == "live" and exp:
            try:
                if datetime.strptime(exp[:10], "%Y-%m-%d").date() < datetime.now(timezone.utc).date():
                    f.add("WARN", "TRIAL", path, "trial expired on %s" % exp[:10],
                          "`mem expire` closes it and records what happened")
            except ValueError:
                f.add("FAIL", "TRIAL", path, "expires %r is not a date" % exp, "YYYY-MM-DD")

    if rel.startswith("log/journal/"):
        cap = ctx.policy.get("significance", {}).get("journal_max_lines", 80)
        n = len(text.split("\n"))
        if n > cap:
            f.add("FAIL", "NOISE", path, "journal note is %d lines (cap %d)" % (n, cap),
                  "a signal note is a fact and its consequence, not a transcript. Cut it down, or "
                  "if it is really a decision, write a proposal instead")
        transcripty = len(re.findall(r"(?im)^\s*(user|assistant|human|ai)\s*:", text))
        if transcripty >= 4:
            f.add("FAIL", "NOISE", path, "note looks like a pasted conversation transcript",
                  "store the conclusion, not the conversation")


# --------------------------------------------------------------------------- commands


def all_notes_as_changes(ctx):
    out = []
    for fn in sorted(os.listdir(ctx.notes_root)):
        if fn.endswith(".md") and os.path.isfile(os.path.join(ctx.notes_root, fn)):
            out.append(("M", (ctx.prefix + fn) if ctx.prefix else fn))
    for d in NOTE_DIRS:
        for dirpath, _dn, filenames in os.walk(os.path.join(ctx.notes_root, d)):
            for fn in filenames:
                if fn.endswith(".md"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), ctx.repo_root)
                    out.append(("M", rel.replace(os.sep, "/")))
    return out


def cmd_stamp(ctx, args):
    """Fill attribution and classification from git identity — never from what an agent claims."""
    files = all_notes_as_changes(ctx) if getattr(args, "all", False) else changed_files(ctx, staged=args.staged)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    changed = []
    tier_ids = None
    for status, path in files:
        if status == "D" or not is_note(ctx, path):
            continue
        abs_path = os.path.join(ctx.repo_root, path)
        if not os.path.isfile(abs_path):
            continue
        rel = path[len(ctx.prefix):] if ctx.prefix else path
        if rel.startswith("log/CHANGELOG.md") or "/templates/" in "/" + rel:
            continue
        text = read_text(abs_path)
        fm, body = split_frontmatter(text)
        if fm is None:
            title = os.path.splitext(os.path.basename(path))[0].replace("-", " ").strip()
            m = re.search(r"^#\s+(.+)$", text, re.M)
            if m:
                title = m.group(1).strip()
            fm, body = ["title: %s" % title, "type: note", "tags: []"], text

        level = ctx.path_level(path)
        if level and level != "bot":
            fm = fm_set(fm, "level", level)
        if not fm_get(fm, "confidentiality"):
            fm = fm_set(fm, "confidentiality", ctx.policy["sensitivity"]["default"])
        if ctx.handle:
            is_new = not exists_at(ctx, "HEAD", path)
            if is_new or not fm_get(fm, "author"):
                fm = fm_set(fm, "author", ctx.handle)      # creator: set from git when the note is new
            fm = fm_set(fm, "updated_by", ctx.handle)      # last editor, always current
        if ctx.actor_kind == "agent":
            fm = fm_set(fm, "agent", ctx.agent_name)
        if not fm_get(fm, "created"):
            fm = fm_set(fm, "created", today)
        fm = fm_set(fm, "updated", today)

        prev = git("-C", ctx.repo_root, "show", "HEAD:" + path)
        prev_body = split_frontmatter(prev)[1] if prev else None
        note_id = rel[:-3] if rel.endswith(".md") else rel
        if tier_ids is None:
            tier_ids = all_claim_ids(ctx)
        foreign = {cid for cid, where in tier_ids.items() if where != path}
        body, _stamped, _carried = stamp_claim_ids(note_id, body, prev_body, foreign)

        new_text = render(fm, body)
        if new_text != text:
            write_text(abs_path, new_text)
            changed.append(path)
    if changed and args.staged:
        git("-C", ctx.repo_root, "add", "--", *changed)
    if changed:
        print("memory-guard: stamped %d note(s): %s" % (len(changed), ", ".join(changed[:5])))
    return EXIT_OK


def range_base(ctx, rng):
    """The trusted side of a commit range: the merge base for A...B, A for A..B."""
    if "..." in rng:
        a, b = rng.split("...", 1)
        return git("-C", ctx.repo_root, "merge-base", a or "HEAD", b or "HEAD").strip() or a
    if ".." in rng:
        return rng.split("..", 1)[0] or "HEAD"
    return rng


def exists_at(ctx, ref, path):
    if not ref:
        return False
    return subprocess.run(["git", "-C", ctx.repo_root, "cat-file", "-e", "%s:%s" % (ref, path)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def handle_for_email(ctx, email):
    if not usable_email(email):
        return None
    for handle, p in ctx.policy.get("people", {}).items():
        if handle.startswith("$") or not isinstance(p, dict) or not usable_email(p.get("email")):
            continue
        if p["email"].strip().lower() == email.strip().lower():
            return handle
    return None


def check_new_author(ctx, f, path, text, rng):
    """A NEW note's author is whoever introduced it: the committing identity locally, the author of
    the introducing commit in a range. Stamp used to keep any `author:` the writer supplied, so a
    note could be filed under another registered person (audit 01-F5, 10-F3)."""
    fm, _body = split_frontmatter(text)
    author = fm_get(fm or [], "author")
    if rng:
        emails = git("-C", ctx.repo_root, "log", "--diff-filter=A", "--format=%ae", rng, "--", path).split()
        who = handle_for_email(ctx, emails[-1]) if emails else None
        if who is None:
            f.add("FAIL", "ATTRIBUTION", path,
                  "introduced by %r, who is not a registered person" % (emails[-1] if emails else "?"),
                  "commits that add notes must be authored by someone listed in governance/roles.json")
            return
    else:
        who = ctx.handle
    if ctx.actor_kind == "bot" or who is None:
        return
    if author != who:
        f.add("FAIL", "ATTRIBUTION", path,
              "new note records author=%r but it is being introduced by %r" % (author, who),
              "a new note's author is set from git by `stamp`; it cannot name someone else")


def check_range_editor(ctx, f, path, text, rng):
    """CI: an existing note's `updated_by` must be the registered author of the last commit in the
    range that touched it. The old inline workflow check skipped unregistered committers entirely
    (audit 10-F3)."""
    emails = git("-C", ctx.repo_root, "log", "-1", "--format=%ae", rng, "--", path).split()
    who = handle_for_email(ctx, emails[0]) if emails else None
    if who is None:
        f.add("FAIL", "ATTRIBUTION", path,
              "last changed by %r, who is not a registered person" % (emails[0] if emails else "?"),
              "commits that change notes must be authored by someone listed in governance/roles.json")
        return
    fm, _b = split_frontmatter(text)
    editor = fm_get(fm or [], "updated_by")
    if editor != who:
        f.add("FAIL", "ATTRIBUTION", path,
              "note records updated_by=%r but the last commit touching it is by %r" % (editor, who),
              "attribution comes from git; run `stamp` before committing")


# --------------------------------------------------------------------------- playbooks
# A playbook is a finished multi-step task someone did with an AI, written down so a teammate's AI
# can walk them through it: ordered steps, each with a check, and the problems hit with their fixes.
# Trust is DERIVED, never stored: an approval is bound to a hash of the steps, and a replay counts
# only if someone other than the author logged a success against the current steps (ADR-005).

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PLAYBOOK_ID_RX = re.compile(r"^PB-[%s]{4}$" % CROCKFORD)
STEP_HEAD_RX = re.compile(r"^###\s+(\d+)\.\s+(.*?)\s*$")
STEP_MARK_RX = re.compile(r"\[([A-Za-z]+)\]\s*$")
STEP_MARKERS = ("check", "local", "external")
RUN_RX = re.compile(r"^(\d{4}-\d{2}-\d{2}) ([a-z][a-z0-9_-]{0,31}) (success|failed|partial) ([0-9a-f]{8})(?: (.*))?$")
PLACEHOLDER_LINT = [
    (r"(?i)\b[a-z]:\\users\\(?!<)[^\\\s<>]+", "a Windows home path"),
    (r"(?<![\w<])/(?:Users|home)/(?!<)[A-Za-z0-9._-]+", "a home directory path"),
    (r"(?<!\d)\d{12}(?!\d)", "a 12-digit number (an AWS account id?)"),
    (r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b", "a private IP address"),
]
STALE_DAYS = 90


def is_playbook(ctx, path):
    rel = path[len(ctx.prefix):] if ctx.prefix and path.startswith(ctx.prefix) else path
    return rel.startswith("playbooks/") and rel.endswith(".md") and os.path.basename(rel).lower() != "readme.md"


def is_runlog(ctx, path):
    rel = path[len(ctx.prefix):] if ctx.prefix and path.startswith(ctx.prefix) else path
    return rel.startswith("playbooks/") and rel.endswith(".runs")


def section(body, name):
    """The text of `## name` up to the next `## ` heading (not `###`)."""
    out, on = [], False
    for ln in body.split("\n"):
        if re.match(r"^##\s+", ln) and not ln.startswith("###"):
            if on:
                break
            on = ln[2:].strip().lower() == name.lower()
            continue
        if on:
            out.append(ln)
    return "\n".join(out) if on or out else None


def steps_hash(body):
    """8 hex characters over the normalised ## Steps section. An approval and a replay are made
    against this; editing any step changes it, which is what drops stale trust on its own."""
    sec = section(body, "Steps") or ""
    lines = [ln.rstrip() for ln in sec.strip("\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:8]


def parse_steps(body):
    """[{n, title, marker, run, check, lines}] from the ## Steps section, in order."""
    sec = section(body, "Steps")
    if sec is None:
        return []
    steps, cur = [], None
    for ln in sec.split("\n"):
        m = STEP_HEAD_RX.match(ln)
        if m:
            title = m.group(2)
            mk = STEP_MARK_RX.search(title)
            marker = mk.group(1).lower() if mk else None
            if mk:
                title = title[:mk.start()].rstrip()
            cur = {"n": int(m.group(1)), "title": title, "marker": marker, "run": None, "check": None, "lines": []}
            steps.append(cur)
            continue
        if cur is None:
            continue
        cur["lines"].append(ln)
        low = ln.strip().lower()
        if low.startswith("run:") and cur["run"] is None:
            cur["run"] = ln.strip()[4:].strip()
        elif low.startswith("check:") and cur["check"] is None:
            cur["check"] = ln.strip()[6:].strip()
    return steps


def parse_runs(text):
    """([run dicts], [bad lines]) from a .runs file."""
    runs, bad = [], []
    for ln in (text or "").split("\n"):
        if not ln.strip():
            continue
        m = RUN_RX.match(ln.strip())
        if not m:
            bad.append(ln)
            continue
        runs.append({"date": m.group(1), "who": m.group(2), "outcome": m.group(3), "steps": m.group(4),
                     "note": m.group(5) or "", "line": ln.strip()})
    return runs, bad


def approve_level(ctx):
    """Who may approve a playbook: a maintainer (L1) in a project tier, a steward (L2) in the
    company tier, unless roles.json `playbooks.approve_level` says otherwise."""
    cfg = (ctx.policy.get("playbooks") or {}).get("approve_level")
    return cfg if cfg in LEVEL_ORDER else ("L1" if ctx.prefix else "L2")


def person_level(ctx, handle):
    p = (ctx.policy.get("people") or {}).get(handle)
    if not isinstance(p, dict):
        return None
    return ((ctx.policy.get("roles") or {}).get(p.get("role")) or {}).get("max_level")


def playbook_trust(ctx, fm, body, runs, today=None):
    """{label: approved|reproduced|unreviewed, stale, last_success, successes, runs, steps}."""
    h = steps_hash(body)
    author = fm_get(fm or [], "author")
    by = fm_get(fm or [], "approved_by")
    approved = bool(by and fm_get(fm or [], "approved_steps") == h
                    and level_allows(person_level(ctx, by), approve_level(ctx)))
    good = [r for r in runs if r["outcome"] == "success"]
    reproduced = any(r["steps"] == h and r["who"] != author for r in good)
    last = max((r["date"] for r in good), default=None)
    today = today or datetime.now(timezone.utc).date()
    stale = False
    if last:
        try:
            stale = (today - datetime.strptime(last, "%Y-%m-%d").date()).days > STALE_DAYS
        except ValueError:
            stale = False
    return {"label": "approved" if approved else "reproduced" if reproduced else "unreviewed",
            "stale": stale, "last_success": last, "successes": len(good), "runs": len(runs), "steps": h,
            "failed": sum(1 for r in runs if r["outcome"] == "failed")}


def playbook_ids(ctx):
    """id -> [paths] for every playbook in this tier."""
    out = {}
    root = os.path.join(ctx.notes_root, "playbooks")
    for dirpath, _d, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".md") or fn.lower() == "readme.md":
                continue
            p = os.path.join(dirpath, fn)
            try:
                fm, _b = split_frontmatter(read_text(p))
            except OSError:
                continue
            pid = fm_get(fm or [], "id")
            if pid:
                out.setdefault(pid, []).append(os.path.relpath(p, ctx.repo_root).replace(os.sep, "/"))
    return out


def validate_playbook(ctx, f, path, text):
    fm, body = split_frontmatter(text)
    fm = fm or []
    pid = fm_get(fm, "id") or ""
    if not PLAYBOOK_ID_RX.match(pid):
        f.add("FAIL", "PLAYBOOK", path, "id %r is not PB- plus 4 Crockford base32 characters" % pid,
              "`mem playbook save` assigns one, e.g. PB-7K3F")
    else:
        homes = playbook_ids(ctx).get(pid, [])
        if len(homes) > 1:
            f.add("FAIL", "PLAYBOOK", path, "id %s is used by %d playbooks: %s" % (pid, len(homes), ", ".join(sorted(homes))),
                  "every playbook in a tier has its own id; `mem playbook save` picks a free one")
        if not os.path.basename(path).startswith(pid):
            f.add("WARN", "PLAYBOOK", path, "the file name does not start with its id %s" % pid,
                  "name it %s-<slug>.md so the run log beside it is easy to find" % pid)
    if (fm_get(fm, "type") or "") != "playbook":
        f.add("FAIL", "PLAYBOOK", path, "a note under playbooks/ must have type: playbook", "set type: playbook")
    steps = parse_steps(body)
    if not steps:
        f.add("FAIL", "PLAYBOOK", path, "no steps: a playbook needs a ## Steps section with `### 1. ...` steps",
              "write the steps that actually worked, in order")
        return
    nums = [s_["n"] for s_ in steps]
    if nums != list(range(1, len(steps) + 1)):
        f.add("FAIL", "PLAYBOOK", path, "steps are numbered %s, not 1..%d" % (nums, len(steps)),
              "number the steps 1, 2, 3 ... without gaps")
    for s_ in steps:
        if s_["marker"] and s_["marker"] not in STEP_MARKERS:
            f.add("FAIL", "PLAYBOOK", path, "step %d has marker [%s]; use [check], [local] or [external]" % (s_["n"], s_["marker"]),
                  "[check] only reads, [local] changes this machine, [external] changes anything shared")
        if not s_["marker"]:
            f.add("WARN", "PLAYBOOK", path, "step %d has no marker, so replay treats it as [external]" % s_["n"],
                  "mark it [check], [local] or [external]")
        if not s_["check"]:
            f.add("WARN", "PLAYBOOK", path, "step %d has no `Check:` line" % s_["n"],
                  "an unverifiable step is where replays go wrong silently; say how to tell it worked")
    emails = {(p.get("email") or "").lower() for h_, p in (ctx.policy.get("people") or {}).items() if isinstance(p, dict)}
    for pat, label in PLACEHOLDER_LINT + [(r"[\w.+-]+@[\w-]+\.[\w.-]+", "an email address")]:
        for m in re.finditer(pat, body):
            if label == "an email address" and m.group(0).lower() in emails:
                continue
            if label == "an email address" and m.group(0).lower().endswith(("example.com", "example.test", "example.org")):
                continue
            f.add("WARN", "PLAYBOOK-PLACEHOLDER", path, "%s: %r" % (label, m.group(0)[:60]),
                  "replace machine- or person-specific values with a placeholder like <YOUR_VALUE>")
            break


def _approval(fm):
    return (fm_get(fm or [], "approved_by") or "", fm_get(fm or [], "approved_steps") or "")


def check_playbook_approval(ctx, f, path, text, base_ref, rng):
    """approved_by / approved_steps may be added or changed only by a person (never an agent) whose
    level reaches approve_level, and approved_by must be that person. Removing an approval is free."""
    fm, body = split_frontmatter(text)
    new = _approval(fm)
    old = ("", "")
    if base_ref and exists_at(ctx, base_ref, path):
        ofm, _ob = split_frontmatter(git("-C", ctx.repo_root, "show", "%s:%s" % (base_ref, path)))
        old = _approval(ofm)
    if new == old or not (new[0] or new[1]):
        return
    need = approve_level(ctx)
    if rng:
        emails = git("-C", ctx.repo_root, "log", "-1", "--format=%ae", rng, "--", path).split()
        who, kind = (handle_for_email(ctx, emails[0]) if emails else None), "human"
        trailer = git("-C", ctx.repo_root, "log", "-1", "--format=%B", rng, "--", path)
        if re.search(r"(?m)^Sync-Actor:\s*agent\b", trailer):
            kind = "agent"
    else:
        who, kind = ctx.handle, ctx.actor_kind
    if kind != "human":
        f.add("FAIL", "PLAYBOOK-APPROVAL", path, "an agent set approved_by/approved_steps",
              "only a person approves a playbook, by running `mem playbook approve` themselves")
        return
    if new[0] != (who or ""):
        f.add("FAIL", "PLAYBOOK-APPROVAL", path, "approved_by=%r but the change is by %r" % (new[0], who),
              "an approval names the person who gives it; nobody approves for someone else")
        return
    if not level_allows(person_level(ctx, who), need):
        f.add("FAIL", "PLAYBOOK-APPROVAL", path, "%s cannot approve: approving needs %s" % (who, need),
              "ask a %s to review and approve it" % ("maintainer" if need == "L1" else "steward"))
        return
    if new[1] != steps_hash(body):
        f.add("FAIL", "PLAYBOOK-APPROVAL", path, "approved_steps=%r does not match the current steps (%s)" % (new[1], steps_hash(body)),
              "run `mem playbook approve` after the last edit to the steps")


def check_runlog(ctx, f, path, base_ref, rng):
    """A .runs file is append-only, every line parses, and each NEW line names whoever committed it:
    the committing identity locally, each commit's author in a range. No one logs a run for someone else."""
    abs_path = os.path.join(ctx.repo_root, path)
    cur = read_text(abs_path) if os.path.isfile(abs_path) else ""
    base = git("-C", ctx.repo_root, "show", "%s:%s" % (base_ref, path)) if base_ref and exists_at(ctx, base_ref, path) else ""
    runs, bad = parse_runs(cur)
    for ln in bad[:3]:
        f.add("FAIL", "PLAYBOOK-RUNS", path, "not a run record: %r" % ln[:80],
              "one line per run: YYYY-MM-DD <handle> success|failed|partial <steps hash> <note>; `mem playbook log` writes it")
    have = collections.Counter(r["line"] for r in runs)
    base_runs, _b = parse_runs(base)
    missing = collections.Counter(r["line"] for r in base_runs) - have
    if missing:
        f.add("FAIL", "PLAYBOOK-RUNS", path, "%d earlier run record(s) were removed or edited" % sum(missing.values()),
              "run logs are append-only; failed runs are the most useful warnings")
    if not rng:
        added = have - collections.Counter(r["line"] for r in base_runs)
        for line in added:
            who = line.split(" ")[1]
            if ctx.actor_kind != "bot" and who != ctx.handle:
                f.add("FAIL", "PLAYBOOK-RUNS", path, "a new run is logged for %r by %r" % (who, ctx.handle),
                      "log only your own runs; `mem playbook log` fills in your handle")
        return
    commits = git("-C", ctx.repo_root, "log", "--no-merges", "--format=%H %ae", rng, "--", path).split("\n")
    for row in commits:
        if not row.strip():
            continue
        sha_, email = row.split(" ", 1)
        who = handle_for_email(ctx, email)
        after, _x = parse_runs(git("-C", ctx.repo_root, "show", "%s:%s" % (sha_, path)))
        before, _y = parse_runs(git("-C", ctx.repo_root, "show", "%s^:%s" % (sha_, path)) if exists_at(ctx, sha_ + "^", path) else "")
        for line in collections.Counter(r["line"] for r in after) - collections.Counter(r["line"] for r in before):
            if line.split(" ")[1] != who:
                f.add("FAIL", "PLAYBOOK-RUNS", path, "commit %s by %r logs a run for %r" % (sha_[:7], who, line.split(" ")[1]),
                      "log only your own runs")


def cmd_classify(ctx, args):
    """Print the highest level this change needs, judged by the trusted policy plus the protected
    floor, counting both sides of every rename. CI routes review on this; the old inline classifier
    read the PR's own policy and only rename destinations (audit 10-F4)."""
    ref = args.policy_ref or os.environ.get("MEMORY_POLICY_REF") or (range_base(ctx, args.range) if args.range else None)
    if ref:
        ctx.use_policy_ref(ref)
    top, why = "L0", []
    for status, path in changed_files(ctx, staged=args.staged, rng=args.range):
        lvl = ctx.required_level(path)
        if lvl is None:
            continue
        eff = "L3" if lvl in FLOOR_KEEPS else lvl  # a derived or bot-only path is owner business
        if level_rank(eff) > level_rank(top):
            top, why = eff, [path]
        elif eff == top:
            why.append(path)
    if ctx.policy_changed():
        top = "L3"
        why = [ctx.policy_path] + why
    print(top)
    if not args.quiet:
        sys.stderr.write("memory-guard: highest level %s (%s)\n" % (top, ", ".join(why[:5]) or "no changes"))
    return EXIT_OK


def _codeowners_login(handle, p):
    login = (p.get("github") or "").strip().lstrip("@")
    if not login or "__todo" in login.lower():
        die("people.%s.github is %r: fill in the GitHub login before CODEOWNERS can name anyone"
            % (handle, login), EXIT_INVALID)
    return "@" + login


def codeowners_body(policy, prefix=""):
    """CODEOWNERS text for a policy.

    While `enforcement.auto_merge_levels` is empty (the containment default) every path needs an
    OWNER: one catch-all line. Once levels are allowed to merge on their own (e.g. ["L0"]), a
    catch-all would still demand a review for them, so instead each rule above those levels, plus
    the protected floor, names the people whose role reaches that level, and paths at an
    auto-merge level name nobody. Owners of the floor paths are always owners."""
    people = [(h, p) for h, p in policy.get("people", {}).items()
              if not h.startswith("$") and isinstance(p, dict)]
    owners = sorted(_codeowners_login(h, p) for h, p in people if p.get("role") == "owner")
    if not owners:
        die("no person has role owner", EXIT_INVALID)
    head = "# GENERATED by `memory_guard.py codeowners --write` from governance/roles.json. Do not edit.\n"
    base = "/" + prefix if prefix else "/"
    catch_all = (base + "**") if prefix else "*"
    auto = [l for l in (policy.get("enforcement") or {}).get("auto_merge_levels") or [] if l in LEVEL_ORDER]
    if not auto:
        return (head + "# Every path needs an owner's review: the containment rule after the 2026-09 audit.\n"
                "# Only enforced with branch protection on main requiring Code Owner review.\n"
                "%s    %s\n" % (catch_all, " ".join(owners)))
    ceiling = max(LEVEL_ORDER.index(l) for l in auto)
    roles = policy.get("roles", {})

    def reviewers(level):
        want = LEVEL_ORDER.index(level)
        out = set(owners)
        for h, p in people:
            ml = (roles.get(p.get("role")) or {}).get("max_level") if isinstance(roles.get(p.get("role")), dict) else None
            if p.get("role") not in ("agent", "reader", "contributor") and ml in LEVEL_ORDER and LEVEL_ORDER.index(ml) >= want:
                if (p.get("github") or "").strip():
                    out.add(_codeowners_login(h, p))
        return " ".join(sorted(out))

    # roles.json is FIRST match wins; CODEOWNERS is LAST match wins. So the rules are written in
    # reverse, and a rule at an auto-merge level gets an owner-less line (GitHub's "no owner"),
    # so a specific L0 folder inside a broader protected glob still merges on its own.
    lines, seen, unique = [], set(), []
    for r in (policy.get("paths") or {}).get("rules", []):   # the first rule for a glob is the one that applies
        glob = (r.get("glob") or "").strip().lstrip("/")
        if glob and glob not in seen:
            seen.add(glob)
            unique.append((glob, r.get("level")))
    for glob, lvl in reversed(unique):
        if lvl in ("bot", "derived"):
            who = " ".join(owners)
        elif lvl in LEVEL_ORDER and LEVEL_ORDER.index(lvl) > ceiling:
            who = reviewers(lvl)
        elif lvl in LEVEL_ORDER:
            who = ""
        else:
            continue
        lines.append(("%s%s    %s" % (base, glob, who)).rstrip())
    # the protected floor last, so no policy line can take an owner off it
    for glob, _lvl in PROTECTED_FLOOR:
        lines.append("%s%s    %s" % (base, glob, " ".join(owners)))
    return (head + "# enforcement.auto_merge_levels = %s: paths at those levels name no reviewer, so their pull\n"
            "# requests merge once memory-gate passes. Every other path names who must review it.\n"
            "# Written in reverse of roles.json because GitHub applies the LAST matching line; the\n"
            "# protected floor comes last.\n"
            % json.dumps(auto) + "\n".join(lines) + "\n")


CODEOWNERS_BEGIN = "# >>> cairn memory: generated by memory_guard.py codeowners, do not edit >>>"
CODEOWNERS_END = "# <<< cairn memory <<<"


def cmd_codeowners(ctx, args):
    """Generate .github/CODEOWNERS from roles.json (see codeowners_body). Refuses to write
    placeholders (audit 10-F2). The company tier owns the whole file. A project tier (memory/ inside
    a code repository) owns only a marked block of lines scoped to memory/, so the product's own
    code owners are never touched."""
    body = codeowners_body(ctx.policy, ctx.prefix)
    if ctx.prefix:
        body = "%s\n%s%s\n" % (CODEOWNERS_BEGIN, body, CODEOWNERS_END)
    owners = sorted({w for line in body.splitlines() if line and not line.startswith("#") for w in line.split()[1:]})
    if getattr(args, "print", False):
        sys.stdout.write(body)
        return EXIT_OK
    path = os.path.join(ctx.repo_root, ".github", "CODEOWNERS")
    current = read_text(path) if os.path.isfile(path) else ""
    if ctx.prefix:
        if CODEOWNERS_BEGIN in current and CODEOWNERS_END in current:
            i = current.index(CODEOWNERS_BEGIN)
            j = current.index(CODEOWNERS_END) + len(CODEOWNERS_END)
            have = current[i:j] + "\n"
            wanted = current[:i] + body + current[j:].lstrip("\n")
        else:
            have = ""
            wanted = (current.rstrip("\n") + "\n\n" if current.strip() else "") + body
    else:
        have, wanted = current, body
    if args.write:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_text(path, wanted)
        print("memory-guard: wrote %s.github/CODEOWNERS (%s)" % ("the memory block of " if ctx.prefix else "", " ".join(owners)))
        return EXIT_OK
    if have != body:
        sys.stderr.write("memory-guard: .github/CODEOWNERS does not match roles.json; run codeowners --write\n")
        return EXIT_INVALID
    print("memory-guard: CODEOWNERS matches roles.json")
    return EXIT_OK


def cmd_check(ctx, args):
    f = Findings()
    ref = getattr(args, "policy_ref", None) or os.environ.get("MEMORY_POLICY_REF")
    if not ref and args.range:
        ref = range_base(ctx, args.range)
    if ref:
        ctx.use_policy_ref(ref)
    base_ref = ref or ("HEAD" if git("-C", ctx.repo_root, "rev-parse", "--verify", "--quiet", "HEAD").strip() else None)
    files = changed_files(ctx, staged=args.staged, rng=args.range)
    if not files:
        if not args.quiet:
            print("memory-guard: nothing to check.")
        return EXIT_OK

    actor_max = ctx.effective_max_level()
    known_titles = repo_titles(ctx)
    id_home = {}
    for _st, npath in all_notes_as_changes(ctx):
        try:
            _fm, nbody = split_frontmatter(read_text(os.path.join(ctx.repo_root, npath)))
        except OSError:
            continue
        for (_i, _c, _t, cid, _s) in parse_claims(nbody):
            if cid:
                id_home.setdefault(cid, set()).add(npath)
    changed_set = {p for _st, p in files}
    for cid, homes in sorted(id_home.items()):
        if len(homes) > 1 and homes & changed_set:
            f.add("FAIL", "CLAIM-ID", sorted(homes & changed_set)[0],
                  "claim id ^%s is the id of claims in %d notes: %s" % (cid, len(homes), ", ".join(sorted(homes))),
                  "a claim may not END with a reference to another claim - write references earlier in "
                  "the line or in parentheses, e.g. `includes (^%s)`. `stamp` repairs it." % cid)
    strict_attr = not args.no_attribution

    if args.range and getattr(args, "no_access", False):
        pass  # CI: identity is per commit (checked per note below), review is enforced by CODEOWNERS
    elif ctx.actor_kind != "bot" and not usable_email(ctx.email):
        # A blank identity once matched a placeholder person with a blank email and passed
        # (audit 01-F6). No usable email means nobody can be attributed: block when attribution is on.
        f.add("FAIL" if strict_attr else "WARN", "IDENTITY", "-",
              "git user.email is %r, which identifies nobody" % (ctx.email or ""),
              "git config user.email <the address listed for you in governance/roles.json>")
    elif ctx.actor_kind == "human" and ctx.handle is None:
        f.add("WARN", "IDENTITY", "-",
              "git identity %r is not listed in governance/roles.json" % ctx.email,
              "add yourself to roles.json, or set git config user.email to the address listed there")
    if ctx.policy_changed():
        f.add("WARN", "POLICY", ctx.policy_path,
              "governance/roles.json changes in this commit; it is judged by the policy at %s and "
              "takes effect only after it lands" % ctx.policy_ref,
              "a path needs the level BOTH policies require while the policy is changing")

    for status, path in files:
        required = ctx.required_level(path)
        if required is None:
            continue  # outside this tier

        # --- level / role -------------------------------------------------
        if required == "derived":
            # A generated copy of an owner-approved file is not a new privilege — but an
            # ALTERED copy is an instruction injected into every agent. Allow it only while it
            # matches the canonical file byte for byte.
            rule = ctx.path_rule(path) or {}
            rel = path[len(ctx.prefix):] if ctx.prefix else path
            src_rel = rule.get("derived_from", "") + rel[len(rule.get("strip_prefix", "")):]
            src_abs = os.path.join(ctx.notes_root, src_rel)
            dst_abs = os.path.join(ctx.repo_root, path)
            same = False
            try:
                # bytes, not text: universal-newline reads hid a CR/LF swap (audit 01-F7)
                with open(src_abs, "rb") as a, open(dst_abs, "rb") as b:
                    same = a.read() == b.read()
            except OSError:
                same = False
            if not same:
                f.add("FAIL", "ACCESS-DERIVED", path,
                      "this is a generated copy of %s and no longer matches it" % src_rel,
                      "an altered copy is an instruction injected into every agent. Run "
                      "`sync-memory pre` to regenerate it, or change the canonical file — which "
                      "is L3 and needs an owner")
        elif required == "bot" and ctx.actor_kind != "bot":
            # The very first commit of a repository carries the generated files once; after that
            # only CI's bot writes them.
            f.add("WARN" if base_ref is None else "FAIL", "ACCESS-BOT", path, "this file is machine-generated",
                  "hand edits are overwritten by CI; change the generator instead")
        elif required == "bot":
            pass  # the bot writing its own generated file: the one writer this path allows
        elif getattr(args, "no_access", False):
            pass  # the level is enforced by required review (classify + CODEOWNERS), not by this job
        elif not level_allows(actor_max, required):
            reason = ctx.path_reason(path)
            allowed_roles = [
                r for r in ctx.policy["roles"]["order"]
                if r not in ("reader",) and level_allows(
                    (ctx.policy["roles"].get(r) or {}).get("max_level"), required)
            ]
            f.add("FAIL", "ACCESS-LEVEL", path,
                  "%s is %s (%s); you are acting as %s, capped at %s"
                  % (path, required, reason or "canon", ctx.role_name(), actor_max or "nothing"),
                  "write the change as a proposal instead: log/proposals/PROPOSAL - <what>.md, "
                  "stating the exact text you want promoted and why. %s can promote it."
                  % (" or ".join(allowed_roles) or "an owner"))
        elif required == "L1" and (ctx.person or {}).get("role") == "maintainer":
            if not ctx.maintains(ctx.project_name):
                f.add("FAIL", "ACCESS-PROJECT", path,
                      "you maintain %s, not %s"
                      % (", ".join((ctx.person or {}).get("projects", [])) or "no projects",
                         ctx.project_name),
                      "ask that project's maintainer to promote it")

        if status == "D":
            if is_runlog(ctx, path):
                f.add("FAIL", "PLAYBOOK-RUNS", path, "a run log was deleted",
                      "run logs are append-only; failed runs are the most useful warnings")
            continue
        abs_path = os.path.join(ctx.repo_root, path)
        if not os.path.isfile(abs_path):
            continue
        try:
            text = read_text(abs_path)
        except OSError:
            continue

        # --- safety, on every changed file --------------------------------
        scan_secrets(f, path, text)
        if is_note(ctx, path):
            scan_injection(ctx, f, path, text)
            rel = path[len(ctx.prefix):] if ctx.prefix else path
            if rel.startswith("templates/") or rel.startswith("log/CHANGELOG"):
                continue
            validate_note(ctx, f, path, text, known_titles, strict_attr)
            if strict_attr and not exists_at(ctx, base_ref, path):
                check_new_author(ctx, f, path, text, args.range)
            elif strict_attr and args.range:
                check_range_editor(ctx, f, path, text, args.range)
            if status == "A" and rel.startswith("log/journal/"):
                check_duplicate(ctx, f, path, text)
            if is_playbook(ctx, path):
                validate_playbook(ctx, f, path, text)
                check_playbook_approval(ctx, f, path, text, base_ref, args.range)
        elif is_runlog(ctx, path):
            check_runlog(ctx, f, path, base_ref, args.range)

    # --- write-back: code a feature covers changed, its note did not ------
    # This is what keeps the feature spine alive. Every wiki's component page rots the same way:
    # the code moves on and nobody updates the description. Here the commit that moves the code is
    # told, by name, which feature note it left behind.
    root = code_root(ctx)
    if root and os.path.abspath(root) == os.path.abspath(ctx.repo_root):
        touched = {p for st_, p in files if st_ != "D"}
        code_changes = [p for p in touched if not is_note(ctx, p)]
        for fpath, title, covers, fstatus in load_features(ctx):
            if fstatus == "retired" or not covers:
                continue
            hit = [p for p in code_changes if any(glob_match(g, p) for g in covers)]
            if hit and fpath not in touched:
                f.add("WARN", "WRITEBACK", fpath,
                      "%d file(s) covered by feature '%s' changed but its note did not: %s"
                      % (len(hit), title, ", ".join(sorted(hit)[:3])),
                      "update the card, the contract if a promise changed, or add a claim - "
                      "the next agent will read this note to understand that code")

    code = f.worst_exit(args.warn_only)
    if f.items:
        sys.stderr.write("\nmemory-guard: %s\n" % ("advisory findings" if args.warn_only else "policy check"))
        f.report(args.warn_only)
    elif not args.quiet:
        print("memory-guard: %d file(s) checked, clean (acting as %s, max level %s)."
              % (len(files), ctx.role_name(), actor_max))
    return code


def cmd_cascade(ctx, args):
    """A planning change ripples: stamp every note related to it as needing review."""
    cfg = ctx.policy.get("cascade", {})
    if not cfg.get("enabled", True):
        print("memory-guard: cascade disabled in roles.json")
        return EXIT_OK

    files = changed_files(ctx, staged=args.staged, rng=args.range)
    seeds = []
    for status, path in files:
        if status == "D" or not is_note(ctx, path):
            continue
        lvl = ctx.path_level(path)
        if lvl in ("L1", "L2", "L3"):
            abs_path = os.path.join(ctx.repo_root, path)
            if os.path.isfile(abs_path):
                fm, _ = split_frontmatter(read_text(abs_path))
                t = fm_get(fm, "title") if fm else None
                if t:
                    seeds.append((t.strip(), path, lvl))
    if not seeds:
        if not args.quiet:
            print("memory-guard: no L1/L2/L3 change in this set — nothing cascades.")
        return EXIT_OK

    # Build reverse index: title -> notes that link to it.
    back = {}
    all_notes = []
    for d in NOTE_DIRS:
        for dirpath, _dn, filenames in os.walk(os.path.join(ctx.notes_root, d)):
            for fn in filenames:
                if fn.endswith(".md"):
                    all_notes.append(os.path.join(dirpath, fn))
    follow = set(cfg.get("relation_types_followed", []))
    for note in all_notes:
        try:
            text = read_text(note)
        except OSError:
            continue
        for m in re.finditer(r"^\s*-\s+(\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)?\s*\[\[([^\]]+)\]\]",
                             strip_code(text), re.M):
            rtype = (m.group(1) or "links_to").strip('"')
            if follow and rtype not in follow:
                continue  # `relates_to` is "see also", not a dependency: see roles.json
            back.setdefault(m.group(2).strip(), set()).add((note, rtype))

    sha = git("-C", ctx.repo_root, "rev-parse", "--short", "HEAD").strip() or "working-tree"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    depth = int(cfg.get("depth", 2))
    field = cfg.get("stamp_field", "review_needed")

    affected, frontier, seen = {}, {t: (p, l) for t, p, l in seeds}, set(t for t, _, _ in seeds)
    for _ in range(depth):
        nxt = {}
        for title, (src_path, lvl) in frontier.items():
            for note, rtype in back.get(title, ()):  # notes pointing AT the changed note
                rel = os.path.relpath(note, ctx.repo_root).replace(os.sep, "/")
                if rel in {p for _t, p, _l in seeds} or rel in affected:
                    continue
                affected[rel] = (title, src_path, lvl, rtype)
                try:
                    fm, _ = split_frontmatter(read_text(note))
                    t2 = fm_get(fm, "title") if fm else None
                except OSError:
                    t2 = None
                if t2 and t2 not in seen:
                    seen.add(t2)
                    nxt[t2.strip()] = (src_path, lvl)
        frontier = nxt
        if not frontier:
            break

    if not affected:
        print("memory-guard: %d changed note(s) at L1+, nothing depends on them yet." % len(seeds))
        return EXIT_OK

    cap = int(cfg.get("max_stamped", 8))
    print("memory-guard: cascade from %s" % ", ".join(p for _t, p, _l in seeds))
    for rel, (title, src, lvl, rtype) in sorted(affected.items()):
        print("  %-52s %s [[%s]]" % (rel, rtype, title))
    if len(affected) > cap:
        print("\n  %d notes depend on this change, over the cap of %d. Nothing was stamped."
              % (len(affected), cap))
        print("  A change this central is not a note-by-note review: decide what it invalidates,")
        print("  then either narrow the change or stamp the specific notes by hand.")
        return EXIT_OK
    for rel, (title, src, lvl, rtype) in sorted(affected.items()):
        if args.apply:
            abs_path = os.path.join(ctx.repo_root, rel)
            text = read_text(abs_path)
            fm, body = split_frontmatter(text)
            if fm is None:
                continue
            stamp = '"%s @ %s (%s) via %s"' % (src, sha, today, rtype)
            new = render(fm_set(fm, field, stamp), body)
            if new != text:
                write_text(abs_path, new)
    if args.apply:
        print("  stamped %s on %d note(s)." % (field, len(affected)))
    else:
        print("  (dry run — pass --apply to stamp %s)" % field)
    return EXIT_OK


# --- significance detector ---------------------------------------------------

SIGNIFICANCE_PATHS = [
    "**/package.json", "**/pyproject.toml", "**/requirements*.txt", "**/go.mod", "**/Cargo.toml",
    "**/Dockerfile", "**/docker-compose*.yml", ".github/workflows/**", "**/*.tf",
    "**/*.proto", "**/.mcp.json", "**/settings.json", "**/ADR-*.md", "**/CLAUDE.md",
    "**/docs/adr/**", "**/RFC-*.md", "**/*ARCHITECTURE*.md", "**/*DECISION*.md",
]
DECISION_LANGUAGE = [
    r"(?i)\bwe (decided|chose|settled on|agreed)\b",
    r"(?i)\b(switch(ed|ing)? (to|from)|replac(ed|ing) .{1,40} with|migrat(ed|ing) (to|off))\b",
    r"(?i)\b(instead of|rather than) (using|doing)\b",
    r"(?i)\broot cause\b",
    r"(?i)\bturns out\b|\bit turned out\b",
    r"(?i)\b(won'?t|will not|does ?n'?t) work because\b",
    r"(?i)\bdeprecat(ed|ing)\b|\bsupersed(ed|es)\b",
    r"(?i)\bnow owns\b|\bhanded over to\b|\btook over\b",
    r"(?i)\bthe (real|actual) (problem|cause|behaviour|behavior) (is|was)\b",
    r"(?i)\bgotcha\b|\bcaveat\b|\bfoot-?gun\b",
]


def cmd_significance(ctx, args):
    """Stop-hook detector. Deterministic and free: no model call, no token cost."""
    raw = ""
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
        except Exception:
            raw = ""
    try:
        hook = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        hook = {}

    # Never loop: if we already blocked once this turn, let the agent stop.
    if hook.get("stop_hook_active"):
        return EXIT_OK
    session = str(hook.get("session_id") or os.environ.get("MEMORY_SESSION_ID") or "nosession")
    marker = os.path.join(
        git("-C", ctx.repo_root, "rev-parse", "--git-dir").strip() or ".git",
        "memory-significance-%s" % re.sub(r"[^A-Za-z0-9_.-]", "_", session)[:64],
    )
    if not os.path.isabs(marker):
        marker = os.path.join(ctx.repo_root, marker)
    playbook_offer = playbook_suggestion(ctx, hook, marker + "-playbook")
    if os.path.exists(marker):
        return emit_significance(args, playbook_offer) if playbook_offer else EXIT_OK

    # Did the agent already record something? Then we are done.
    wrote_memory = False
    for _s, p in changed_files(ctx, staged=False):
        rel = p[len(ctx.prefix):] if ctx.prefix and p.startswith(ctx.prefix) else p
        if rel.startswith("log/journal/") or rel.startswith("log/proposals/") or rel.startswith("projects/"):
            wrote_memory = True
            break
    if wrote_memory:
        return emit_significance(args, playbook_offer) if playbook_offer else EXIT_OK

    # Markers in the working tree of the repo the agent is actually working in.
    work_repo = hook.get("cwd") or ctx.repo_root
    # -uall, not the default: plain --porcelain collapses an untracked directory to "?? dir/",
    # so otherwise no file marker below would ever match an untracked file.
    porcelain = git("-C", work_repo, "status", "--porcelain", "--untracked-files=all")
    work_files = [ln[3:].strip() for ln in porcelain.splitlines() if ln.strip()]
    reasons = []
    hits = [p for p in work_files if any(glob_match(g, p) for g in SIGNIFICANCE_PATHS)]
    if hits:
        reasons.append("changed files that usually encode a decision: " + ", ".join(hits[:4]))
    if len(work_files) >= 8:
        reasons.append("%d files changed in this session" % len(work_files))

    msg = hook.get("last_assistant_message") or ""
    for pat in DECISION_LANGUAGE:
        m = re.search(pat, msg)
        if m:
            reasons.append("your closing message states a conclusion (%r)" % m.group(0)[:40])
            break

    if not reasons:
        return emit_significance(args, playbook_offer) if playbook_offer else EXIT_OK

    try:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(datetime.now(timezone.utc).isoformat())
    except OSError:
        pass

    reason = (
        "Memory check before you stop. This turn shows a durable change: "
        + "; ".join(reasons)
        + ". Apply governance/SIGNIFICANCE.md: if a teammate would decide worse in a month "
        "without it, record it now, then stop.\n"
        "  - A code-level fact, gotcha, corrected assumption or dead end -> write_note(project=\"%s\", "
        "directory=\"log/journal\", title=\"YYYY-MM-DD <slug>\"), <=80 lines, at least one relation.\n"
        "  - A decision, plan or architecture change -> you may NOT edit context/ or decisions/. "
        "Write log/proposals/\"PROPOSAL - <what>\" with the exact text you want promoted and why.\n"
        "  - Nothing durable (progress narration, anything re-derivable from the diff) -> say "
        "'nothing durable to store' and stop. That is a valid answer and often the right one."
    ) % ctx.project_name
    return emit_significance(args, reason + (("\n" + playbook_offer) if playbook_offer else ""))


def emit_significance(args, reason):
    fmt = getattr(args, "format", "claude")
    if fmt == "claude":
        # Claude Code reads a JSON decision on stdout; `block` feeds `reason` back to the agent
        # as its next instruction, so it writes the note and then stops.
        print(json.dumps({"decision": "block", "reason": reason}))
    else:
        # Kiro cannot block a Stop, but stdout from an exit-0 command hook is added to the
        # agent's context, so the same text arrives as a nudge rather than an instruction.
        print(reason)
    return EXIT_OK


PLAYBOOK_SHELL_STEPS = 8
SHELL_TOOL_RX = re.compile(r'"name"\s*:\s*"(Bash|PowerShell|shell|run_terminal_cmd|executeBash)"')


def playbook_suggestion(ctx, hook, marker):
    """Once per session, after a turn that ran many shell commands and saved no playbook: tell the
    agent to OFFER /playbook-save to the person. It counts tool calls in the host's transcript file;
    nothing from the transcript is read beyond that count or kept."""
    if os.path.exists(marker):
        return None
    path = hook.get("transcript_path") or ""
    n = 0
    try:
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    n += len(SHELL_TOOL_RX.findall(line))
    except OSError:
        return None
    if n < PLAYBOOK_SHELL_STEPS:
        return None
    for _s, p in changed_files(ctx, staged=False):
        rel = p[len(ctx.prefix):] if ctx.prefix and p.startswith(ctx.prefix) else p
        if rel.startswith("playbooks/"):
            return None
    try:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(datetime.now(timezone.utc).isoformat())
    except OSError:
        pass
    return ("This session ran %d shell commands. If it was a multi-step setup or task someone else will "
            "repeat, ask the person once: \"Save this as a playbook so a teammate's AI can walk them "
            "through it? (/playbook-save)\". Do not save it without their yes; if they decline, stop." % n)


def cmd_explain(ctx, args):
    handle = args.actor or ctx.handle
    person = (ctx.policy.get("people", {}) or {}).get(handle) if handle else None
    role = (person or {}).get("role", "unregistered")
    roles = ctx.policy.get("roles", {})
    print("actor        : %s (%s)" % (handle or "<unregistered>", (person or {}).get("email", ctx.email)))
    print("role         : %s" % role)
    print("acting as    : %s" % ctx.actor_kind)
    print("max level    : %s   (as a human committing directly)" % (roles.get(role) or {}).get("max_level"))
    print("             : %s   (when driving an AI agent)" % (roles.get("agent") or {}).get("max_level"))
    if (person or {}).get("projects"):
        print("projects     : %s" % ", ".join(person["projects"]))
    print("\nlevel       may change")
    for lvl in LEVEL_ORDER:
        info = ctx.policy["levels"][lvl]
        ok_h = level_allows((roles.get(role) or {}).get("max_level"), lvl)
        ok_a = level_allows((roles.get("agent") or {}).get("max_level"), lvl)
        print("  %-3s %-22s human:%-3s agent:%-3s  %s"
              % (lvl, info["label"], "yes" if ok_h else "no", "yes" if ok_a else "no",
                 ", ".join(info["paths"][:2])))
    print("\npaths in this tier:")
    for rule in ctx.policy["paths"]["rules"]:
        print("  %-26s %-4s %s" % (rule["glob"], rule["level"], rule.get("reason", "")))
    return EXIT_OK


def cmd_audit(ctx, args):
    since = args.since or "30d"
    m = re.match(r"^(\d+)([dwmy])$", since)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * {"d": 1, "w": 7, "m": 30, "y": 365}[unit]
        since_arg = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    else:
        since_arg = since
    pathspec = [args.path] if args.path else [p for p in (ctx.prefix or ".",)]
    fmt = "%H%x01%an%x01%ae%x01%ad%x01%s%x01%b"
    out = git("-C", ctx.repo_root, "log", "--since", since_arg, "--date=format:%Y-%m-%d %H:%M",
              "--pretty=format:" + fmt, "--name-only", "--", *pathspec)
    # Each commit begins with a \x01-delimited header line, then its file list.
    rows = []
    cur = None
    for line in out.splitlines():
        if "\x01" in line:
            parts = line.split("\x01")
            if len(parts) >= 5:
                cur = {"sha": parts[0][:8], "an": parts[1], "ae": parts[2], "date": parts[3],
                       "subject": parts[4], "body": parts[5] if len(parts) > 5 else "", "files": []}
                rows.append(cur)
                continue
        if cur is not None and line.strip():
            if line.startswith("Sync-"):
                cur["body"] += " " + line
            else:
                cur["files"].append(line.strip())
    if not rows:
        print("no memory changes since %s" % since_arg)
        return EXIT_OK

    print("%-9s %-16s %-26s %-4s %-5s %s" % ("commit", "when", "who", "lvl", "files", "what"))
    print("-" * 104)
    for r in rows:
        if not r["files"]:
            continue
        # `bot` and `derived` are not levels: a commit that touches one must still be reported
        # at the highest REAL level it contains, or a governance change hides behind a copy.
        levels = [ctx.path_level(p) for p in r["files"]]
        real = [l for l in levels if l in LEVEL_ORDER]
        top = max(real, key=level_rank) if real else (levels[0] if levels else "-")
        agent = ""
        ma = re.search(r"Sync-Agent:\s*(\S+)", r["body"])
        if ma and ma.group(1) not in ("unknown", None):
            agent = "/" + ma.group(1)
        actor = ""
        mk = re.search(r"Sync-Actor:\s*(\S+)", r["body"])
        if mk and mk.group(1) == "agent":
            actor = " (agent%s)" % agent
        who = (r["an"] + actor)
        who = who if len(who) <= 26 else who[:25] + "\u2026"
        print("%-9s %-16s %-26s %-4s %-5d %s"
              % (r["sha"], r["date"], who, top, len(r["files"]), r["subject"][:40]))
        if args.verbose:
            for p in r["files"]:
                print("%39s %-4s %s" % ("", ctx.path_level(p) or "-", p))
    print("\n%d commit(s) since %s. Levels: L0 observation, L1 project planning, L2 strategy, L3 governance."
          % (len([r for r in rows if r["files"]]), since_arg))
    return EXIT_OK


# --------------------------------------------------------------------------- main


def main(argv):
    ap = argparse.ArgumentParser(prog="memory_guard.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notes-root", help="override discovery of the memory root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stamp", help="write attribution/level into changed notes from git identity")
    p.add_argument("--staged", action="store_true", default=True)
    p.add_argument("--worktree", dest="staged", action="store_false")
    p.add_argument("--all", action="store_true", help="one-time backfill over every note in the tier")

    p = sub.add_parser("check", help="enforce level, role, quality and safety")
    p.add_argument("--staged", action="store_true")
    p.add_argument("--range", help="commit range, for CI (e.g. origin/main...HEAD)")
    p.add_argument("--warn-only", action="store_true", help="report but never block")
    p.add_argument("--no-attribution", action="store_true", help="skip the author/identity check")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--policy-ref", help="judge with roles.json as of this ref (default: HEAD, or the "
                                        "range's merge base)")
    p.add_argument("--no-access", action="store_true",
                   help="CI only: skip the actor's level cap (review enforces it); bot-only and derived "
                        "paths, safety, format and per-commit attribution are still checked")

    p = sub.add_parser("classify", help="print the highest level a change needs (trusted policy + floor)")
    p.add_argument("--staged", action="store_true")
    p.add_argument("--range")
    p.add_argument("--policy-ref")
    p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("codeowners", help="generate or check .github/CODEOWNERS from roles.json")
    p.add_argument("--write", action="store_true")
    p.add_argument("--print", action="store_true", help="print what --write would write, change nothing")

    p = sub.add_parser("cascade", help="stamp review_needed on notes that depend on a changed plan")
    p.add_argument("--staged", action="store_true")
    p.add_argument("--range")
    p.add_argument("--apply", action="store_true", help="write the stamps (default is a dry run)")
    p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("significance", help="Stop-hook detector; reads hook JSON on stdin")
    p.add_argument("--format", choices=["claude", "text"], default="claude",
                   help="claude: JSON decision (Claude Code). text: plain stdout (Kiro, others)")

    p = sub.add_parser("explain", help="print what an actor may change")
    p.add_argument("--actor", help="handle from governance/roles.json")

    p = sub.add_parser("audit", help="who changed what, when")
    p.add_argument("--since", default="30d")
    p.add_argument("--path")
    p.add_argument("--verbose", action="store_true")

    args = ap.parse_args(argv)
    try:
        ctx = Ctx(args.notes_root)
    except SystemExit:
        raise
    except Exception as e:  # pragma: no cover - defensive
        die("could not establish context: %s" % e, EXIT_INTERNAL)

    return {
        "stamp": cmd_stamp, "check": cmd_check, "cascade": cmd_cascade, "classify": cmd_classify,
        "codeowners": cmd_codeowners,
        "significance": cmd_significance, "explain": cmd_explain, "audit": cmd_audit,
    }[args.cmd](ctx, args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
