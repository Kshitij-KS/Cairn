# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
mem.py - how agents and people read, steer and experiment with the shared memory (ADR-003, ADR-004).

READ (the entry protocol)
    mem load [<ask>] [--mode M] [--feature T ...] [--touching PATH ...] [--ref REF]
                                       core -> resolve -> directional scope -> receipt -> bundle
    mem resolve <ask> [--touching PATH ...]        which feature(s) an ask is about
    mem recall <query> [--limit N] [--ideas]       ranked claims, each with a reason
    mem context                                    the current session's receipt
    mem moved [--fetch] [--quiet]                  did anything I loaded change upstream?
    mem session start|evict|show                   ledger lifecycle (hooks call these)
    mem compile                                    write the claim pack to .memory/pack/

WRITE
    mem remember <claim> [--category C] [--feature T | --note PATH]
    mem retire ^id [--by ^id]
    mem gap <what is missing> [--feature T]        mem gaps
    mem feature new <name> [--covers G ...] [--owner H] [--depends T ...] [--status S]
    mem features
    mem propose <title> --target PATH --text TEXT [--why W]
    mem approve <proposal> [--apply]

STEER
    mem pin|unpin|mute|unmute <^id | note title>   personal; team-wide pins belong in CORE.md
    mem why ^id                                    provenance of one claim

EXPERIMENT
    mem try <hypothesis> [--for H ...] [--days N] [--change LINE ...] [--evals NAME ...]
    mem trials                                     live trials, expiry, overlaps
    mem keep <slug>     mem drop <slug> --result R     mem expire
    mem eval [--trial SLUG] [--file PATH]          deterministic retrieval + resolution tests
    mem diff [--since REF] [--to REF]              what the team BELIEVES changed, claim by claim

AWARE / GOVERN
    mem status    mem brief    mem who    mem can <handle> <path>    mem role <handle> <role>
    mem core init

Standard library only. Shares every parser with memory_guard.py by importing it, so the reader and
the enforcer cannot drift. Everything local lives in .memory/ beside the notes, which is gitignored.

Exit codes: 0 ok · 2 ambiguous (ask the person one question) · 4 not permitted · 5 invalid input ·
1 a test or check failed.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # importing memory_guard must not leave __pycache__/ in a notes repo


def _load_guard():
    spec = importlib.util.spec_from_file_location("memory_guard", os.path.join(HERE, "memory_guard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mg = _load_guard()

EXIT_OK, EXIT_FAIL, EXIT_AMBIGUOUS, EXIT_DENIED, EXIT_INVALID = 0, 1, 2, 4, 5
DEP_TYPES_DEFAULT = ("depends_on", "implements", "part_of", "supersedes")
MODES = ("orient", "build", "change", "debug", "review", "plan", "explain")
DEPTH_RANK = {"title": 0, "card": 1, "full": 2}
STOP = set("""a an and are as at be but by can do does for from how i if in into is it its of on or
our so that the their them then there these this to up us was we what when where which who why will
with would you your should could all any some make get need want please just""".split())
TODAY = datetime.now(timezone.utc).date()


def today():
    return TODAY.isoformat()


def die(msg, code=EXIT_INVALID):
    sys.stderr.write("mem: %s\n" % msg)
    sys.exit(code)


def words(text):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_.\-]*", (text or "").lower())
            if len(w) >= 3 and w not in STOP]


def slugify(text, n=6):
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return "-".join(toks[:n]) or "note"


def sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def parse_date(s):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------- local state

MAX_SESSION_ID = 200
LEDGER_VERSION = 2
RETENTION_DAYS = 14


class SessionIdError(ValueError):
    pass


def check_session_id(sid):
    """A bounded, printable string. Lossy sanitising let `a/b` and `a?b` share one ledger, and a
    newline in a hook's id printed a forged line into the agent's context (audit 04-F5)."""
    if not isinstance(sid, str) or not sid or len(sid) > MAX_SESSION_ID:
        raise SessionIdError("session id must be a string of 1-%d characters" % MAX_SESSION_ID)
    if any(ord(c) < 32 or ord(c) == 127 for c in sid):
        raise SessionIdError("session id contains control characters")
    return sid


def session_key(sid):
    """Filesystem name for a session: readable prefix + hash of the EXACT id, so distinct ids never
    collide and no id can name a device or leave the folder."""
    prefix = re.sub(r"[^A-Za-z0-9_-]", "_", sid)[:24]
    return "%s-%s" % (prefix, hashlib.sha256(sid.encode("utf-8")).hexdigest()[:16])


def valid_ledger(led):
    return (isinstance(led, dict) and isinstance(led.get("loaded"), dict) and isinstance(led.get("turn"), int)
            and all(isinstance(v, dict) and isinstance(v.get("hash"), str) and v.get("depth") in DEPTH_RANK
                    for v in led["loaded"].values()))


