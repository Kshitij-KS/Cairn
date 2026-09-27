# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
init.py - turn a fresh clone of the Cairn template into your team's memory.

    uv run -q --script scripts/init.py                       # asks for what it needs
    uv run -q --script scripts/init.py --name "Ada Lovelace" --email ada@example.test \
        --github ada-l [--handle ada] [--org my-org] [--repo cairn] [--project cairn] --yes

What it does, in order:
  1. records you as the owner in governance/roles.json (handle, name, email, GitHub login),
     sets the organisation and repository names, and marks the repository as an instance;
  2. fills the owner placeholders in the starter notes;
  3. names the Basic Memory project in .basic-memory/project.json;
  4. creates the git repository if there is none, and sets this repository's git identity to you
     (so commits here are attributed correctly even if your machine uses another identity);
  5. writes .github/CODEOWNERS from the owners in roles.json;
  6. stamps every note with you as its author;
  7. removes the open-source project's README, CONTRIBUTING and SECURITY files from .github/, so the
     repository's front page is the team guide (README.md). LICENSE, LICENSE-NOTES and NOTICE stay.

It refuses to run twice (an initialised instance has "instance": true in roles.json) unless you
pass --force. Standard library only.

Exit codes: 0 done, 5 invalid or missing input, 6 a step failed.
"""
import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROLES = os.path.join(ROOT, "governance", "roles.json")
MANIFEST = os.path.join(ROOT, ".basic-memory", "project.json")
NOTE_ROOTS = ("CORE.md", "README.md", "RUNBOOK.md", "ARCHITECTURE.md", "CLAUDE.md", "context", "decisions",
              "features", "projects", "log", "governance")

TEMPLATE_ONLY = (".github/README.md", ".github/CONTRIBUTING.md", ".github/SECURITY.md", ".github/ISSUE_TEMPLATE",
                 ".github/pull_request_template.md", ".github/assets")

EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GITHUB_RX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
HANDLE_RX = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
NAME_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def fail(msg, code=5):
    sys.stderr.write("cairn init: %s\n" % msg)
    sys.exit(code)


def ask(label, current, interactive):
    if current or not interactive:
        return current
    try:
        return input("%s: " % label).strip()
    except EOFError:
        return ""


def git(*args, check=True):
    p = subprocess.run(["git", "-C", ROOT, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8")
    if check and p.returncode != 0:
        fail("git %s failed: %s" % (" ".join(args), p.stderr.strip()), 6)
    return p


def replace_in_notes(pairs):
    changed = 0
    for entry in NOTE_ROOTS:
        base = os.path.join(ROOT, entry)
        paths = [base] if os.path.isfile(base) else [
            os.path.join(dp, f) for dp, _dn, fns in os.walk(base) for f in fns if f.endswith(".md")]
        for p in paths:
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            new = text
            for a, b in pairs:
                new = new.replace(a, b)
            if new != text:
                with open(p, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(new)
                changed += 1
    return changed


def main(argv):
    ap = argparse.ArgumentParser(prog="init.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="your name, as teammates know you")
    ap.add_argument("--email", help="the email your commits to this repository will use")
    ap.add_argument("--github", help="your GitHub login")
    ap.add_argument("--handle", help="short id used in notes (default: GitHub login, lower case)")
    ap.add_argument("--org", help="GitHub owner of the repository: an organisation or your login (default: --github)")
    ap.add_argument("--repo", help="repository name (default: this folder's name)")
    ap.add_argument("--project", help="Basic Memory project name (default: the repository name, lower case)")
    ap.add_argument("--yes", action="store_true", help="do not ask; fail if anything is missing")
    ap.add_argument("--force", action="store_true", help="run again on an already initialised instance")
    a = ap.parse_args(argv)

    with open(ROLES, encoding="utf-8") as fh:
        pol = json.load(fh, object_pairs_hook=collections.OrderedDict)
    if pol.get("instance") and not a.force:
        fail("this repository is already initialised (roles.json has \"instance\": true). "
             "Change owners in governance/roles.json directly, or pass --force.")
    if "__OWNER__" not in pol.get("people", {}) and not a.force:
        fail("roles.json has no __OWNER__ placeholder row; is this the Cairn template?")

    interactive = sys.stdin.isatty() and not a.yes
    name = ask("Your name", a.name, interactive)
    email = ask("Your email (the one you commit with here)", a.email, interactive)
    github = ask("Your GitHub login", a.github, interactive)
    missing = [k for k, v in (("--name", name), ("--email", email), ("--github", github)) if not v]
    if missing:
        fail("missing %s" % ", ".join(missing))
    if not EMAIL_RX.match(email) or "__todo" in email.lower():
        fail("%r is not a usable email address" % email)
    if not GITHUB_RX.match(github) or "__todo" in github.lower():
        fail("%r is not a valid GitHub login" % github)
    handle = (a.handle or github).lower()
    if not HANDLE_RX.match(handle):
        fail("handle %r must be 2-32 characters: lower-case letters, digits, '-' or '_', starting with a letter" % handle)
    org = a.org or github
    if not GITHUB_RX.match(org):
        fail("%r is not a valid GitHub organisation or login" % org)
    repo = a.repo or os.path.basename(ROOT)
    if not re.match(r"^[A-Za-z0-9._-]{1,100}$", repo):
        fail("%r is not a valid repository name" % repo)
    project = (a.project or repo).lower()
    if not NAME_RX.match(project):
        fail("Basic Memory project name %r must be lower case letters, digits, '.', '_' or '-'" % project)

    # 1. policy
    people = collections.OrderedDict()
    for k, v in pol["people"].items():
        if k == "__OWNER__" or (a.force and isinstance(v, dict) and v.get("role") == "owner" and k == handle):
            continue
        people[k] = v
    owner = collections.OrderedDict([("name", name), ("email", email), ("github", github), ("role", "owner"),
                                     ("projects", ["*"]), ("function", "eng"), ("restricted_read", True)])
    ordered = collections.OrderedDict()
    for k, v in people.items():
        ordered[k] = v
        if k == "$comment":
            ordered[handle] = owner
    if handle not in ordered:
        ordered[handle] = owner
    pol["people"] = ordered
    pol["org"], pol["repo"], pol["instance"] = org, repo, True
    tiers = pol.get("sensitivity", {}).get("tiers", {})
    if "restricted" in tiers:
        tiers["restricted"]["submodule"] = "%s/%s-restricted" % (org, repo)
    with open(ROLES, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(pol, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("  owner         %s <%s>, GitHub @%s, handle %s" % (name, email, github, handle))

    # 2. notes
    n = replace_in_notes([("__OWNER_NAME__", name), ("__OWNER__", handle)])
    print("  notes         owner filled in %d note(s)" % n)

    # 2b. the open-source project's own front page and contribution files describe Cairn, not your
    # team: remove them so the repository's GitHub page shows the team guide (README.md).
    # LICENSE, LICENSE-NOTES and NOTICE stay: the licences require them.
    gone = [f for f in TEMPLATE_ONLY if os.path.exists(os.path.join(ROOT, f))]
    for f in gone:
        target = os.path.join(ROOT, f)
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    print("  template      removed %s" % (", ".join(gone) or "nothing (already gone)"))

    # 3. Basic Memory project name
    with open(MANIFEST, encoding="utf-8") as fh:
        man = json.load(fh, object_pairs_hook=collections.OrderedDict)
    man["name"] = project
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(man, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("  basic-memory  project %r" % project)

    # 4. git
    if git("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        git("init", "-q", "-b", "main")
        print("  git           new repository (branch main)")
    git("config", "user.name", name)
    git("config", "user.email", email)
    print("  git           this repository commits as %s <%s>" % (name, email))

    # 5-6. CODEOWNERS and stamps, through the guard itself, as a person (never as an agent)
    env = {k: v for k, v in os.environ.items() if k not in (
        "MEMORY_ACTOR_KIND", "MEMORY_ACTOR_EMAIL", "MEMORY_AGENT", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT", "KIRO_AGENT", "CURSOR_AGENT", "MEMORY_POLICY_REF")}
    env["MEMORY_ACTOR_KIND"] = "human"
    env["MEMORY_POLICY_REF"] = "WORKTREE"  # judge with the policy just written, not the template's HEAD
    guard = os.path.join(HERE, "memory_guard.py")
    for step in (["codeowners", "--write"], ["stamp", "--all"]):
        p = subprocess.run([sys.executable, guard, "--notes-root", ROOT, *step], cwd=ROOT, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        if p.returncode != 0:
            fail("memory_guard %s failed:\n%s" % (step[0], (p.stdout + p.stderr).strip()), 6)
    print("  CODEOWNERS    * @%s" % github)
    print("  notes         stamped with %s as author" % handle)

    print("""
Done. Next:
  1. fill in CORE.md and context/*.md (search for TODO): what every agent should know first;
  2. add teammates to governance/roles.json, then: uv run -q --script scripts/memory_guard.py codeowners --write
  3. git add -A && git commit -m "cairn: initialise" && git push -u origin main
     (no origin yet? git remote add origin <your private repo> first)
  4. protect main on GitHub (README, "Turn on enforcement").""")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
