# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""
sync-memory.py - cross-platform dispatcher for the hook commands.

Hooks in .claude/settings.json and .kiro/hooks/*.json are committed and shared by a mixed
Windows/macOS/Linux team, so they need ONE command string that works everywhere:

    uv run -q --script scripts/sync-memory.py pre|post|status [--agent]

It picks the native implementation (Windows: Windows PowerShell 5.1 or pwsh running
sync-memory.ps1; elsewhere: bash running sync-memory.sh) and forwards the exit code. It also:

  - normalises the mode once (no argument = pre; case-insensitive) so every platform agrees and the
    post-pre steps run for every spelling of pre (audit 06-F10);
  - holds ONE lock across native pre, `mem compile` and `mem expire`, so a concurrent post cannot
    commit half-written pack files (06-F7). A busy lock is exit 75, never a silent success;
  - with --agent sets MEMORY_ACTOR_KIND=agent, which caps the write at L0;
  - on Windows, an agent hook's `post` commits like everywhere else. It was paused until the
    Windows sync chain had passed on Windows; it now runs in CI on every change (tests.yml,
    windows-sync). MEMORY_SYNC_WINDOWS_POST=0 pauses it again on one machine;
  - PULL-REQUEST MODE, for a protected default branch. With `enforcement.mode: "pr"` in the trusted
    (HEAD) roles.json, or MEMORY_SYNC_MODE=pr, `post` commits locally as usual and then, instead of
    pushing to the default branch, pushes the unpushed memory commits to the person's own branch
    `memory/<who>` and opens (or reuses) ONE pull request for it with the GitHub CLI when `gh` is
    installed and signed in, else prints the link to open it. In direct mode a push the server
    refuses because the branch is protected falls back to the same path. The default branch is
    never force-pushed; `memory/<who>` is rewritten only with a lease, and only after checking that
    nothing on it would be lost. Once the pull request merges, the next `pre` drops the local copies
    of those commits (git rebase skips changes already upstream).

Exit codes: 0 ok, 1 error, 2 conflict, 3 secret, 4 access denied, 5 invalid note,
            6 policy cannot be enforced, 7 push refused by a protected branch (native scripts only;
            the dispatcher turns it into a pull request), 64 bad usage, 75 another sync is running.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

# realpath, never abspath: git names the repository by its real, long path, and a relpath from a
# symlinked or 8.3 short path (C:\Users\RUNNER~1) to it came out as "../../RUNNER~1/...", so every
# memory commit looked like it changed files outside the tier (found by the Windows CI job).
HERE = os.path.dirname(os.path.realpath(__file__))
NOTES_ROOT = os.path.dirname(HERE)
MODES = ("pre", "post", "status")
EXIT_BUSY = 75
EXIT_PROTECTED = 7
STALE_SECONDS = 30 * 60


def git_dir():
    try:
        out = subprocess.run(["git", "-C", NOTES_ROOT, "rev-parse", "--absolute-git-dir"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return out.stdout.strip() or None
    except OSError:
        return None


def _pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        except Exception:
            return True  # cannot tell: assume alive, so only age can free the lock
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


class Lock:
    """mkdir-based, the same directory the native scripts use, so either can hold it.

    A lock is stale when its owner is a process on THIS machine that no longer runs, or when it is
    older than 30 minutes and its owner cannot be shown to be alive. Age alone once freed the lock
    of a slow but live sync (recheck 06-F7). Stealing renames the stale directory first, which only
    one process can do, and then checks it took the lock it judged stale."""

    def __init__(self):
        g = git_dir()
        self.path = os.path.join(g, "sync-memory.lock") if g else None
        self.held = False

    @staticmethod
    def _owner(path):
        try:
            with open(os.path.join(path, "owner"), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return {}, ""
        return dict(re.findall(r"(\w+)=(\S+)", text)), text

    def _stale(self):
        try:
            age = time.time() - os.path.getmtime(self.path)
        except OSError:
            return False, ""
        info, text = self._owner(self.path)
        pid = int(info["pid"]) if info.get("pid", "").isdigit() else 0
        host = info.get("host", "")
        here = socket.gethostname()
        if pid and host == here:
            return (not _pid_alive(pid)) and age > 5, text   # the owner died (5 s: let it write)
        if pid and not host and age < STALE_SECONDS:
            return False, text                               # a native script's lock: age decides
        return age >= STALE_SECONDS, text

    def acquire(self):
        if not self.path:
            return True  # not a git repo: the native script will report that
        try:
            os.mkdir(self.path)
        except FileExistsError:
            stale, seen = self._stale()
            if not stale:
                return False
            tomb = "%s.stale-%d-%d" % (self.path, os.getpid(), int(time.time() * 1000))
            try:
                os.rename(self.path, tomb)
            except OSError:
                return False
            if self._owner(tomb)[1] != seen:          # someone replaced it between our look and our rename
                try:
                    os.rename(tomb, self.path)
                except OSError:
                    pass
                return False
            shutil.rmtree(tomb, ignore_errors=True)
            try:
                os.mkdir(self.path)
            except FileExistsError:
                return False
        with open(os.path.join(self.path, "owner"), "w") as fh:
            fh.write("pid=%d host=%s started=%s\n" % (os.getpid(), socket.gethostname(),
                                                      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        self.held = True
        return True

    def release(self):
        if self.held:
            shutil.rmtree(self.path, ignore_errors=True)
            self.held = False


def native_command(args):
    if os.name == "nt":
        # Windows PowerShell 5.1 ships with every supported Windows; prefer it so what we test is
        # what everyone runs. pwsh is the fallback.
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            sys.stderr.write("sync-memory: neither powershell nor pwsh found on PATH\n")
            return None
        return [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", os.path.join(HERE, "sync-memory.ps1"), *args]
    bash = shutil.which("bash")
    if not bash:
        sys.stderr.write("sync-memory: bash not found on PATH\n")
        return None
    return [bash, os.path.join(HERE, "sync-memory.sh"), *args]


# --------------------------------------------------------------------------- pull-request mode

_ROOT = []


def _top():
    """The repository root. Every git call runs there, so a pathspec means the same thing in a
    project tier (memory/ inside a code repository) as in the company tier: from memory/ itself a
    root-relative path like memory/x.md was read as memory/memory/x.md."""
    if not _ROOT:
        p = subprocess.run(["git", "-C", NOTES_ROOT, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
        _ROOT.append(os.path.realpath(p.stdout.strip()) if p.stdout.strip() else NOTES_ROOT)
    return _ROOT[0]


def _git(*args, check=False):
    p = subprocess.run(["git", "-c", "core.quotePath=false", "-C", _top(), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.strip()))
    return p


def repo_root():
    top = _git("rev-parse", "--show-toplevel").stdout.strip()
    return os.path.realpath(top) if top else ""


def sync_mode(env):
    """direct | pr. MEMORY_SYNC_MODE wins; else enforcement.mode from the TRUSTED policy at HEAD, never
    the working copy, so an uncommitted edit cannot change where this commit goes."""
    forced = (env.get("MEMORY_SYNC_MODE") or "").strip().lower()
    if forced in ("pr", "direct"):
        return forced
    root = repo_root()
    rel = os.path.relpath(os.path.join(NOTES_ROOT, "governance", "roles.json"), root).replace(os.sep, "/") if root else ""
    text = _git("show", "HEAD:%s" % rel).stdout if rel else ""
    try:
        mode = ((json.loads(text) if text.strip() else {}).get("enforcement") or {}).get("mode", "direct")
    except ValueError:
        mode = "direct"
    return "pr" if str(mode).strip().lower() == "pr" else "direct"


def upstream():
    """(remote, branch) of the current branch's upstream, or (None, None)."""
    up = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").stdout.strip()
    if not up or "/" not in up:
        return None, None
    remote, branch = up.split("/", 1)
    return remote, branch


def default_branch(remote):
    head = _git("symbolic-ref", "-q", "--short", "refs/remotes/%s/HEAD" % remote).stdout.strip()
    return head.split("/", 1)[1] if "/" in head else None


def on_default_branch():
    """PR mode only changes where commits to the DEFAULT branch go. A project tier riding a feature
    branch keeps pushing to that branch: its code review already carries the memory change."""
    remote, branch = upstream()
    if not remote:
        return False
    default = default_branch(remote) or "main"
    return branch == default


def who():
    """The person's own branch name: their handle in roles.json when they are registered (handles are
    unique), else the email's local part plus a short hash of the whole address, so two people
    called alex at different domains never share memory/alex (recheck C)."""
    email = _git("config", "user.email").stdout.strip()
    if email:
        root = repo_root()
        rel = os.path.relpath(os.path.join(NOTES_ROOT, "governance", "roles.json"), root).replace(os.sep, "/") if root else ""
        try:
            people = (json.loads(_git("show", "HEAD:%s" % rel).stdout or "{}").get("people") or {}) if rel else {}
        except ValueError:
            people = {}
        for handle, p in people.items():
            if isinstance(p, dict) and not handle.startswith(("$", "__")) and \
                    (p.get("email") or "").strip().lower() == email.lower():
                slug = re.sub(r"[^a-z0-9._-]+", "-", handle.lower()).strip("-.")
                if slug:
                    return slug[:40]
        local = email.split("@", 1)[0]
        slug = re.sub(r"[^a-z0-9._-]+", "-", local.lower()).strip("-.") or "someone"
        import hashlib
        return "%s-%s" % (slug[:32], hashlib.sha1(email.lower().encode("utf-8")).hexdigest()[:6])
    name = _git("config", "user.name").stdout.strip()
    return (re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-.") or "someone")[:40]


def repo_slug(remote):
    url = _git("remote", "get-url", remote).stdout.strip()
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return (m.group(1), m.group(2)) if m else (None, None)


def tier_prefix():
    root = repo_root()
    rel = os.path.relpath(NOTES_ROOT, root).replace(os.sep, "/") if root else "."
    return "" if rel == "." else rel.rstrip("/") + "/"


def pr_push(env, reason):
    """Push the unpushed memory commits to memory/<who> and make sure one pull request is open."""
    remote, base = upstream()
    if not remote:
        sys.stderr.write("sync-memory: no upstream branch; cannot open a pull request\n")
        return 1
    ahead = [c for c in _git("rev-list", "--reverse", "@{u}..HEAD").stdout.split() if c]
    if not ahead:
        print("[memory] nothing waiting to be merged.")
        return 0
    prefix = tier_prefix()
    if prefix:
        touched = {f for f in _git("log", "--format=", "--name-only", "@{u}..HEAD").stdout.split("\n") if f}
        outside = sorted(f for f in touched if not f.startswith(prefix))
        if outside:
            sys.stderr.write("[memory] not opening a pull request: unpushed commits change files outside %s: %s\n"
                             % (prefix, ", ".join(outside[:5])))
            return 0
    branch = "memory/%s" % who()
    ref = "refs/heads/%s" % branch
    tracking = "refs/remotes/%s/%s" % (remote, branch)
    fetched = _git("fetch", "--quiet", remote, "+%s:%s" % (ref, tracking)).returncode == 0
    remote_sha = _git("rev-parse", "--verify", "-q", tracking).stdout.strip() if fetched else ""
    head = _git("rev-parse", "HEAD").stdout.strip()
    if remote_sha and remote_sha != head:
        # Never lose work: every file the remote branch changed beyond its merge base must already
        # have that content in HEAD, or in the base branch. The second case is a pull request that
        # was squash-merged and whose branch was left behind: its commits are not ancestors of
        # anything, but its content is merged (recheck P2).
        mine = [c for c in _git("rev-list", "%s..%s" % (head, remote_sha)).stdout.split() if c]
        if mine:
            files = sorted({f for f in _git("diff", "--name-only", "-z", "%s/%s...%s" % (remote, base, remote_sha)).stdout.split("\0") if f})
            in_head = not files or _git("diff", "--quiet", remote_sha, head, "--", *files).returncode == 0
            in_base = not files or _git("diff", "--quiet", remote_sha, "%s/%s" % (remote, base), "--", *files).returncode == 0
            if not (in_head or in_base):
                sys.stderr.write(
                    "[memory] %s on %s holds changes that are neither here nor merged into %s; not overwriting it.\n"
                    "  Its pull request is still open or was closed unmerged: merge or close it on GitHub, then\n"
                    "  delete the branch (git push %s --delete %s) and run sync post again.\n"
                    % (branch, remote, base, remote, branch))
                return 1
    if remote_sha != head:
        lease = "--force-with-lease=%s:%s" % (ref, remote_sha)
        p = _git("push", "--quiet", lease, remote, "HEAD:%s" % ref)
        if p.returncode != 0:
            sys.stderr.write(p.stderr)
            sys.stderr.write("[memory] could not push %s; your notes are committed locally.\n" % branch)
            return 1
        _git("update-ref", tracking, head)
    owner, repo = repo_slug(remote)
    link = ("https://github.com/%s/%s/compare/%s...%s?expand=1" % (owner, repo, base, branch)) if owner else None
    gh = shutil.which("gh")
    if gh and env.get("MEMORY_SYNC_NO_GH") != "1":
        root = repo_root()
        lst = subprocess.run([gh, "pr", "list", "--head", branch, "--base", base, "--state", "open",
                              "--json", "url", "-q", ".[0].url"], cwd=root, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        url = lst.stdout.strip() if lst.returncode == 0 else ""
        if lst.returncode == 0 and not url:
            body = ("Memory notes from %s, opened by the Cairn sync (%s).\n\n"
                    "The memory-gate check classifies the level this change needs; L0 merges on its own "
                    "when enforcement.auto_merge_levels allows it, anything higher waits for its reviewer." % (who(), reason))
            cr = subprocess.run([gh, "pr", "create", "--base", base, "--head", branch,
                                 "--title", "memory: notes from %s" % who(), "--body", body],
                                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            url = cr.stdout.strip().splitlines()[-1] if cr.returncode == 0 and cr.stdout.strip() else ""
        if url:
            print("[memory] %d commit(s) waiting for review in %s" % (len(ahead), url))
            return 0
    print("[memory] %d commit(s) pushed to %s. Open the pull request: %s"
          % (len(ahead), branch, link or ("%s -> %s on %s" % (branch, base, remote))))
    return 0


def _z(out):
    return [x for x in out.split("\0") if x]


def drop_merged_commits():
    """Drop local commits whose content upstream already has (recheck P1).

    A squash-merged pull request lands as ONE new commit upstream; the local commits it came from
    are not ancestors of it, so `pull --rebase` replays them onto content that already contains them
    and the second edit of a file conflicts with its own result. Here: find the longest run of the
    oldest unpushed commits whose files already read the same upstream, and move past them. Only
    memory commits are touched, and nothing is dropped unless its content is upstream byte for byte."""
    remote, base = upstream()
    if not remote:
        return
    # Only when something is waiting: Stop hooks run this every turn, and a fetch is a round-trip.
    if not _git("rev-list", "-1", "@{u}..HEAD").stdout.strip():
        return
    if _git("fetch", "--quiet", remote).returncode != 0:
        return
    commits = [c for c in _git("rev-list", "--reverse", "@{u}..HEAD").stdout.split() if c]
    if not commits:
        return
    prefix = tier_prefix()
    touched, contained = set(), 0
    for i, c in enumerate(commits):
        files = set(_z(_git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", c).stdout))
        if prefix and any(not f.startswith(prefix) for f in files):
            break                                  # an application commit: never ours to move
        touched |= files
        if touched and _git("diff", "--quiet", c, "@{u}", "--", *sorted(touched)).returncode == 0:
            contained = i + 1
    if not contained:
        return
    upto = commits[contained - 1]
    if contained == len(commits):
        p = _git("reset", "--quiet", "--keep", "@{u}")
    elif _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return                                     # a dirty tree: let the normal pull handle it
    else:
        p = _git("rebase", "--quiet", "--onto", "@{u}", upto)
        if p.returncode != 0:
            _git("rebase", "--abort")
            return
    if p.returncode == 0:
        print("[memory] %d local commit(s) were already merged upstream (a squashed pull request); "
              "moved past them." % contained, flush=True)


def save_index():
    """The staged entries, so a pull's autostash cannot silently unstage them (recheck N1)."""
    head = _git("rev-parse", "-q", "--verify", "HEAD").stdout.strip()
    paths = _z(_git("diff", "--cached", "--name-only", "-z", "--no-renames").stdout)
    if not head or not paths:
        return None
    tree = _git("write-tree").stdout.strip()
    return {"head": head, "tree": tree, "paths": paths} if tree else None


def restore_index(saved, skip_prefix=None):
    """Re-stage what was staged before, for every path upstream did not change meanwhile."""
    if not saved:
        return
    head = _git("rev-parse", "-q", "--verify", "HEAD").stdout.strip()
    lost = []
    for p in saved["paths"]:
        if skip_prefix is not None and (skip_prefix == "" or p.startswith(skip_prefix)):
            continue                               # committed by this post
        if head != saved["head"] and _git("diff", "--quiet", saved["head"], head, "--", p).returncode != 0:
            lost.append(p)
            continue
        entry = _git("ls-tree", "-r", "-z", saved["tree"], "--", p).stdout
        if entry:
            r = subprocess.run(["git", "-C", _top(), "update-index", "-z", "--index-info"], input=entry,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        else:
            r = _git("update-index", "--force-remove", "--", p)
        if r.returncode != 0:
            lost.append(p)
    if lost:
        sys.stderr.write("[memory] the pull changed files you had staged; stage these again: %s\n" % ", ".join(lost[:8]))


def after_pre(env):
    mem = os.path.join(HERE, "mem.py")
    if not os.path.isfile(mem):
        return
    for step in (["compile", "--quiet"], ["expire", "--quiet"]):
        try:
            r = subprocess.run([sys.executable, mem, "--root", NOTES_ROOT, *step], env=env, timeout=60)
            if r.returncode != 0:
                sys.stderr.write("sync-memory: mem %s exited %d (ignored)\n" % (step[0], r.returncode))
        except (OSError, subprocess.SubprocessError) as exc:
            sys.stderr.write("sync-memory: mem %s did not run: %s (ignored)\n" % (step[0], exc))


def run_side(env, argv, stdin_text=None):
    """A companion command in the SAME hook, in a fixed order (Kiro executes a file's hooks in an order
    it does not promise, recheck 09-F9). Its output goes to the agent's context; it never fails the
    sync."""
    try:
        p = subprocess.run([sys.executable, *argv], env=env, input=stdin_text or "", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=60)
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write("sync-memory: %s did not run: %s (ignored)\n" % (os.path.basename(argv[0]), exc))


def main(argv):
    agent = "--agent" in argv
    then_session = "--then-session" in argv        # pre, then `mem session start`
    significance = "--significance" in argv        # `memory_guard significance`, then post
    rest = [a for a in argv if a not in ("--agent", "--then-session", "--significance")]
    mode = (rest[0] if rest else "pre").strip().lower()
    if mode not in MODES:
        sys.stderr.write("sync-memory: usage: sync-memory.py pre|post|status [--agent]\n")
        return 64
    env = dict(os.environ)
    if agent:
        env["MEMORY_ACTOR_KIND"] = "agent"
        env.setdefault(
            "MEMORY_AGENT",
            "claude-code" if os.environ.get("CLAUDE_CODE_ENTRYPOINT") or os.environ.get("CLAUDE_CODE_SESSION_ID")
            else ("kiro" if os.environ.get("KIRO_AGENT") else "unknown"),
        )

    if os.name == "nt" and mode == "post" and agent and env.get("MEMORY_SYNC_WINDOWS_POST") == "0":
        print("[memory] Windows auto-commit is paused on this machine (MEMORY_SYNC_WINDOWS_POST=0). Your notes "
              "are saved but not committed. Commit by hand with: uv run -q --script scripts/sync-memory.py post")
        return 0

    if significance and mode == "post":
        run_side(env, [os.path.join(HERE, "memory_guard.py"), "--notes-root", NOTES_ROOT, "significance", "--format", "text"],
                 sys.stdin.read() if not sys.stdin.isatty() else "")
    pr_mode = mode == "post" and sync_mode(env) == "pr" and on_default_branch()
    if pr_mode:
        env["MEMORY_SYNC_DIRECT_PUSH"] = "0"   # the native script commits and rebases; we push
    cmd = native_command([mode])
    if cmd is None:
        return 1
    lock = Lock()
    if mode != "status":
        if not lock.acquire():
            sys.stderr.write("sync-memory: another sync is running (lock %s); not syncing now.\n" % lock.path)
            return EXIT_BUSY
        env["MEMORY_SYNC_LOCK_HELD"] = "1"
    try:
        saved = None
        if mode != "status":
            drop_merged_commits()
            saved = save_index()
        try:
            rc = subprocess.call(cmd, env=env)
        except KeyboardInterrupt:
            return 130
        if saved and rc in (0, EXIT_PROTECTED):
            restore_index(saved, skip_prefix=tier_prefix() if mode == "post" else None)
        if rc == 0 and mode == "pre":
            after_pre(env)  # still under the lock
        if then_session and mode == "pre":
            run_side(env, [os.path.join(HERE, "mem.py"), "--root", NOTES_ROOT, "session", "start"])
        if mode == "post" and rc == 0 and pr_mode:
            return pr_push(env, "enforcement.mode is pr")
        if mode == "post" and rc == EXIT_PROTECTED:
            print("[memory] the default branch is protected, so this goes through a pull request. "
                  "Set enforcement.mode to \"pr\" in governance/roles.json to skip the failed push.")
            return pr_push(env, "the default branch refused a direct push")
        return rc
    finally:
        lock.release()


if __name__ == "__main__":
    # A Windows console is cp1252 by default; a note title or message it cannot encode must print
    # escaped, not end the run in UnicodeEncodeError.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="backslashreplace")
    sys.exit(main(sys.argv[1:]))
