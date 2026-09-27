"""
testpolicy.py - the policy every test fixture runs under.

Tests exercise the engine, never a team's configuration. Each fixture gets this repository's
governance/roles.json (its rules, levels and roles) with the people replaced by one fictional
owner, Alex Tester, plus the template's placeholder rows, and with team-specific protocol
settings (protocol.extra_symptoms) cleared. So the suites pass the same way in the template and in
an initialised instance, whoever its owner is.
"""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TEMPLATE = os.path.join(REPO, "governance", "roles.json")

HANDLE = "alex"
NAME = "Alex Tester"
EMAIL = "alex@example.test"
GITHUB = "alex-test"


def _owner():
    return collections.OrderedDict([
        ("name", NAME), ("email", EMAIL), ("github", GITHUB), ("role", "owner"),
        ("projects", ["*"]), ("function", "eng"), ("restricted_read", True)])


def policy():
    with open(TEMPLATE, encoding="utf-8") as fh:
        d = json.load(fh, object_pairs_hook=collections.OrderedDict)
    people = collections.OrderedDict([(HANDLE, _owner())])
    for k, v in d["people"].items():
        if k.startswith("__TODO"):          # the template's placeholder rows stay, real people do not
            people[k] = v
    d["people"] = people
    if isinstance(d.get("protocol"), dict):
        d["protocol"]["extra_symptoms"] = []
    d["instance"] = True
    return d


def install(governance_dir):
    """Write the test policy as <governance_dir>/roles.json."""
    d = policy()   # read before opening for write: installing into this repo's own governance/ must not empty it
    os.makedirs(governance_dir, exist_ok=True)
    with open(os.path.join(governance_dir, "roles.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(d, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
