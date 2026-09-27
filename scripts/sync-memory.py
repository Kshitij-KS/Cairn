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
  - CONTAINMENT: on Windows, an agent hook's `post` does not commit until the Windows sync chain has
    passed tools/test_sync.py on a real Windows machine. Set MEMORY_SYNC_WINDOWS_POST=1 after that.

Exit codes: 0 ok, 1 error, 2 conflict, 3 secret, 4 access denied, 5 invalid note,
            6 policy cannot be enforced, 64 bad usage, 75 another sync is running.
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NOTES_ROOT = os.path.dirname(HERE)
MODES = ("pre", "post", "status")
EXIT_BUSY = 75
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

    if os.name == "nt" and mode == "post" and agent and env.get("MEMORY_SYNC_WINDOWS_POST") != "1":
        print("[memory] Windows auto-commit is paused (2026-09 audit containment) until the sync tests "
              "pass on Windows. Your notes are saved but not committed. Run tools/test_sync.py, then set "
              "MEMORY_SYNC_WINDOWS_POST=1, or commit by hand with: uv run -q --script scripts/sync-memory.py post")
        return 0

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
        return rc
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