class Local:
    """Everything this machine keeps: cache, bundles, ledgers, logs, prefs. Never committed.

    Concurrency (audit 04-F1/F2/F7): every write goes to a unique temporary file and is atomically
    renamed; a session's ledger is read-modified-written under a per-session lock; bundles are
    content-addressed so one session can never overwrite another's; the ledger is written LAST, so a
    failed load does not mark notes as already delivered."""

    def __init__(self, notes_root):
        self.root = os.path.join(notes_root, ".memory")
        for d in ("cache", "bundles", "session", "logs", "pack"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def read_json(self, rel, default):
        try:
            with open(self.path(rel), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    def write_bytes(self, abspath, data):
        tmp = "%s.%d.%s.tmp" % (abspath, os.getpid(), os.urandom(4).hex())
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(40):
            try:
                os.replace(tmp, abspath)
                return
            except PermissionError:  # Windows: another process has the target open for a moment
                time.sleep(0.05)
        os.remove(tmp)
        raise OSError("could not replace %s (in use)" % abspath)

    def write_json(self, rel, data):
        self.write_bytes(self.path(rel), json.dumps(data, indent=1, sort_keys=True).encode("utf-8"))

    def prefs(self):
        return self.read_json("prefs.json", {"pins": [], "mutes": []})

    def salt(self):
        p = self.path("salt")
        if not os.path.isfile(p):
            self.write_bytes(p, os.urandom(16).hex().encode("ascii"))
        with open(p) as fh:
            return fh.read().strip()

    def session_id(self, explicit=None):
        sid = explicit or os.environ.get("MEMORY_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID")
        # (CLAUDE_CODE_SESSION_ID: Claude Code exports it to Bash tool commands; hooks receive the same
        # id on stdin, so `load` and `session evict` agree even with two sessions in one checkout.)
        if not sid:
            try:
                with open(self.path("session", "current"), encoding="utf-8") as fh:
                    sid = fh.read().strip()
            except (OSError, UnicodeDecodeError):
                sid = ""
        sid = sid or "default"
        try:
            return check_session_id(sid)
        except SessionIdError as e:
            die("%s" % e, EXIT_INVALID)

    def _ledger_path(self, sid):
        return self.path("session", session_key(sid) + ".json")

    def ledger(self, sid):
        p = self._ledger_path(sid)
        if not os.path.exists(p):
            return None
        led = self.read_json(os.path.relpath(p, self.root), None)
        if led is not None and valid_ledger(led):
            return led
        # Quarantine, warn once, rebuild: a wrong-shaped ledger used to crash load, moved and evict
        # with tracebacks (audit 04-F8).
        bad = "%s.corrupt-%d" % (p, int(time.time()))
        try:
            os.replace(p, bad)
        except OSError:
            pass
        sys.stderr.write("mem: the session record was damaged; kept it as %s and started a fresh one\n"
                         % os.path.basename(bad))
        return None

    def save_ledger(self, sid, data):
        data["version"] = LEDGER_VERSION
        self.write_json(os.path.relpath(self._ledger_path(sid), self.root), data)

    def receipt_path(self, sid):
        return self.path("session", session_key(sid) + ".receipt.json")

    def lock(self, sid, timeout=15.0):
        return _FileLock(self.path("session", session_key(sid) + ".lock"), timeout)

    def purge(self, older_than_days=None):
        """Delete cached note blocks and bundles (all, or those untouched for N days). They are plain
        copies of note text, so retention is bounded (audit 04-F9)."""
        n, cutoff = 0, (time.time() - older_than_days * 86400) if older_than_days else None
        for d in ("cache", "bundles"):
            for fn in os.listdir(self.path(d)):
                fp = self.path(d, fn)
                try:
                    if cutoff is None or os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                        n += 1
                except OSError:
                    pass
        return n


class _FileLock:
    """Cross-platform exclusive lock: O_CREAT|O_EXCL on a lock file, stale after 60 s."""

    def __init__(self, path, timeout):
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, ("%d" % os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > 60:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                if time.time() > deadline:
                    die("another mem command holds the session lock (%s); try again" % self.path, 1)
                time.sleep(0.02)

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False


CACHE_MAGIC = "<!-- mem-cache v1 "


def cache_read(path, note_hash, depth):
    """A cached block is used only if its envelope names this exact note version and depth and its
    digest matches its bytes. A tampered or truncated cache file used to be served as context
    (audit 04-F4)."""
    try:
        with open(path, encoding="utf-8") as fh:
            head = fh.readline()
            block = fh.read()
    except (OSError, UnicodeDecodeError):
        return None
    m = re.match(r"^<!-- mem-cache v1 ([0-9a-f]+) (\w+) ([0-9a-f]{64}) -->\n$", head)
    if not m or m.group(1) != note_hash or m.group(2) != depth:
        return None
    if hashlib.sha256(block.encode("utf-8")).hexdigest() != m.group(3):
        return None
    return block


def cache_write(local, path, note_hash, depth, block):
    head = "%s%s %s %s -->\n" % (CACHE_MAGIC, note_hash, depth, hashlib.sha256(block.encode("utf-8")).hexdigest())
    local.write_bytes(path, (head + block).encode("utf-8"))


# --------------------------------------------------------------------------- refs

def resolve_ref(ctx, ref):
    """A context ref: `<branch>@HEAD` (the working tree), a past commit or date, or a trial."""
    proto = ctx.policy.get("protocol", {})
    ref = (ref or proto.get("default_ref") or "main@HEAD").strip()
    branch = mg.git("-C", ctx.repo_root, "rev-parse", "--abbrev-ref", "HEAD").strip() or "main"
    head = mg.git("-C", ctx.repo_root, "rev-parse", "--short", "HEAD").strip() or "uncommitted"
    if ref.startswith("trial/"):
        return {"label": ref, "sha": None, "trial": ref[len("trial/"):], "short": head}
    spec = ref.split("@", 1)[1] if "@" in ref else ref
    if spec in ("", "HEAD", "worktree", "latest"):
        return {"label": "%s@%s" % (branch, head), "sha": None, "trial": None, "short": head}
    if re.match(r"^\d{4}-\d{2}-\d{2}$", spec):
        full = mg.git("-C", ctx.repo_root, "rev-list", "-1", "--before=%s 23:59:59" % spec, "HEAD").strip()
        if not full:
            die("no commit exists on or before %s" % spec)
    else:
        full = mg.git("-C", ctx.repo_root, "rev-parse", "--verify", "--quiet", spec + "^{commit}").strip()
        if not full:
            die("unknown ref %r - use <branch>@HEAD, a commit, a date YYYY-MM-DD, or trial/<slug>" % ref)
    return {"label": "%s@%s" % (branch, full[:7]), "sha": full, "trial": None, "short": full[:7],
            "past": True}


# --------------------------------------------------------------------------- notes

def brief_of(body):
    for block in re.split(r"\n\s*\n", mg.strip_code(body or "")):
        b = block.strip()
        if not b or b[0] in "#-|>*" or b.startswith("<!--"):
            continue
        flat = re.sub(r"\s+", " ", re.sub(r"<!--.*?-->|`|\*|\[\[|\]\]", "", b, flags=re.S)).strip()
        if not flat:
            continue
        m = re.match(r"^(.{30,200}?[.!?])(\s|$)", flat)
        return (m.group(1) if m else flat[:200]).strip()
    return ""


def relations_of(body):
    out = []
    for m in re.finditer(r"^\s*-\s+(\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)?\s*\[\[([^\]]+)\]\]",
                         mg.strip_code(body or ""), re.M):
        rtype = (m.group(1) or "links_to").strip('"')
        target = m.group(2).strip()
        if not target.startswith(("<", "__")):
            out.append((rtype, target))
    return out


def parse_note(nid, rel, text):
    fm, body = mg.split_frontmatter(text)
    fm = fm or []
    title = (mg.fm_get(fm, "title") or os.path.basename(nid)).strip()
    secs = mg.note_sections(body)
    ntype = (mg.fm_get(fm, "type") or "note").strip()
    if rel.startswith("features/"):
        ntype = "feature"
    card = secs.get("card") if ntype == "feature" else None
    claims = []
    for (i, cat, ctext, cid, sec) in mg.parse_claims(body):
        claims.append({"id": cid, "category": cat, "text": ctext, "section": sec,
                       "retired": sec == "retired", "line": i})
    return {
        "id": nid, "path": rel, "title": title, "type": ntype, "text": text, "body": body,
        "hash": sha(text), "level": mg.fm_get(fm, "level"), "status": mg.fm_get(fm, "status"),
        "owner": mg.fm_get(fm, "owner"), "author": mg.fm_get(fm, "author"),
        "updated": mg.fm_get(fm, "updated") or mg.fm_get(fm, "created"),
        "confidentiality": (mg.fm_get(fm, "confidentiality") or "internal").strip(),
        "covers": mg.fm_list(fm, "covers"), "aliases": mg.fm_list(fm, "aliases"),
        "tags": mg.fm_list(fm, "tags"), "for": mg.fm_list(fm, "for"),
        "hypothesis": mg.fm_get(fm, "hypothesis"), "expires": mg.fm_get(fm, "expires"),
        "card": card if card is not None else brief_of(body),
        "contract": secs.get("contract"), "contract_hash": sha(secs.get("contract") or ""),
        "sections": secs, "claims": claims, "relations": relations_of(body),
    }


def is_corpus_note(ctx, rel):
    """rel is notes-root-relative. Scaffolding and the machine-written changelog are not memory."""
    if not rel.endswith(".md") or rel.startswith((".", "templates/")) or rel == "log/CHANGELOG.md":
        return False
    return mg.is_note(ctx, (ctx.prefix + rel) if ctx.prefix else rel)


class Corpus:
    """Every note at one ref, parsed, with the dependency graph in both directions."""

    def __init__(self, ctx, ref_info, overlay=None):
        self.ctx, self.ref = ctx, ref_info
        self.notes = OrderedDict()
        for rel, text in self._read_all():
            nid = rel[:-3]
            self.notes[nid] = parse_note(nid, rel, text)
        self.trial_applied = None
        self._index()
        if overlay:
            self.apply_trial(overlay)
            self._index()

    def _read_all(self):
        ctx, sha_ = self.ctx, self.ref.get("sha")
        if sha_:
            listing = mg.git("-C", ctx.repo_root, "ls-tree", "-r", "--name-only", sha_,
                             "--", ctx.prefix or ".").splitlines()
            for repo_rel in sorted(listing):
                rel = repo_rel[len(ctx.prefix):] if ctx.prefix else repo_rel
                if is_corpus_note(ctx, rel):
                    yield rel, mg.git("-C", ctx.repo_root, "show", "%s:%s" % (sha_, repo_rel))
            return
        found = []
        for fn in os.listdir(ctx.notes_root):
            if fn.endswith(".md") and os.path.isfile(os.path.join(ctx.notes_root, fn)):
                found.append(fn)
        for d in mg.NOTE_DIRS:
            for dirpath, _dn, fns in os.walk(os.path.join(ctx.notes_root, d)):
                for fn in fns:
                    rel = os.path.relpath(os.path.join(dirpath, fn), ctx.notes_root).replace(os.sep, "/")
                    found.append(rel)
        for rel in sorted(set(found)):
            if is_corpus_note(ctx, rel):
                yield rel, mg.read_text(os.path.join(ctx.notes_root, rel))

    def _index(self):
        self.by_title = {n["title"].lower(): nid for nid, n in self.notes.items()}
        dep = set(self.ctx.policy.get("cascade", {}).get("relation_types_followed", DEP_TYPES_DEFAULT))
        self.up = {nid: [] for nid in self.notes}
        self.down = {nid: [] for nid in self.notes}
        self.links = {nid: [] for nid in self.notes}
        self.edges, self.unresolved = [], []
        for nid, n in self.notes.items():
            for rtype, target in n["relations"]:
                tid = self.by_title.get(target.lower())
                if tid is None:
                    self.unresolved.append((nid, target))
                    continue
                if tid == nid:
                    continue
                self.edges.append((nid, tid, rtype, rtype in dep))
                self.links[nid].append(tid)
                self.links[tid].append(nid)
                if rtype in dep:
                    self.up[nid].append(tid)      # nid relies on tid
                    self.down[tid].append(nid)    # tid breaks nid if it changes
        self.claims = {}
        for nid, n in self.notes.items():
            for c in n["claims"]:
                if c["id"]:
                    self.claims[c["id"]] = (nid, c)

    def features(self, include_retired=False):
        return [n for n in self.notes.values() if n["type"] == "feature"
                and (include_retired or (n["status"] or "") != "retired")]

    def find(self, name):
        """A note by id, path, title or claim id."""
        if not name:
            return None
        name = name.strip()
        if name in self.notes:
            return self.notes[name]
        if name.endswith(".md") and name[:-3] in self.notes:
            return self.notes[name[:-3]]
        tid = self.by_title.get(name.lower())
        if tid:
            return self.notes[tid]
        cid = name.lstrip("^")
        if cid in self.claims:
            return self.notes[self.claims[cid][0]]
        return None

    def hops(self, seeds, direction, depth):
        adj = self.up if direction == "up" else self.down
        seen, frontier, out = set(seeds), list(seeds), []
        for hop in range(1, depth + 1):
            nxt = []
            for nid in frontier:
                for m in adj.get(nid, []):
                    if m not in seen:
                        seen.add(m)
                        nxt.append(m)
                        out.append((m, hop))
            frontier = nxt
        return out

    # -- trials ---------------------------------------------------------------
    def apply_trial(self, trial):
        """Apply a trial's changes to the in-memory notes. Nothing on disk moves."""
        applied = []
        for op in trial_changes(trial):
            if op["op"] == "add":
                n = self.find(op["target"])
                if not n:
                    applied.append("SKIPPED add to missing note %r" % op["target"])
                    continue
                taken = {c["id"] for x in self.notes.values() for c in x["claims"] if c["id"]}
                cid = mg.new_claim_id(n["id"], op["text"], taken)
                n["body"] = insert_claim(n["body"], "- [%s] %s ^%s" % (op["category"], op["text"], cid))
            else:
                hit = None
                for n in self.notes.values():
                    if re.search(r"\^%s\s*$" % re.escape(op["id"]), n["body"], re.M):
                        hit = n
                        break
                if not hit:
                    applied.append("SKIPPED %s of missing claim ^%s" % (op["op"], op["id"]))
                    continue
                if op["op"] == "replace":
                    hit["body"] = re.sub(r"^\s*-\s*\[[\w-]+\].*\^%s\s*$" % re.escape(op["id"]),
                                         "- [%s] %s ^%s" % (op["category"], op["text"], op["id"]),
                                         hit["body"], flags=re.M)
                else:
                    hit["body"] = retire_line(hit["body"], op["id"], "trial %s" % trial["id"])
                n = hit
            fm, _ = mg.split_frontmatter(n["text"])
            n.update(parse_note(n["id"], n["path"], mg.render(fm or [], n["body"])))
            applied.append("%s %s" % (op["op"], op.get("id") or op.get("target")))
        self.trial_applied = {"slug": trial["id"].split("/")[-1], "ops": applied}


# --------------------------------------------------------------------------- text edits

def insert_claim(body, line):
    """Append a claim under ## Observations, creating the section before ## Relations if needed."""
    lines = body.rstrip("\n").split("\n")
    plain = mg.strip_code(body.rstrip("\n")).split("\n")
    obs = next((i for i, ln in enumerate(plain) if re.match(r"^##\s+observations\s*$", ln, re.I)), None)
    if obs is not None:
        j = obs + 1
        while j < len(plain) and not plain[j].startswith("## "):
            j += 1
        while j - 1 > obs and not lines[j - 1].strip():
            j -= 1
        lines.insert(j, line)
    else:
        rel = next((i for i, ln in enumerate(plain) if re.match(r"^##\s+relations\s*$", ln, re.I)), None)
        block = ["## Observations", line, ""]
        if rel is None:
            lines += [""] + block
        else:
            lines[rel:rel] = block
    return "\n".join(lines) + "\n"


def retire_line(body, cid, why):
    lines = body.rstrip("\n").split("\n")
    idx = next((i for i, ln in enumerate(lines) if re.search(r"\^%s\s*$" % re.escape(cid), ln)), None)
    if idx is None:
        return body
    line = lines.pop(idx).rstrip() + " (retired %s: %s)" % (today(), why)
    plain = mg.strip_code("\n".join(lines)).split("\n")
    ret = next((i for i, ln in enumerate(plain) if re.match(r"^##\s+retired\s*$", ln, re.I)), None)
    if ret is None:
        rel = next((i for i, ln in enumerate(plain) if re.match(r"^##\s+relations\s*$", ln, re.I)), None)
        block = ["## Retired", line, ""]
        if rel is None:
            lines += [""] + block
        else:
            lines[rel:rel] = block
    else:
        lines.insert(ret + 1, line)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- trials

CHANGE_RE = [
    ("add", re.compile(r'^\s*-\s+add\s+to\s+"([^"]+)"\s*:\s*\[([\w-]+)\]\s*(.+?)\s*$', re.I)),
    ("replace", re.compile(r"^\s*-\s+replace\s+\^([0-9a-f]{6})\s+with\s*:\s*\[([\w-]+)\]\s*(.+?)\s*$", re.I)),
    ("retire", re.compile(r"^\s*-\s+retire\s+\^([0-9a-f]{6})\s*$", re.I)),
]


def trial_changes(trial):
    ops = []
    body = trial["sections"].get("changes", "")
    for ln in mg.strip_code(body).split("\n"):
        for kind, rx in CHANGE_RE:
            m = rx.match(ln)
            if not m:
                continue
            if kind == "add":
                ops.append({"op": "add", "target": m.group(1), "category": m.group(2).lower(), "text": m.group(3)})
            elif kind == "replace":
                ops.append({"op": "replace", "id": m.group(1), "category": m.group(2).lower(), "text": m.group(3)})
            else:
                ops.append({"op": "retire", "id": m.group(1)})
            break
    return ops


def live_trials(corpus):
    out = []
    for n in corpus.notes.values():
        if n["path"].startswith("trials/") and (n["status"] or "") == "live":
            exp = parse_date(n["expires"])
            out.append(dict(n, expired=bool(exp and exp < TODAY)))
    return out


def trial_for_person(ctx, corpus):
    """Canary by person: a live trial listing this person in `for:` applies automatically."""
    if not ctx.handle:
        return None
    for t in live_trials(corpus):
        if not t["expired"] and ctx.handle in t["for"]:
            return t
    return None


# --------------------------------------------------------------------------- the engine

class Mem:
    def __init__(self, args):
        root = getattr(args, "root", None)
        self.ctx = mg.Ctx(root)
        self.local = Local(self.ctx.notes_root)
        self.proto = self.ctx.policy.get("protocol", {})
        self.args = args

    def corpus(self, ref=None, trial="auto"):
        info = resolve_ref(self.ctx, ref)
        base = Corpus(self.ctx, dict(info, trial=None) if info.get("trial") else info)
        overlay = None
        if info.get("trial"):
            overlay = next((t for t in live_trials(base) if t["id"].endswith("/" + info["trial"])), None)
            if not overlay:
                die("no live trial %r" % info["trial"])
        elif trial == "auto" and not info.get("past"):
            overlay = trial_for_person(self.ctx, base)
        if overlay:
            return Corpus(self.ctx, info, overlay=overlay), info
        return base, info

    def acting(self):
        p = self.ctx.person or {}
        return {"handle": self.ctx.handle or "unregistered", "role": p.get("role", "unregistered"),
                "function": p.get("function"), "restricted_read": bool(p.get("restricted_read")),
                "kind": self.ctx.actor_kind, "cap": self.ctx.effective_max_level() or "nothing"}

    def can_write(self, rel):
        need = self.ctx.path_level((self.ctx.prefix + rel) if self.ctx.prefix else rel)
        have = self.ctx.effective_max_level()
        return mg.level_allows(have, need), need, have

    def write_note(self, rel, text):
        path = os.path.join(self.ctx.notes_root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mg.write_text(path, text)
        return path


# --------------------------------------------------------------------------- resolution

SYMPTOM_RX = (r"\bkeeps? \w+ing\b|\bhas no\b|\bhave no\b|\bno (?:output|data|results?|rows?|response)\b|"
              r"\bmissing\b|\bwrong\b|\bstopped\b|\bstuck\b|\bhangs?\b|\bfreez\w*|\bblank\b|"
              r"\bdoesn'?t\b|\bdoes not\b|\bwon'?t\b|\bcan'?t\b|\bnot (?:showing|loading|saving|updating|sending)\b|"
              r"\bduplicat\w*|\breturns? (?:an? )?(?:error|5\d\d)\b|\btim(?:es|ed|ing) out\b|\btoo slow\b|"
              r"\b(?:is|are|goes|went|turned|turns) red\b|\breturns? (?:nothing|null|none|empty)\b|\bis empty\b|"
              r"\binvent(?:s|ed|ing)?\b|\bhallucinat\w*|\bmade[- ]up\b|\bfabricat\w*")


def detect_mode(ask, function=None, extra_symptoms=()):
    """The earliest intent word in the ask wins; the person's function is only a fallback.

    `extra_symptoms` are regular expressions from roles.json `protocol.extra_symptoms`: the words
    a bug report uses in this team's domain ("spins forever" in a web app, "404" for routing). The
    built-in list stays generic."""
    if not ask:
        return {"pm": "plan"}.get(function or "", "orient"), "no ask given"
    a = " " + ask.lower() + " "
    rules = [
        ("orient", r"catch me up|overview|onboard|big picture|orient me|what is this project"),
        ("plan", r"roadmap|prioriti[sz]e|priorit(?:y|ies)|what should we|where are we|next quarter|"
                 r"backlog|planning|strategy for"),
        ("review", r"\breview\b|\baudit\b|pull request|\bpr\b|\bdiff\b"),
        ("explain", r"\bwhy (?:do|does|did|is|are|we)\b|\bexplain\b|\bhow does\b|\bwhat is\b"),
        ("debug", r"\bbug\b|\bbroken\b|\bfail(?:s|ing|ed|ure)?\b|\berrors?\b|\bcrash\w*|\bregress\w*|"
                  r"\bflaky\b|not working|doesn'?t work|\bfix\b"),
        ("change", r"\bchange\b|\bmodify\b|\brefactor\w*|\bremove\b|\bdelete\b|\brename\b|\bmigrate\b|"
                   r"\breplace\b|\bdeprecate\b|\bsplit\b|\brewrite\b|\bmove\b"),
        ("build", r"\badd\b|\bimplement\b|\bcreate\b|\bbuild\b|\bintroduce\b|\bsupport\b|\bnew\b"),
    ]
    best = None
    for mode, rx in rules:
        m = re.search(rx, a)
        if m and (best is None or m.start() < best[1]):
            best = (mode, m.start(), m.group(0).strip())
    if best:
        return best[0], "the ask says %r" % best[2]
    # No intent word. A bug report often names only the symptom ("the export has no rows", "keeps
    # timing out"): both were read as build in early testing. Symptoms are a
    # fallback, never a competitor, so "add X because Y is missing" stays build.
    m = re.search(SYMPTOM_RX, a)
    for rx in ([] if m else list(extra_symptoms or ())):
        try:
            m = re.search(rx, a)
        except re.error:
            sys.stderr.write("mem: protocol.extra_symptoms has an invalid pattern, ignored: %r\n" % rx)
            continue
        if m:
            break
    if m:
        return "debug", "no intent word; %r reads like a symptom" % m.group(0).strip()
    if function == "pm":
        return "plan", "no intent word; you are a PM"
    # A guess, and the receipt says so: the held-out review found asks with no intent word silently
    # read as build, which loads the wrong neighbourhood for a bug report.
    return "build", "A GUESS: no intent word or symptom; if this is a bug, rerun with --mode debug"


def path_tokens(ask):
    return [t for t in re.findall(r"[\w./-]+", ask or "") if ("." in t or "/" in t or "_" in t) and len(t) > 3]


def resolve(mem, corpus, ask, touching=(), names=()):
    """Rank features for this ask. Returns (ranked [(score, note, reasons)], confident)."""
    feats = corpus.features()
    scores = {f["id"]: [0.0, []] for f in feats}
    ask_l = (ask or "").lower()
    aw = set(words(ask))
    root = mg.code_root(mem.ctx)
    files = mg.code_files(root) if root else []

    for f in feats:
        s = scores[f["id"]]
        for nm in names:
            if nm.lower() in (f["title"].lower(), f["id"].lower()):
                s[0] += 100
                s[1].append("named explicitly")
        for p in touching:
            p = p.replace("\\", "/").lstrip("./")
            if any(mg.glob_match(g, p) for g in f["covers"]):
                s[0] += 12
                s[1].append("covers %s" % p)
        if f["title"].lower() in ask_l:
            s[0] += 9
            s[1].append("names %r" % f["title"])
        tw = set(words(f["title"]))
        hit = aw & tw
        if hit:
            s[0] += 4 * len(hit)
            s[1].append("title words %s" % ", ".join(sorted(hit)))
        for al in f["aliases"]:
            if re.search(r"(?<![\w])%s(?![\w])" % re.escape(al.lower()), ask_l):
                # A phrase is more specific than a word: a two-word alias was once beaten by two features
                # whose files were merely named after one of its words.
                n_words = len(al.split())
                s[0] += 7 + 3 * (n_words - 1)
                s[1].append("alias %r" % al)
        cw = aw & set(words(f["card"]))
        if cw:
            s[0] += min(4, len(cw))
            s[1].append("card mentions %s" % ", ".join(sorted(cw)[:3]))
    # A word in the ask that is the stem of a file a feature covers ("export" -> export.py) points at
    # that feature. Generic stems are ignored: every codebase has an index, a main and a utils.
    generic = {"index", "main", "utils", "util", "init", "__init__", "test", "tests", "app", "base",
               "common", "core", "types", "config", "helpers", "server", "client", "setup", "readme"}
    if files:
        for f in feats:
            stems = set()
            for x in files:
                if any(mg.glob_match(g, x) for g in f["covers"]):
                    st = os.path.splitext(x.split("/")[-1])[0].lower()
                    if len(st) >= 4 and st not in generic:
                        stems.add(st)
            hit = aw & stems
            if hit:
                scores[f["id"]][0] += 7 * min(2, len(hit))  # the same weight as an alias
                scores[f["id"]][1].append("owns %s" % ", ".join(sorted(hit)[:2]))
    # a file named in the ask resolves to whatever covers it
    for tok in path_tokens(ask):
        base = tok.split("/")[-1].lower()
        matched = [x for x in files if x.lower().endswith("/" + base) or x.lower() == tok.lower()]
        for f in feats:
            if any(any(mg.glob_match(g, x) for g in f["covers"]) for x in matched[:50]):
                scores[f["id"]][0] += 10
                scores[f["id"]][1].append("owns %s" % tok)
    ranked = sorted(((v[0], corpus.notes[k], v[1]) for k, v in scores.items() if v[0] > 0),
                    key=lambda r: -r[0])
    if not ranked:
        return [], False
    top = ranked[0][0]
    second = ranked[1][0] if len(ranked) > 1 else 0
    confident = top >= 7 and (second <= top * 0.6 or top >= 12)
    return ranked, confident


def resolve_decisions(corpus, ask):
    """For "why do we..." asks that name no feature: rank decision records by the ask's words in
    their title (x4) and body (x1 per distinct word, capped at 6). An explain ask is usually about a
    decision, and a feature-only resolver answered "which feature?" to a question about none."""
    aw = set(words(ask))
    out = []
    for n in corpus.notes.values():
        if not n["path"].startswith("decisions/") or n["type"] not in ("decision", "adr"):
            continue
        if re.search(r"(?i)template", n["title"]):
            continue
        tw = aw & set(words(n["title"]))
        bw = aw & set(words(mg.strip_code(n["body"])))
        score = 4 * len(tw) + min(6, len(bw - tw))
        if score:
            reasons = (["title words %s" % ", ".join(sorted(tw))] if tw else []) + \
                      (["body mentions %s" % ", ".join(sorted(bw - tw)[:4])] if bw - tw else [])
            out.append((score, n, reasons))
    out.sort(key=lambda r: -r[0])
    if not out:
        return [], False
    top, second = out[0][0], (out[1][0] if len(out) > 1 else 0)
    return out, top >= 4 and top >= 1.5 * max(second, 1)


# --------------------------------------------------------------------------- scope

def build_scope(mem, corpus, mode, targets):
    """OrderedDict nid -> (depth, role). Directional: never an undirected walk."""
    items = OrderedDict()
    proto = mem.proto
    up_n, down_n = proto.get("upstream_hops", 2), proto.get("downstream_hops", 2)

    def put(nid, depth, role):
        if nid not in corpus.notes:
            return
        cur = items.get(nid)
        if cur is None:
            items[nid] = (depth, role)
        elif DEPTH_RANK[depth] > DEPTH_RANK[cur[0]]:
            items[nid] = (depth, cur[1])

    if "CORE" in corpus.notes:
        put("CORE", "full", "core")
    if mode == "orient":
        return items

    if mode == "plan":
        for f in corpus.features():
            put(f["id"], "card", "feature cards")
        for n in corpus.notes.values():
            if n["path"].startswith("decisions/") and (n["status"] or "") == "proposed":
                put(n["id"], "card", "open decisions")
            if n["path"].startswith("log/proposals/") and (n["status"] or "open") == "open":
                put(n["id"], "title", "waiting proposals")
            if n["path"].startswith("log/gaps/"):
                put(n["id"], "full", "gaps")
        cutoff = TODAY - timedelta(days=proto.get("plan_recent_days", 14))
        for n in corpus.notes.values():
            d = parse_date(n["updated"])
            if n["path"].startswith("log/journal/") and d and d >= cutoff:
                put(n["id"], "title", "recent change")
        for t in targets:
            put(t, "full", "target")
        return items

    for t in targets:
        put(t, "full", "target")

    if mode in ("build", "debug"):
        for nid, _h in corpus.hops(targets, "up", up_n):
            put(nid, "full", "relies on")
        for nid, _h in corpus.hops(targets, "down", 1):
            put(nid, "card", "could break")
    elif mode == "change":
        for nid, _h in corpus.hops(targets, "down", down_n):
            put(nid, "full", "could break")
        for nid, _h in corpus.hops(targets, "up", 1):
            put(nid, "card", "relies on")
    elif mode == "review":
        for c in targets:
            if corpus.notes[c]["contract"]:
                put(c, "full", "target")
        for nid, _h in corpus.hops(targets, "down", 1):
            put(nid, "card", "could break")
    elif mode == "explain":
        for t in targets:
            for (src, dst, rtype, _dep) in corpus.edges:
                if src == t and rtype in ("implements", "supersedes"):
                    put(dst, "full", "the decision")
                if dst == t and rtype == "supersedes":
                    put(src, "full", "the decision")
                if dst == t and rtype == "implements":
                    put(src, "card", "implemented by")
        chain = list(items)
        for nid in chain:
            for (src, dst, rtype, _dep) in corpus.edges:
                if rtype == "supersedes" and nid in (src, dst):
                    put(dst if src == nid else src, "full", "the decision")

    if mode == "debug":
        related = set(items)
        titles = [corpus.notes[t]["title"].lower() for t in targets]
        cutoff = TODAY - timedelta(days=proto.get("debug_journal_days", 30))
        for n in corpus.notes.values():
            if not n["path"].startswith("log/"):
                continue
            d = parse_date(n["updated"])
            if d and d < cutoff:
                continue
            links = {corpus.by_title.get(t.lower()) for _r, t in n["relations"]}
            if links & related or any(t in n["body"].lower() for t in titles):
                put(n["id"], "full", "recent history")
    return items


# --------------------------------------------------------------------------- rendering

def feature_map(corpus):
    lines = ["## Feature map", ""]
    feats = sorted(corpus.features(), key=lambda f: f["title"].lower())
    if not feats:
        return "## Feature map\n\n_No features yet. `mem feature new \"<name>\"` creates one._\n"
    for f in feats:
        first = re.split(r"(?<=[.!?])\s", re.sub(r"\s+", " ", f["card"] or "").strip())[0]
        deps = sorted({corpus.notes[t]["title"] for t in corpus.up[f["id"]]
                       if corpus.notes[t]["type"] == "feature"})
        lines.append("- **%s** (%s, owner %s)%s — %s" % (
            f["title"], f["status"] or "?", f["owner"] or "?",
            ("; relies on " + ", ".join(deps)) if deps else "", first))
    return "\n".join(lines) + "\n"


def render_block(corpus, nid, depth):
    n = corpus.notes[nid]
    meta = ", ".join(x for x in (n["type"], n["level"], n["status"],
                                 ("owner " + n["owner"]) if n["owner"] else None) if x)
    head = "### %s  (%s)\n<!-- note %s · %s -->\n" % (n["title"], meta, n["path"], n["hash"][:12])
    if depth == "title":
        return "- %s  (%s)\n" % (n["title"], meta)
    if depth == "card":
        extra = ""
        if n["contract"]:
            extra = "\n**Contract:** " + re.sub(r"\s+", " ", n["contract"]).strip()[:400] + "\n"
        return head + "\n" + (n["card"] or "_no card_").strip() + "\n" + extra + "\n"
    return head + "\n" + n["body"].strip() + "\n\n"


ROLE_ORDER = ["core", "about", "target", "the decision", "implemented by", "relies on", "could break", "recent history",
              "feature cards", "open decisions", "waiting proposals", "gaps", "recent change", "pinned"]


def cmd_load(mem, a):
    corpus, ref = mem.corpus(a.ref)
    who = mem.acting()
    mode, why_mode = (a.mode, "you chose it") if a.mode else detect_mode(a.ask, who["function"], mem.proto.get("extra_symptoms") or ())
    if mode not in MODES:
        die("unknown mode %r; one of %s" % (mode, ", ".join(MODES)))

    targets, resolution = [], None
    orient_about = []
    if mode == "orient" and (a.ask or a.touching or a.feature):
        # "catch me up on Billing": the big picture PLUS that feature's card. Orient
        # never asks a question, so an unclear target is simply left out.
        ranked, confident = resolve(mem, corpus, a.ask, a.touching or [], a.feature or [])
        if ranked and confident:
            orient_about = [ranked[0][1]["id"]]
            resolution = ranked[:3]
    if mode not in ("orient",):
        names = a.feature or []
        ranked, confident = resolve(mem, corpus, a.ask, a.touching or [], names)
        explicit = [corpus.find(nm) for nm in names]
        missing = [nm for nm, n in zip(names, explicit) if n is None]
        if missing:
            die("no note called %s" % ", ".join(repr(m) for m in missing))
        if explicit:
            targets = [n["id"] for n in explicit]
        elif ranked and (confident or mode == "plan"):
            targets = [ranked[0][1]["id"]]
            if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] * 0.85:
                targets.append(ranked[1][1]["id"])
        elif mode == "explain" and resolve_decisions(corpus, a.ask)[1]:
            dranked, _ok = resolve_decisions(corpus, a.ask)
            targets = [dranked[0][1]["id"]]
            ranked = dranked
        elif mode not in ("plan",):
            print("mem: I cannot tell which feature this is about.")
            if ranked:
                for sc, n, rs in ranked[:3]:
                    print("  - %s  (score %.0f: %s)" % (n["title"], sc, "; ".join(rs[:2])))
                print("Ask the person which one, then: mem load \"%s\" --feature \"<name>\"" % (a.ask or ""))
                if mode == "explain":
                    print("A 'why' question may be about a rule rather than a feature: mem recall \"%s\"" % (a.ask or ""))
            else:
                print("  No feature matched. Name one with --feature, or load orient mode for the big picture.")
            return EXIT_AMBIGUOUS
        resolution = ranked[:3]
    if a.add:
        for nm in a.add:
            n = corpus.find(nm)
            if not n:
                die("no note called %r" % nm)
            targets.append(n["id"])

    items = build_scope(mem, corpus, mode, targets)
    for nid in orient_about:
        items.setdefault(nid, ("card", "about"))

    prefs = mem.local.prefs()
    for p in prefs.get("pins", []):
        n = corpus.find(p)
        if n and n["id"] not in items:
            items[n["id"]] = ("full", "pinned")
    mutes = {corpus.find(m)["id"] for m in prefs.get("mutes", []) if corpus.find(m)}
    withheld = []
    for nid in list(items):
        n = corpus.notes[nid]
        if nid in mutes and nid not in targets:
            del items[nid]
        elif n["confidentiality"] == "restricted" and not who["restricted_read"]:
            del items[nid]
            withheld.append(nid)

    # ledger: what is already in this session's context. Read-modify-write under the session lock.
    sid = mem.local.session_id(a.session)
    with mem.local.lock(sid):
        return _load_locked(mem, a, corpus, ref, who, mode, why_mode, targets, resolution, items, withheld, sid)


def _load_locked(mem, a, corpus, ref, who, mode, why_mode, targets, resolution, items, withheld, sid):
    led = mem.local.ledger(sid)
    if not led or led.get("ref") != ref["label"]:
        if led and led.get("ref") and led.get("ref") != ref["label"]:
            print("mem: switching context ref %s -> %s; earlier loads no longer count" % (led["ref"], ref["label"]))
        led = {"session": sid, "ref": ref["label"], "started": datetime.now(timezone.utc).isoformat(),
               "turn": 0, "loaded": {}}
    led["turn"] += 1

    blocks, repeated, from_cache = [], [], 0
    groups = OrderedDict((r, []) for r in ROLE_ORDER)
    for nid, (depth, role) in items.items():
        n = corpus.notes[nid]
        prev = led["loaded"].get(nid)
        groups.setdefault(role, []).append((n["title"], depth))
        if (prev and not prev.get("evicted") and prev["hash"] == n["hash"]
                and DEPTH_RANK[prev["depth"]] >= DEPTH_RANK[depth] and not a.full):
            repeated.append("%s (turn %d)" % (n["title"], prev["turn"]))
            continue
        cache_file = mem.local.path("cache", "%s-%s.md" % (n["hash"][:32], depth))
        block = cache_read(cache_file, n["hash"], depth)
        if block is not None:
            from_cache += 1
        else:
            block = render_block(corpus, nid, depth)
            try:
                cache_write(mem.local, cache_file, n["hash"], depth, block)
            except OSError:
                pass  # a cache is an optimisation; the load goes on without it
        if nid == "CORE":
            block += "\n" + feature_map(corpus) + "\n"
        blocks.append((role, block))
        led["loaded"][nid] = {"hash": n["hash"], "depth": depth, "turn": led["turn"], "evicted": False,
                              "path": n["path"], "contract": n["contract_hash"]}
    if "CORE" not in corpus.notes and mode != "plan":
        blocks.insert(0, ("core", "## Core\n\n_There is no CORE.md. Run `mem core init` - without it an "
                                  "agent starts every task without the big picture._\n\n" + feature_map(corpus)))

    body = "".join(b for _r, b in blocks)
    est = mg.estimate_tokens(body)
    trial = corpus.trial_applied
    receipt = receipt_text(ref, mode, why_mode, who, groups, len(items), est, from_cache,
                           withheld, repeated, trial, resolution)
    text = "# Context bundle\n\n```\n%s\n```\n\n%s" % (receipt, body)
    if repeated:
        text += "\n## Already loaded this session, not repeated\n\n" + "".join("- %s\n" % r for r in repeated)
    data = text.encode("utf-8")
    # Content-addressed: the name is the hash of the exact bytes, so two sessions (or a repeat load)
    # can never overwrite each other's bundle (audit 04-F2).
    bundle = mem.local.path("bundles", "%s.md" % hashlib.sha256(data).hexdigest()[:20])
    led["mode"], led["targets"], led["last_receipt"], led["last_bundle"] = mode, targets, receipt, bundle
    try:
        if not os.path.isfile(bundle):
            mem.local.write_bytes(bundle, data)
        mem.local.write_json(os.path.relpath(mem.local.receipt_path(sid), mem.local.root),
                             {"session": sid, "receipt": receipt, "bundle": bundle})
        mem.local.save_ledger(sid, led)  # LAST: the commit point (audit 04-F7)
    except OSError as e:
        die("could not save this load (%s); nothing was marked as delivered, so run it again" % e, 1)

    if a.json:
        print(json.dumps({"mode": mode, "ref": ref["label"], "targets": targets, "bundle": bundle,
                          "notes": [{"id": k, "depth": v[0], "role": v[1]} for k, v in items.items()],
                          "tokens_estimate": est, "withheld": withheld, "repeated": repeated}, indent=1))
    else:
        print(receipt)
        # Relative to where the agent IS (the repo root, in a project tier), not to the notes root.
        print("\nBundle: %s" % os.path.relpath(bundle, os.getcwd()).replace(os.sep, "/"))
        if a.print:
            print("\n" + body)
    return EXIT_OK


def receipt_text(ref, mode, why_mode, who, groups, n_notes, est, from_cache, withheld, repeated, trial,
                 resolution):
    cap = "writes %s" % who["cap"]
    lines = ["Context · %s · %s mode (%s) · for %s (%s, %s)" % (
        ref["label"], mode, why_mode, who["handle"], who["role"],
        ("agent " if who["kind"] == "agent" else "") + cap)]
    if trial:
        lines.append("  trial ............ %s applied (%d change%s)" % (
            trial["slug"], len(trial["ops"]), "" if len(trial["ops"]) == 1 else "s"))
    if ref.get("past"):
        lines.append("  version .......... a PAST context, not the latest")
    for role, entries in groups.items():
        if not entries:
            continue
        depths = sorted({d for _t, d in entries}, key=lambda d: -DEPTH_RANK[d])
        names = ", ".join(t for t, _d in entries[:6]) + (" +%d more" % (len(entries) - 6) if len(entries) > 6 else "")
        lines.append("  %-17s %s  [%s]" % ((role + " ").ljust(17, "."), names, "/".join(depths)))
    if resolution:
        top = resolution[0]
        lines.append("  resolved by ...... %s" % "; ".join(top[2][:3]))
    lines.append("  %d notes · ~%d new tokens (estimate) · %d from cache · %d already in context · %d restricted withheld"
                 % (n_notes, est, from_cache, len(repeated), len(withheld)))
    lines.append('  Change it: --mode plan|build|change|debug|review|explain · --add "<feature>" · --ref main@YYYY-MM-DD')
    return "\n".join(lines)


def cmd_resolve(mem, a):
    corpus, _ = mem.corpus(a.ref)
    ranked, confident = resolve(mem, corpus, a.ask, a.touching or [])
    mode, why = detect_mode(a.ask, mem.acting()["function"], mem.proto.get("extra_symptoms") or ())
    if a.json:
        print(json.dumps({"mode": mode, "why": why, "confident": confident,
                          "features": [{"title": n["title"], "score": s, "reasons": r} for s, n, r in ranked[:5]]}, indent=1))
        return EXIT_OK if confident else EXIT_AMBIGUOUS
    print("mode: %s (%s)" % (mode, why))
    if not ranked:
        print("no feature matched")
        return EXIT_AMBIGUOUS
    for s, n, r in ranked[:5]:
        print("  %5.0f  %-32s %s" % (s, n["title"], "; ".join(r[:3])))
    print("confident" if confident else "AMBIGUOUS - ask the person which one")
    return EXIT_OK if confident else EXIT_AMBIGUOUS


def cmd_context(mem, a):
    led = mem.local.ledger(mem.local.session_id(a.session))
    if not led or not led.get("last_receipt"):
        print("mem: nothing loaded in this session yet. Start with: mem load \"<the ask>\"")
        return EXIT_OK
    print(led["last_receipt"])
    live = [k for k, v in led["loaded"].items() if not v.get("evicted")]
    print("\nIn context now: %d notes (%d evicted by compaction)" % (len(live), len(led["loaded"]) - len(live)))
    return EXIT_OK


# --------------------------------------------------------------------------- session + moved

def cmd_session(mem, a):
    if a.action == "purge":
        n = mem.local.purge()
        print("mem: deleted %d cached note block(s) and bundle(s) from this machine" % n)
        return EXIT_OK
    if a.action == "start":
        sid = a.id
        if not sid and not a.hook and not sys.stdin.isatty():
            try:
                raw = sys.stdin.read()
                sid = (json.loads(raw) if raw.strip() else {}).get("session_id")
            except ValueError:
                sid = None
        sid = sid or datetime.now(timezone.utc).strftime("s%Y%m%d%H%M%S")
        try:
            check_session_id(sid)
        except SessionIdError as e:
            die("%s" % e, EXIT_INVALID)
        mem.local.write_bytes(mem.local.path("session", "current"), sid.encode("utf-8"))
        with mem.local.lock(sid):
            if not mem.local.ledger(sid):
                mem.local.save_ledger(sid, {"session": sid, "ref": None, "turn": 0, "loaded": {},
                                            "started": datetime.now(timezone.utc).isoformat()})
            try:
                os.remove(mem.local.receipt_path(sid))  # no previous session's receipt (04-F10)
            except OSError:
                pass
        mem.local.purge(RETENTION_DAYS)
        print("mem: session %s. Follow the entry protocol: mem load \"<the ask>\"" % json.dumps(sid))
        return EXIT_OK
    sid = mem.local.session_id(a.id or a.session)
    if a.action == "evict":
        # Compaction drops loaded notes from the context window. Without this the ledger would
        # say "already loaded" about text the agent can no longer see.
        with mem.local.lock(sid):
            led = mem.local.ledger(sid)
            if led:
                for v in led["loaded"].values():
                    v["evicted"] = True
                mem.local.save_ledger(sid, led)
        print("mem: context compacted - %d note(s) marked evicted; they will be re-read from the local "
              "cache when needed" % (len(led["loaded"]) if led else 0))
        return EXIT_OK
    led = mem.local.ledger(sid)
    print(json.dumps(led or {}, indent=1))
    return EXIT_OK


def cmd_moved(mem, a):
    sid = mem.local.session_id(a.session)
    led = mem.local.ledger(sid)
    if not led or not led.get("loaded"):
        if not a.quiet:
            print("mem: nothing loaded in this session.")
        return EXIT_OK
    # Per session: one session's check used to silence another's for five minutes (audit 04-F6).
    stamp_file = mem.local.path("session", session_key(sid) + ".moved")
    every = a.throttle if a.throttle is not None else 0
    if every and os.path.isfile(stamp_file) and time.time() - os.path.getmtime(stamp_file) < every:
        return EXIT_OK
    remote_ref = None
    if a.fetch:
        mg.git("-C", mem.ctx.repo_root, "fetch", "-q")
        up = mg.git("-C", mem.ctx.repo_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
        remote_ref = up or None
    changes = []
    for nid, v in led["loaded"].items():
        rel = v.get("path") or (nid + ".md")
        repo_rel = (mem.ctx.prefix + rel) if mem.ctx.prefix else rel
        sources = [("local", None)] + ([("upstream " + remote_ref, remote_ref)] if remote_ref else [])
        for label, gref in sources:
            if gref:
                text = mg.git("-C", mem.ctx.repo_root, "show", "%s:%s" % (gref, repo_rel))
            else:
                p = os.path.join(mem.ctx.notes_root, rel)
                text = mg.read_text(p) if os.path.isfile(p) else ""
            if not text:
                changes.append((nid, label, "DELETED", False))
                break
            if sha(text) != v["hash"]:
                n = parse_note(nid, rel, text)
                contract = n["contract_hash"] != v.get("contract")
                changes.append((n["title"], label, "changed", contract))
                break
    try:
        mem.local.write_bytes(stamp_file, b"")  # only after a completed comparison
    except OSError:
        pass
    if not changes:
        if not a.quiet:
            print("mem: nothing you loaded has changed since you loaded it.")
        return EXIT_OK
    print("memory: YOUR CONTEXT MOVED since you loaded it (session %s):" % json.dumps(sid))
    for title, label, what, contract in changes:
        print("  - %s: %s (%s)%s" % (title, what, label,
                                     "  ** CONTRACT CHANGED - re-check anything that relies on it **" if contract else ""))
    print("  Re-read with: mem load --add \"<title>\" --full   (or mem context to see what you have)")
    return EXIT_OK


# --------------------------------------------------------------------------- claims: pack + recall

AUTHORITY = [("CORE", 1.0), ("decisions/", 0.9), ("features/", 0.9), ("context/", 0.8),
             ("projects/", 0.6), ("evals/", 0.0), ("trials/", 0.2), ("log/", 0.3)]


def authority(n):
    if n["id"] == "CORE":
        return 1.0
    for prefix, w in AUTHORITY:
        if n["path"].startswith(prefix):
            if prefix == "decisions/" and (n["status"] or "") != "accepted":
                return 0.6
            return w
    return 0.5


def freshness(n):
    if n["level"] and n["level"] != "L0":
        return 1.0  # an old strategy is not a wrong strategy
    d = parse_date(n["updated"])
    if not d:
        return 0.7
    return 0.5 ** (max(0, (TODAY - d).days) / 30.0)


def cmd_compile(mem, a):
    corpus, ref = mem.corpus(a.ref)
    rows = []
    for nid, n in corpus.notes.items():
        for c in n["claims"]:
            rows.append({"id": c["id"], "text": c["text"], "category": c["category"], "note": nid,
                         "title": n["title"], "level": n["level"],
                         "state": "retired" if c["retired"] else ("idea" if c["category"] == "idea" else "belief"),
                         "updated": n["updated"], "tokens": mg.estimate_tokens(c["text"])})
    with open(mem.local.path("pack", "claims.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    feats = [{"id": f["id"], "title": f["title"], "status": f["status"], "owner": f["owner"],
              "covers": f["covers"], "aliases": f["aliases"],
              "relies_on": [corpus.notes[t]["title"] for t in corpus.up[f["id"]]],
              "relied_on_by": [corpus.notes[t]["title"] for t in corpus.down[f["id"]]]}
             for f in corpus.features(include_retired=True)]
    mem.local.write_json(os.path.join("pack", "features.json"), feats)
    with open(mem.local.path("pack", "source"), "w") as fh:
        fh.write(ref["label"] + "\n")
    missing = [r for r in rows if not r["id"]]
    if not a.quiet:
        print("mem: compiled %d claims from %d notes, %d features at %s -> .memory/pack/%s"
              % (len(rows), len(corpus.notes), len(feats), ref["label"],
                 ("  (%d claims have no id yet; `memory_guard.py stamp` assigns them)" % len(missing)) if missing else ""))
    return EXIT_OK


def _idf(corpus):
    """Inverse document frequency over claim texts. Without it, a claim matching only 'notes' in the
    core (authority 1.0) outranked the one claim matching 'restricted' AND 'submodule' - observed on
    cairn's own notes."""
    cached = getattr(corpus, "_idf_cache", None)
    if cached is not None:
        return cached
    import math
    df, total = {}, 0
    for n in corpus.notes.values():
        for c in n["claims"]:
            if c["retired"]:
                continue
            total += 1
            for w in set(words(c["text"])):
                df[w] = df.get(w, 0) + 1
    table = {w: math.log(1 + total / float(k)) for w, k in df.items()}
    default = math.log(1 + max(total, 1))
    corpus._idf_cache = (table, default)
    return corpus._idf_cache


def recall(mem, corpus, query, limit=15, ideas=False):
    q = set(words(query))
    idf, idf_unseen = _idf(corpus)
    weight = lambda ws: sum(idf.get(w, idf_unseen) for w in ws)
    q_weight = max(1e-9, weight(q))
    prefs = mem.local.prefs()
    pins = {p.lstrip("^") for p in prefs.get("pins", [])}
    mutes = {p.lstrip("^") for p in prefs.get("mutes", [])}
    out = []
    for nid, n in corpus.notes.items():
        if n["confidentiality"] == "restricted" and not mem.acting()["restricted_read"]:
            continue
        tw = set(words(n["title"]))
        for c in n["claims"]:
            if c["retired"] or c["category"] == "eval":
                continue
            if c["category"] == "idea" and not ideas:
                continue
            cid = c["id"] or ""
            if cid in mutes or nid in mutes or n["title"] in mutes:
                continue
            cw = set(words(c["text"]))
            overlap = weight(q & cw) + 0.5 * weight(q & tw)
            pinned = cid in pins or nid in pins or n["title"] in pins
            if overlap <= 0 and not pinned:
                continue
            rel = overlap / q_weight  # share of the query's information this claim covers
            state = 0.5 if c["category"] == "gap" else 1.0
            score = rel * authority(n) * freshness(n) * state + (100 if pinned else 0)
            reasons = []
            if pinned:
                reasons.append("pinned")
            if q & cw:
                reasons.append("matches " + ", ".join(sorted(q & cw)[:3]))
            if q & tw:
                reasons.append("in %r" % n["title"])
            reasons.append("authority %.1f" % authority(n))
            out.append((score, cid, c, n, reasons))
    out.sort(key=lambda r: -r[0])
    return out[:limit]


def cmd_recall(mem, a):
    corpus, ref = mem.corpus(a.ref)
    hits = recall(mem, corpus, a.query, a.limit, a.ideas)
    # Log what was shown and why, never the query text: a task description can hold anything.
    qhash = sha(mem.local.salt() + a.query)[:16]
    with open(mem.local.path("logs", "recall-%s.jsonl" % TODAY.strftime("%Y-%m")), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "ref": ref["label"],
                             "q": qhash, "ids": [h[1] for h in hits],
                             "why": [h[4][0] if h[4] else "" for h in hits]}) + "\n")
    if a.json:
        print(json.dumps([{"id": h[1], "text": h[2]["text"], "category": h[2]["category"],
                           "note": h[3]["title"], "score": round(h[0], 3), "reasons": h[4]} for h in hits], indent=1))
        return EXIT_OK
    if not hits:
        print("mem: nothing in memory matches %r. If you needed it, record the gap: mem gap \"%s\"" % (a.query, a.query))
        return EXIT_OK
    for s, cid, c, n, reasons in hits:
        print("^%-6s [%s] %s\n         — %s · %s" % (cid or "?", c["category"], c["text"], n["title"], "; ".join(reasons)))
    return EXIT_OK


# --------------------------------------------------------------------------- write verbs

NOTE_TEMPLATE = """---
title: {title}
type: {type}
tags: [{tags}]
{extra}---

# {title}

{lead}

## Observations
{claims}

## Relations
{relations}
"""


def new_note_text(title, ntype, tags, lead, claims, relations, extra=""):
    return NOTE_TEMPLATE.format(title=title, type=ntype, tags=", ".join(tags), extra=extra, lead=lead,
                                claims="\n".join(claims), relations="\n".join(relations))


def fresh_id(corpus, note_id, text):
    return mg.new_claim_id(note_id, text, set(corpus.claims))


def core_title(mem):
    """The core note's real title: 'Core' in cairn, '<Project> Core' in a project tier. Linking a
    new note to a hard-coded [[Core]] left a dangling relation in every project tier."""
    path = os.path.join(mem.ctx.notes_root, "CORE.md")
    if os.path.isfile(path):
        m = re.search(r"^title:\s*(.+?)\s*$", mg.read_text(path), re.M)
        if m:
            return m.group(1).strip("'\"")
    return "Core"


def proposal(mem, title, target_rel, text, why, kind="text", payload=""):
    rel = "log/proposals/PROPOSAL - %s.md" % re.sub(r"[^\w .,()'-]", "", title)[:80].strip()
    body = new_note_text(
        "PROPOSAL - %s" % title, "proposal", ["proposal"],
        "Proposed change to `%s`. %s" % (target_rel, why or ""),
        ["- [proposal] %s" % re.sub(r"\s+", " ", text).strip()[:300]],
        ["- relates_to [[%s]]" % core_title(mem)],
        extra="status: open\ntarget: %s\nproposal_kind: %s\n" % (target_rel, kind))
    if payload:
        body = body.rstrip("\n") + "\n\n## Payload\n\n````\n%s\n````\n" % payload.rstrip("\n")
    mem.write_note(rel, body)
    return rel


def cmd_remember(mem, a):
    corpus, _ = mem.corpus(trial=None)
    text = re.sub(r"\s+", " ", a.claim).strip()
    if not text:
        die("nothing to remember")
    cat = (a.category or "fact").lower()
    target = None
    if a.note:
        target = corpus.find(a.note)
        if not target:
            die("no note %r" % a.note)
    elif a.feature:
        target = corpus.find(a.feature)
        if not target:
            die("no feature %r" % a.feature)
    about = target
    if about is None:
        ranked, confident = resolve(mem, corpus, text)
        about = ranked[0][1] if ranked and confident else None
    if target is not None:
        for c in target["claims"]:
            if mg.jaccard(mg._claim_tokens(c["text"]), mg._claim_tokens(text)) >= 0.85:
                print("mem: %r already holds this (^%s): %s" % (target["title"], c["id"], c["text"]))
                return EXIT_OK
        allowed, need, have = mem.can_write(target["path"])
        if not allowed:
            rel = proposal(mem, "Add claim to %s" % target["title"], target["path"],
                           "[%s] %s" % (cat, text), "Raised by %s." % mem.acting()["handle"], kind="claim",
                           payload="- [%s] %s" % (cat, text))
            print("mem: %s is %s and you write %s, so this became a proposal: %s" % (target["title"], need, have, rel))
            return EXIT_OK
        cid = fresh_id(corpus, target["id"], text)
        path = os.path.join(mem.ctx.notes_root, target["path"])
        fm, body = mg.split_frontmatter(mg.read_text(path))
        mg.write_text(path, mg.render(fm or [], insert_claim(body, "- [%s] %s ^%s" % (cat, text, cid))))
        print("mem: remembered ^%s in %s" % (cid, target["path"]))
        return EXIT_OK
    rel = "log/journal/%s-%s.md" % (today(), slugify(text))
    if os.path.exists(os.path.join(mem.ctx.notes_root, rel)):
        rel = rel[:-3] + "-%s.md" % os.urandom(2).hex()
    nid = rel[:-3]
    cid = mg.new_claim_id(nid, text, set(corpus.claims))
    link = about["title"] if about else ("Core" if "CORE" in corpus.notes else None)
    rels = ["- relates_to [[%s]]" % link] if link else ["- relates_to [[Conventions]]"]
    mem.write_note(rel, new_note_text(text[:70].rstrip(" .") , "note", ["journal"], text,
                                      ["- [%s] %s ^%s" % (cat, text, cid)], rels))
    print("mem: remembered ^%s in %s%s" % (cid, rel, (" (about %s)" % about["title"]) if about else ""))
    return EXIT_OK


def cmd_retire(mem, a):
    corpus, _ = mem.corpus(trial=None)
    cid = a.id.lstrip("^")
    if cid not in corpus.claims:
        die("no live claim ^%s" % cid)
    nid, c = corpus.claims[cid]
    n = corpus.notes[nid]
    allowed, need, have = mem.can_write(n["path"])
    if not allowed:
        rel = proposal(mem, "Retire claim %s" % cid, n["path"], "Retire ^%s: %s" % (cid, c["text"]),
                       "Replaced by ^%s." % a.by.lstrip("^") if a.by else "")
        print("mem: %s is %s and you write %s - proposal written: %s" % (n["title"], need, have, rel))
        return EXIT_OK
    path = os.path.join(mem.ctx.notes_root, n["path"])
    fm, body = mg.split_frontmatter(mg.read_text(path))
    why = "by %s%s" % (mem.acting()["handle"], (", replaced by ^" + a.by.lstrip("^")) if a.by else "")
    mg.write_text(path, mg.render(fm or [], retire_line(body, cid, why)))
    print("mem: retired ^%s in %s (history kept under ## Retired)" % (cid, n["path"]))
    return EXIT_OK


def cmd_pin(mem, a, which, add):
    prefs = mem.local.prefs()
    key = "pins" if which == "pin" else "mutes"
    items = set(prefs.get(key, []))
    target = a.target.strip()
    (items.add if add else items.discard)(target)
    prefs[key] = sorted(items)
    mem.local.write_json("prefs.json", prefs)
    verb = {("pin", True): "pinned", ("pin", False): "unpinned",
            ("mute", True): "muted", ("mute", False): "unmuted"}[(which, add)]
    print("mem: %s %s - personal, affects only your own recall and loads. Team-wide pins belong in CORE.md."
          % (verb, target))
    return EXIT_OK


def cmd_why(mem, a):
    corpus, _ = mem.corpus(trial=None)
    cid = a.id.lstrip("^")
    hit = corpus.claims.get(cid)
    first = mg.git("-C", mem.ctx.repo_root, "log", "--reverse", "-S", "^" + cid,
                   "--format=%h %ad %an: %s", "--date=short").splitlines()
    if not hit:
        retired = [n for n in corpus.notes.values() if re.search(r"\^%s\b" % cid, n["body"])]
        if retired:
            print("^%s is retired in %s" % (cid, retired[0]["path"]))
        elif first:
            print("^%s no longer exists. History:" % cid)
            for ln in first[-5:]:
                print("  " + ln)
        else:
            print("mem: no claim ^%s anywhere in this memory or its history" % cid)
        return EXIT_OK
    nid, c = hit
    n = corpus.notes[nid]
    print("^%s [%s] %s" % (cid, c["category"], c["text"]))
    print("  note     : %s  (%s, %s)" % (n["path"], n["type"], n["level"] or "?"))
    print("  authority: %.1f   state: %s" % (authority(n), "retired" if c["retired"] else "belief"))
    if first:
        print("  added    : %s" % first[0])
        if len(first) > 1:
            print("  last     : %s" % first[-1])
    else:
        print("  added    : not committed yet")
    refs = [x["title"] for x in corpus.notes.values()
            if x["id"] != nid and re.search(r"\^%s\b" % cid, x["text"])]
    if refs:
        print("  cited by : %s" % ", ".join(refs))
    return EXIT_OK


def cmd_gap(mem, a):
    corpus, _ = mem.corpus(trial=None)
    text = re.sub(r"\s+", " ", a.what).strip()
    feat = corpus.find(a.feature) if a.feature else None
    if a.feature and not feat:
        die("no feature %r" % a.feature)
    if not feat:
        ranked, confident = resolve(mem, corpus, text)
        feat = ranked[0][1] if ranked and confident else None
    slug = slugify(feat["title"]) if feat else "general"
    rel = "log/gaps/%s.md" % slug
    existing = corpus.notes.get(rel[:-3])
    if existing:
        for c in existing["claims"]:
            if c["category"] == "gap" and mg.jaccard(mg._claim_tokens(c["text"]), mg._claim_tokens(text)) >= 0.85:
                print("mem: already recorded as ^%s" % c["id"])
                return EXIT_OK
    cid = mg.new_claim_id(rel[:-3], text, set(corpus.claims))
    line = "- [gap] %s ^%s" % (text, cid)
    if existing:
        path = os.path.join(mem.ctx.notes_root, rel)
        fm, body = mg.split_frontmatter(mg.read_text(path))
        mg.write_text(path, mg.render(fm or [], insert_claim(body, line)))
    else:
        title = "Gaps - %s" % (feat["title"] if feat else "General")
        link = feat["title"] if feat else ("Core" if "CORE" in corpus.notes else "Conventions")
        mem.write_note(rel, new_note_text(title, "gaps", ["gap"],
                                          "What agents needed and the memory did not have.",
                                          [line], ["- relates_to [[%s]]" % link]))
    print("mem: gap ^%s recorded in %s" % (cid, rel))
    return EXIT_OK


def cmd_gaps(mem, a):
    corpus, _ = mem.corpus(trial=None)
    rows = [(n["title"], c) for n in corpus.notes.values() for c in n["claims"]
            if c["category"] == "gap" and not c["retired"]]
    if not rows:
        print("mem: no gaps recorded.")
        return EXIT_OK
    print("%d gap(s) - what agents needed and the memory did not have:" % len(rows))
    for t, c in rows:
        print("  ^%s  %s  (%s)" % (c["id"] or "?", c["text"], t))
    return EXIT_OK


FEATURE_TEMPLATE = """---
title: {title}
type: feature
status: {status}
owner: {owner}
covers: [{covers}]
aliases: []
tags: [feature]
---

# {title}

## Card
<!-- TODO: fill in - at most 150 words: what it is, who it serves, current state, what is in flight. -->

## Contract
<!-- TODO: fill in - what this feature promises to the features that depend on it. A change here alerts them. -->

## Observations
- [fact] Created {date}

## Relations
{relations}
"""


def cmd_feature(mem, a):
    corpus, _ = mem.corpus(trial=None)
    if a.action == "list" or not a.name:
        return cmd_features(mem, a)
    title = a.name.strip()
    if corpus.find(title):
        die("a note called %r already exists" % title)
    rels = ["- depends_on [[%s]]" % d for d in (a.depends or [])] or \
           ["- part_of [[%s]]" % corpus.notes["CORE"]["title"] if "CORE" in corpus.notes else "- relates_to [[Conventions]]"]
    covers = [c.replace("\\", "/") for c in (a.covers or [])]
    text = FEATURE_TEMPLATE.format(title=title, status=a.status or "planned",
                                   owner=a.owner or mem.acting()["handle"],
                                   covers=", ".join('"%s"' % c for c in covers), date=today(),
                                   relations="\n".join(rels))
    rel = "features/%s.md" % slugify(title, 8)
    allowed, need, have = mem.can_write(rel)
    if not allowed:
        prel = proposal(mem, "New feature %s" % title, rel, "Create feature %s" % title,
                        "Proposed by %s." % mem.acting()["handle"], kind="feature", payload=text)
        print("mem: features are %s and you write %s - proposal written: %s" % (need, have, prel))
        return EXIT_OK
    mem.write_note(rel, text)
    root = mg.code_root(mem.ctx)
    if root and covers:
        files = mg.code_files(root)
        for g in covers:
            n = sum(1 for x in files if mg.glob_match(g, x))
            print("  covers %-30s %d file(s)%s" % (g, n, "   <- matches nothing" if n == 0 else ""))
    print("mem: created %s - fill in its Card and Contract" % rel)
    return EXIT_OK


def cmd_features(mem, a):
    corpus, _ = mem.corpus(trial=None)
    feats = corpus.features(include_retired=True)
    if not feats:
        print("mem: no features yet. mem feature new \"<name>\" --covers \"src/x/**\"")
        return EXIT_OK
    for f in sorted(feats, key=lambda x: x["title"].lower()):
        ups = [corpus.notes[t]["title"] for t in corpus.up[f["id"]] if corpus.notes[t]["type"] == "feature"]
        downs = [corpus.notes[t]["title"] for t in corpus.down[f["id"]] if corpus.notes[t]["type"] == "feature"]
        print("%-30s %-9s owner %-10s covers %d%s%s" % (
            f["title"], f["status"] or "?", f["owner"] or "?", len(f["covers"]),
            ("  relies on: " + ", ".join(ups)) if ups else "",
            ("  relied on by: " + ", ".join(downs)) if downs else ""))
    return EXIT_OK


def cmd_propose(mem, a):
    rel = proposal(mem, a.title, a.target, a.text, a.why or "")
    print("mem: proposal written: %s" % rel)
    return EXIT_OK


def cmd_approve(mem, a):
    corpus, _ = mem.corpus(trial=None)
    p = corpus.find(a.proposal) or corpus.find("PROPOSAL - " + a.proposal)
    if not p or not p["path"].startswith("log/proposals/"):
        die("no proposal %r" % a.proposal)
    fm, body = mg.split_frontmatter(p["text"])
    target = mg.fm_get(fm, "target")
    kind = mg.fm_get(fm, "proposal_kind") or "text"
    if mem.ctx.actor_kind == "agent":
        die("an agent cannot approve a proposal; a person with the right role does", EXIT_DENIED)
    allowed, need, have = mem.can_write(target or "")
    if not allowed:
        die("%s is %s and you may write %s - you cannot approve this" % (target, need, have), EXIT_DENIED)
    applied = ""
    if a.apply:
        payload = re.search(r"## Payload\s*\n+````\n(.*?)\n````", body, re.S)
        if not payload:
            die("this proposal has no payload to apply; make the change by hand")
        path = os.path.join(mem.ctx.notes_root, target)
        if kind == "feature":
            mem.write_note(target, payload.group(1) + "\n")
        elif kind == "claim":
            tf, tb = mg.split_frontmatter(mg.read_text(path))
            mg.write_text(path, mg.render(tf or [], insert_claim(tb, payload.group(1).strip())))
        else:
            die("only claim and feature proposals can be applied automatically")
        applied = " and applied to %s" % target
    fm = mg.fm_set(mg.fm_set(mg.fm_set(fm, "status", "accepted"), "approved_by", mem.acting()["handle"]),
                   "approved", today())
    mg.write_text(os.path.join(mem.ctx.notes_root, p["path"]), mg.render(fm, body))
    print("mem: approved %s%s. Commit it: sync-memory post" % (p["path"], applied))
    return EXIT_OK


# --------------------------------------------------------------------------- trials

TRIAL_TEMPLATE = """---
title: Trial {slug}
type: trial
status: live
hypothesis: {hypothesis}
owner: {owner}
for: [{people}]
expires: {expires}
evals: [{evals}]
tags: [trial]
---

# Trial: {hypothesis}

Opened {date}. Applies to the people in `for:` automatically, or to anyone who loads `--ref trial/{slug}`.

## Changes
{changes}

## Relations
{relations}
"""


def cmd_try(mem, a):
    corpus, _ = mem.corpus(trial=None)
    slug = slugify(a.slug or a.hypothesis, 5)
    rel = "trials/%s.md" % slug
    if os.path.exists(os.path.join(mem.ctx.notes_root, rel)):
        die("trial %s already exists" % slug)
    changes = [c if c.lstrip().startswith("-") else "- " + c for c in (a.change or [])]
    fake = {"id": "trials/" + slug, "sections": {"changes": "\n".join(changes)}}
    ops = trial_changes(fake)
    if len(ops) != len(changes):
        die('could not read every --change. Forms: add to "Note title": [fact] text · '
            'replace ^abc123 with: [decision] text · retire ^abc123')
    touched = set()
    targets = set()
    for op in ops:
        if op["op"] == "add":
            n = corpus.find(op["target"])
            if not n:
                die("no note %r to add to" % op["target"])
            targets.add(n["title"])
        else:
            if op["id"] not in corpus.claims:
                die("no claim ^%s" % op["id"])
            touched.add(op["id"])
            targets.add(corpus.notes[corpus.claims[op["id"]][0]]["title"])
    for t in live_trials(corpus):
        other = {o.get("id") for o in trial_changes(t) if o.get("id")}
        if touched & other:
            print("mem: WARNING - live trial %s also changes %s" % (t["id"], ", ".join("^" + x for x in touched & other)))
    rels = ["- relates_to [[%s]]" % t for t in sorted(targets)] or \
           ["- relates_to [[%s]]" % corpus.notes["CORE"]["title"] if "CORE" in corpus.notes else "- relates_to [[Conventions]]"]
    expires = (TODAY + timedelta(days=a.days)).isoformat()
    mem.write_note(rel, TRIAL_TEMPLATE.format(
        slug=slug, hypothesis=re.sub(r"\s+", " ", a.hypothesis).strip().replace(":", " -"),
        owner=mem.acting()["handle"], people=", ".join(a.people or []), expires=expires,
        evals=", ".join(a.evals or []), date=today(),
        changes="\n".join(changes) or "<!-- add lines: add to \"Note\": [fact] text · replace ^id with: [cat] text · retire ^id -->",
        relations="\n".join(rels)))
    print("mem: trial %s opened, expires %s. Applies to: %s" % (slug, expires, ", ".join(a.people or []) or
                                                                  "anyone who loads --ref trial/%s" % slug))
    return EXIT_OK


def cmd_trials(mem, a):
    corpus, _ = mem.corpus(trial=None)
    ts = live_trials(corpus)
    if not ts:
        print("mem: no live trials.")
        return EXIT_OK
    claimed = {}
    for t in ts:
        for o in trial_changes(t):
            if o.get("id"):
                claimed.setdefault(o["id"], []).append(t["id"].split("/")[-1])
    for t in ts:
        print("%-28s expires %s%s  for: %s  (%d change(s))" % (
            t["id"].split("/")[-1], t["expires"], "  EXPIRED" if t["expired"] else "",
            ", ".join(t["for"]) or "-", len(trial_changes(t))))
        print("    %s" % t["hypothesis"])
    clashes = {k: v for k, v in claimed.items() if len(v) > 1}
    for k, v in clashes.items():
        print("  OVERLAP: ^%s is changed by %s" % (k, ", ".join(v)))
    return EXIT_OK


def _close_trial(mem, corpus, t, status, result):
    path = os.path.join(mem.ctx.notes_root, t["path"])
    fm, body = mg.split_frontmatter(mg.read_text(path))
    fm = mg.fm_set(mg.fm_set(fm, "status", status), "closed", today())
    mg.write_text(path, mg.render(fm, body))
    slug = t["id"].split("/")[-1]
    rel = "log/journal/%s-trial-%s-%s.md" % (today(), slug, status)
    nid = rel[:-3]
    text = "Trial %s was %s: %s" % (slug, status, re.sub(r"\s+", " ", result).strip())
    claims = ["- [%s] %s ^%s" % ("decision" if status == "kept" else "fact", text,
                                  mg.new_claim_id(nid, text, set(corpus.claims))),
              "- [fact] Hypothesis was: %s ^%s" % (t["hypothesis"], mg.new_claim_id(nid, t["hypothesis"] or "", set(corpus.claims)))]
    if t["for"]:
        claims.append("- [fact] Applied to %s ^%s" % (", ".join(t["for"]), mg.new_claim_id(nid, "for" + ",".join(t["for"]), set(corpus.claims))))
    mem.write_note(rel, new_note_text("Trial %s %s" % (slug, status), "note", ["journal", "trial"],
                                      text, claims, ["- relates_to [[Trial %s]]" % slug]))
    return rel


def cmd_keep(mem, a):
    corpus, _ = mem.corpus(trial=None)
    t = next((x for x in live_trials(corpus) if x["id"].endswith("/" + a.slug)), None)
    if not t:
        die("no live trial %r" % a.slug)
    ops = trial_changes(t)
    # Keeping is governed by the HIGHEST level any change touches, through the ordinary rules.
    for op in ops:
        n = corpus.find(op["target"]) if op["op"] == "add" else corpus.notes[corpus.claims[op["id"]][0]] \
            if op.get("id") in corpus.claims else None
        if not n:
            die("change %s no longer applies - the note or claim is gone" % op)
        allowed, need, have = mem.can_write(n["path"])
        if not allowed:
            die("keeping this trial changes %s (%s); you write %s. Someone with that role runs mem keep %s"
                % (n["title"], need, have, a.slug), EXIT_DENIED)
    for op in ops:
        if op["op"] == "add":
            n = corpus.find(op["target"])
            path = os.path.join(mem.ctx.notes_root, n["path"])
            fm, body = mg.split_frontmatter(mg.read_text(path))
            line = "- [%s] %s ^%s" % (op["category"], op["text"], fresh_id(corpus, n["id"], op["text"]))
            mg.write_text(path, mg.render(fm or [], insert_claim(body, line)))
        else:
            n = corpus.notes[corpus.claims[op["id"]][0]]
            path = os.path.join(mem.ctx.notes_root, n["path"])
            fm, body = mg.split_frontmatter(mg.read_text(path))
            if op["op"] == "replace":
                body = re.sub(r"^\s*-\s*\[[\w-]+\].*\^%s\s*$" % re.escape(op["id"]),
                              "- [%s] %s ^%s" % (op["category"], op["text"], op["id"]), body, flags=re.M)
            else:
                body = retire_line(body, op["id"], "trial %s kept" % a.slug)
            mg.write_text(path, mg.render(fm or [], body))
    rel = _close_trial(mem, corpus, t, "kept", a.result or "the changes became the team's belief")
    print("mem: trial %s kept - %d change(s) applied to the real notes; result recorded in %s" % (a.slug, len(ops), rel))
    return EXIT_OK


def cmd_drop(mem, a):
    corpus, _ = mem.corpus(trial=None)
    t = next((x for x in live_trials(corpus) if x["id"].endswith("/" + a.slug)), None)
    if not t:
        die("no live trial %r" % a.slug)
    if not a.result:
        die("say what happened: mem drop %s --result \"...\" - a dropped trial is memory of what did not work" % a.slug)
    rel = _close_trial(mem, corpus, t, "dropped", a.result)
    print("mem: trial %s dropped; what was tried and what happened is recorded in %s" % (a.slug, rel))
    return EXIT_OK


def cmd_expire(mem, a):
    corpus, _ = mem.corpus(trial=None)
    n = 0
    for t in live_trials(corpus):
        if t["expired"]:
            _close_trial(mem, corpus, t, "dropped", "expired on %s without a decision" % t["expires"])
            n += 1
    if n or not a.quiet:
        print("mem: %d expired trial(s) closed" % n)
    return EXIT_OK


# --------------------------------------------------------------------------- evals

# Ids in an eval go in parentheses - `includes (^a ^b)` - so the line never ENDS with a reference,
# which would otherwise be read as the eval's own claim id.
EVAL_RECALL = re.compile(r'^recall\s+"([^"]+)"\s+includes\s+\(?((?:\^[0-9a-f]{6}\s*)+)\)?\s*'
                         r'(?:excludes\s+\(?((?:\^[0-9a-f]{6}\s*)+)\)?\s*)?(?:top\s+(\d+))?', re.I)
EVAL_RESOLVE = re.compile(r'^resolve\s+"([^"]+)"(?:\s+touching\s+"([^"]+)")?\s+feature\s+"([^"]+)"(?:\s+mode\s+(\w+))?', re.I)


def run_evals(mem, corpus, files=None):
    results = []
    for n in corpus.notes.values():
        if not n["path"].startswith("evals/"):
            continue
        if files and n["path"] not in files and n["id"] not in files:
            continue
        for c in n["claims"]:
            if c["category"] != "eval" or c["retired"]:
                continue
            spec = re.sub(r"\s+", " ", c["text"]).strip()
            m = EVAL_RECALL.match(spec)
            if m:
                q = m.group(1)
                inc = re.findall(r"[0-9a-f]{6}", m.group(2))
                exc = re.findall(r"[0-9a-f]{6}", m.group(3) or "")
                top = int(m.group(4) or 15)
                got = [h[1] for h in recall(mem, corpus, q, top)]
                miss = [x for x in inc if x not in got]
                bad = [x for x in exc if x in got]
                results.append((n["title"], spec, not miss and not bad,
                                ("missing " + " ".join("^" + x for x in miss) if miss else "") +
                                (" unwanted " + " ".join("^" + x for x in bad) if bad else "")))
                continue
            m = EVAL_RESOLVE.match(spec)
            if m:
                ask, touch, want, want_mode = m.group(1), m.group(2), m.group(3), m.group(4)
                ranked, confident = resolve(mem, corpus, ask, [touch] if touch else [])
                got = ranked[0][1]["title"] if ranked else None
                mode, _ = detect_mode(ask, None, mem.proto.get("extra_symptoms") or ())
                okf = (got or "").lower() == want.lower() and confident
                okm = (not want_mode) or mode == want_mode
                detail = "got %s%s, mode %s" % (got, "" if confident else " (not confident)", mode)
                results.append((n["title"], spec, okf and okm, "" if okf and okm else detail))
                continue
            results.append((n["title"], spec, False, "unreadable eval - see `mem eval --help`"))
    return results


def cmd_eval(mem, a):
    files = [a.file] if a.file else None
    base, _ = mem.corpus(trial=None)
    res = run_evals(mem, base, files)
    if not res:
        print("mem: no evals found. Add `- [eval] recall \"<question>\" includes ^id` lines under evals/.")
        return EXIT_OK
    trial_res = None
    if a.trial:
        tc, _ = mem.corpus("trial/" + a.trial)
        trial_res = run_evals(mem, tc, files)
    passed = sum(1 for r in res if r[2])
    print("%d/%d evals pass on main" % (passed, len(res)))
    for i, (src, spec, okk, detail) in enumerate(res):
        line = "  %s %s%s" % ("PASS" if okk else "FAIL", spec[:96], ("   <- " + detail) if detail else "")
        if trial_res:
            t_ok = trial_res[i][2]
            line += "   | trial: %s%s" % ("PASS" if t_ok else "FAIL",
                                          "  (CHANGED)" if t_ok != okk else "")
        print(line)
    if trial_res:
        tp = sum(1 for r in trial_res if r[2])
        print("trial %s: %d/%d (%+d vs main)" % (a.trial, tp, len(trial_res), tp - passed))
        return EXIT_OK if tp >= passed else EXIT_FAIL
    return EXIT_OK if passed == len(res) else EXIT_FAIL


# --------------------------------------------------------------------------- awareness

def cmd_diff(mem, a):
    old, oref = mem.corpus(a.since or "HEAD~1", trial=None)
    new, nref = mem.corpus(a.to, trial=None)

    def beliefs(c):
        out = {}
        for n in c.notes.values():
            for cl in n["claims"]:
                if cl["id"] and not cl["retired"]:
                    out[cl["id"]] = (n["title"], cl["category"], cl["text"])
        return out
    b0, b1 = beliefs(old), beliefs(new)
    added = [k for k in b1 if k not in b0]
    gone = [k for k in b0 if k not in b1]
    changed = [k for k in b1 if k in b0 and b1[k][2] != b0[k][2]]
    print("Beliefs %s -> %s: %d added, %d retired or removed, %d changed"
          % (oref["label"], nref["label"], len(added), len(gone), len(changed)))
    for k in added:
        print("  + ^%s [%s] %s  (%s)" % (k, b1[k][1], b1[k][2], b1[k][0]))
    for k in gone:
        print("  - ^%s [%s] %s  (%s)" % (k, b0[k][1], b0[k][2], b0[k][0]))
    for k in changed:
        print("  ~ ^%s %s\n        was: %s" % (k, b1[k][2], b0[k][2]))
    return EXIT_OK


def cmd_status(mem, a):
    corpus, _ = mem.corpus(trial=None)
    props = [n for n in corpus.notes.values() if n["path"].startswith("log/proposals/") and (n["status"] or "open") == "open"]
    review = []
    for n in corpus.notes.values():
        fm, _b = mg.split_frontmatter(n["text"])
        if fm and mg.fm_get(fm, "review_needed"):
            review.append(n)
    gaps = [c for n in corpus.notes.values() for c in n["claims"] if c["category"] == "gap" and not c["retired"]]
    trials = live_trials(corpus)
    expiring = [t for t in trials if parse_date(t["expires"]) and parse_date(t["expires"]) <= TODAY + timedelta(days=3)]
    feats = corpus.features()
    print("%d proposal(s) waiting · %d note(s) need re-reading · %d gap(s) · %d live trial(s)%s · %d feature(s)"
          % (len(props), len(review), len(gaps), len(trials),
             (" (%d expiring within 3 days)" % len(expiring)) if expiring else "", len(feats)))
    for p in props[:5]:
        print("  waiting   %s" % p["title"])
    for r in review[:5]:
        print("  re-read   %s" % r["title"])
    for t in expiring:
        print("  expiring  %s on %s" % (t["id"].split("/")[-1], t["expires"]))
    return EXIT_OK


def cmd_brief(mem, a):
    corpus, ref = mem.corpus(trial=None)
    print("# Brief · %s\n" % ref["label"])
    if "CORE" in corpus.notes:
        print(brief_of(corpus.notes["CORE"]["body"]) or "")
        print()
    print(feature_map(corpus))
    decisions = [n for n in corpus.notes.values() if n["path"].startswith("decisions/ADR-")]
    if decisions:
        print("## Decisions\n")
        for d in decisions:
            print("- %s (%s)" % (d["title"], d["status"] or "?"))
        print()
    cmd_status(mem, a)
    return EXIT_OK


def cmd_who(mem, a):
    people = mem.ctx.policy.get("people", {})
    print("%-12s %-20s %-12s %-8s %-6s %s" % ("handle", "name", "role", "function", "restr.", "projects"))
    for h, p in people.items():
        if h.startswith(("$", "__")) or not isinstance(p, dict):
            continue
        print("%-12s %-20s %-12s %-8s %-6s %s" % (h, p.get("name", "")[:20], p.get("role", ""),
                                                  p.get("function") or "-", "yes" if p.get("restricted_read") else "no",
                                                  ", ".join(p.get("projects", []))))
    placeholders = [h for h in people if h.startswith("__")]
    if placeholders:
        print("\n%d placeholder(s) in governance/roles.json still to fill in." % len(placeholders))
    return EXIT_OK


def cmd_can(mem, a):
    people = mem.ctx.policy.get("people", {})
    p = people.get(a.handle)
    if not isinstance(p, dict):
        die("no person %r in governance/roles.json" % a.handle)
    rel = a.path.replace("\\", "/")
    need = mem.ctx.path_level((mem.ctx.prefix + rel) if mem.ctx.prefix else rel)
    roles = mem.ctx.policy.get("roles", {})
    human = (roles.get(p.get("role")) or {}).get("max_level")
    agent = mg.min_level(human, (roles.get("agent") or {}).get("max_level", "L0"))
    print("%s is %s (%s)" % (rel, need, mem.ctx.path_reason((mem.ctx.prefix + rel) if mem.ctx.prefix else rel) or "default"))
    print("  %s committing directly : %s" % (a.handle, "yes" if mg.level_allows(human, need) else "no (max %s)" % human))
    print("  %s's agent             : %s" % (a.handle, "yes" if mg.level_allows(agent, need) else "no - writes a proposal instead"))
    return EXIT_OK


def cmd_role(mem, a):
    me = mem.acting()
    if me["kind"] == "agent" or me["role"] != "owner":
        die("only an owner, acting directly and not through an agent, can change roles", EXIT_DENIED)
    roles = mem.ctx.policy.get("roles", {})
    if a.role not in roles or a.role.startswith("$"):
        die("unknown role %r; one of %s" % (a.role, ", ".join(roles.get("order", []))))
    path = mem.ctx.policy_path
    text = mg.read_text(path)
    m = re.search(r'("%s"\s*:\s*\{[^{}]*?"role"\s*:\s*")([^"]*)(")' % re.escape(a.handle), text, re.S)
    if not m:
        die("no person %r in %s" % (a.handle, path))
    old = m.group(2)
    new_text = text[:m.start(2)] + a.role + text[m.end(2):]
    json.loads(new_text)
    mg.write_text(path, new_text)
    print("mem: %s: %s -> %s in governance/roles.json. It is an L3 file: commit it with sync-memory post, "
          "and CODEOWNERS review applies." % (a.handle, old, a.role))
    return EXIT_OK


CORE_TEMPLATE = """---
title: Core
type: context
tags: [core, canonical]
---

# Core

<!-- TODO: fill in - two or three sentences: what this team builds, for whom, and why it matters. -->

Every agent reads this note first, on every task. Keep it to what everyone must know; detail belongs in
features/ and context/. The feature map below it is generated when an agent loads context, so it can
never drift. The guard warns past the size ceiling in governance/roles.json (protocol.core_max_tokens).

## Observations
- [constraint] <!-- TODO: fill in - the non-negotiables every agent must respect -->

## Relations
- relates_to [[Architecture]]
"""


def cmd_core(mem, a):
    path = os.path.join(mem.ctx.notes_root, "CORE.md")
    if os.path.exists(path):
        print("mem: CORE.md already exists (%d tokens, estimate)" % mg.estimate_tokens(mg.read_text(path)))
        return EXIT_OK
    mg.write_text(path, CORE_TEMPLATE)
    print("mem: created CORE.md - fill in what the team builds; every agent reads it first")
    return EXIT_OK


# --------------------------------------------------------------------------- CLI

def main(argv):
    ap = argparse.ArgumentParser(prog="mem", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="notes root (default: found from the current directory)")
    ap.add_argument("--session", help="session id (default: .memory/session/current)")
    ap.add_argument("--hook", action="store_true",
                    help="called from an agent hook: read the hook's JSON on stdin for session_id, so two "
                         "sessions in one checkout keep separate ledgers")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("load", help="the entry protocol: core, resolve, scope, receipt, bundle")
    p.add_argument("ask", nargs="?", default="")
    p.add_argument("--mode", choices=MODES)
    p.add_argument("--feature", action="append", help="target this note by name (repeatable)")
    p.add_argument("--add", action="append", help="add a note to the scope (repeatable)")
    p.add_argument("--touching", action="append", help="a file you are working on (repeatable)")
    p.add_argument("--ref")
    p.add_argument("--full", action="store_true", help="repeat notes already in context")
    p.add_argument("--print", action="store_true", help="print the bundle, not just its path")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("resolve"); p.add_argument("ask"); p.add_argument("--touching", action="append")
    p.add_argument("--ref"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("recall"); p.add_argument("query"); p.add_argument("--limit", type=int, default=15)
    p.add_argument("--ideas", action="store_true"); p.add_argument("--ref"); p.add_argument("--json", action="store_true")
    sub.add_parser("context")
    p = sub.add_parser("session"); p.add_argument("action", choices=["start", "evict", "show", "purge"]); p.add_argument("--id")
    p = sub.add_parser("moved"); p.add_argument("--fetch", action="store_true"); p.add_argument("--quiet", action="store_true")
    p.add_argument("--throttle", type=int)
    p = sub.add_parser("compile"); p.add_argument("--ref"); p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("remember"); p.add_argument("claim"); p.add_argument("--category")
    p.add_argument("--feature"); p.add_argument("--note")
    p = sub.add_parser("retire"); p.add_argument("id"); p.add_argument("--by")
    for name in ("pin", "unpin", "mute", "unmute"):
        p = sub.add_parser(name); p.add_argument("target")
    p = sub.add_parser("why"); p.add_argument("id")
    p = sub.add_parser("gap"); p.add_argument("what"); p.add_argument("--feature")
    sub.add_parser("gaps")
    p = sub.add_parser("feature"); p.add_argument("action", choices=["new", "list"])
    p.add_argument("name", nargs="?"); p.add_argument("--covers", action="append"); p.add_argument("--owner")
    p.add_argument("--depends", action="append"); p.add_argument("--status", choices=list(mg.FEATURE_STATUSES))
    sub.add_parser("features")
    p = sub.add_parser("propose"); p.add_argument("title"); p.add_argument("--target", required=True)
    p.add_argument("--text", required=True); p.add_argument("--why")
    p = sub.add_parser("approve"); p.add_argument("proposal"); p.add_argument("--apply", action="store_true")

    p = sub.add_parser("try"); p.add_argument("hypothesis"); p.add_argument("--for", dest="people", action="append")
    p.add_argument("--days", type=int, default=14); p.add_argument("--change", action="append")
    p.add_argument("--evals", action="append"); p.add_argument("--slug")
    sub.add_parser("trials")
    p = sub.add_parser("keep"); p.add_argument("slug"); p.add_argument("--result")
    p = sub.add_parser("drop"); p.add_argument("slug"); p.add_argument("--result")
    p = sub.add_parser("expire"); p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("eval"); p.add_argument("--trial"); p.add_argument("--file")
    p = sub.add_parser("diff"); p.add_argument("--since"); p.add_argument("--to")

    sub.add_parser("status"); sub.add_parser("brief"); sub.add_parser("who")
    p = sub.add_parser("can"); p.add_argument("handle"); p.add_argument("path")
    p = sub.add_parser("role"); p.add_argument("handle"); p.add_argument("role")
    p = sub.add_parser("core"); p.add_argument("action", choices=["init"])

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return EXIT_OK
    if a.hook:
        try:
            raw = sys.stdin.read() if not sys.stdin.isatty() else ""
            payload = json.loads(raw) if raw.strip() else {}
        except ValueError:
            payload = {}
        sid = payload.get("session_id") if isinstance(payload, dict) else None
        if sid is not None:
            try:
                check_session_id(sid)
            except SessionIdError as e:
                sys.stderr.write("mem: ignoring the hook's session id: %s\n" % e)
                return EXIT_INVALID
        if sid:
            a.session = a.session or sid
            if a.cmd == "session" and not a.id:
                a.id = sid
    mem = Mem(a)
    table = {
        "load": cmd_load, "resolve": cmd_resolve, "recall": cmd_recall, "context": cmd_context,
        "session": cmd_session, "moved": cmd_moved, "compile": cmd_compile, "remember": cmd_remember,
        "retire": cmd_retire, "why": cmd_why, "gap": cmd_gap, "gaps": cmd_gaps, "feature": cmd_feature,
        "features": cmd_features, "propose": cmd_propose, "approve": cmd_approve, "try": cmd_try,
        "trials": cmd_trials, "keep": cmd_keep, "drop": cmd_drop, "expire": cmd_expire,
        "eval": cmd_eval, "diff": cmd_diff, "status": cmd_status, "brief": cmd_brief, "who": cmd_who,
        "can": cmd_can, "role": cmd_role, "core": cmd_core,
    }
    if a.cmd in ("pin", "unpin", "mute", "unmute"):
        return cmd_pin(mem, a, "pin" if "pin" in a.cmd else "mute", not a.cmd.startswith("un"))
    return table[a.cmd](mem, a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
