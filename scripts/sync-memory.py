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
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
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


class Lock:
    """mkdir-based, the same directory the native scripts use, so either can hold it."""

    def __init__(self):
        g = git_dir()
        self.path = os.path.join(g, "sync-memory.lock") if g else None
        self.held = False

    def acquire(self):
        if not self.path:
            return True  # not a git repo: the native script will report that
        try:
            os.mkdir(self.path)
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(self.path)
            except OSError:
                age = 0
            if age < STALE_SECONDS:
                return False
            shutil.rmtree(self.path, ignore_errors=True)
            try:
                os.mkdir(self.path)
            except FileExistsError:
                return False
        with open(os.path.join(self.path, "owner"), "w") as fh:
            fh.write("pid=%d started=%s\n" % (os.getpid(), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
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

def _git(*args, check=False):
    p = subprocess.run(["git", "-C", NOTES_ROOT, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.strip()))
    return p


def repo_root():
    return _git("rev-parse", "--show-toplevel").stdout.strip()


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
    email = _git("config", "user.email").stdout.strip()
    name = email.split("@", 1)[0] if email else _git("config", "user.name").stdout.strip()
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-.") or "someone"
    return slug[:40]


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
        # Never lose work: every file the remote branch changed beyond the base must already be in
        # HEAD with the same content (a squash-merged pull request satisfies this too).
        mine = [c for c in _git("rev-list", "%s..%s" % (head, remote_sha)).stdout.split() if c]
        if mine:
            files = sorted({f for f in _git("diff", "--name-only", "%s/%s...%s" % (remote, base, remote_sha)).stdout.split("\n") if f})
            if files and _git("diff", "--quiet", remote_sha, head, "--", *files).returncode != 0:
                sys.stderr.write("[memory] %s on %s holds changes this machine does not have; not overwriting it.\n"
                                 "  Merge or close its pull request, or run: git pull %s %s\n" % (branch, remote, remote, branch))
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


def main(argv):
    agent = "--agent" in argv
    rest = [a for a in argv if a != "--agent"]
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
        try:
            rc = subprocess.call(cmd, env=env)
        except KeyboardInterrupt:
            return 130
        if rc == 0 and mode == "pre":
            after_pre(env)  # still under the lock
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
    sys.exit(main(sys.argv[1:]))
