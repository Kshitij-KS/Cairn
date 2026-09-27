# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub:
**Security -> Report a vulnerability** on this repository (private vulnerability reporting).
Do not open a public issue for them.

Include what you did, what happened, and what you expected, ideally as a failing test in the style
of `tools/test_security.py`. You should hear back within 7 days.

## What counts

Cairn's security claims are the ones in `ARCHITECTURE.md` section 9 (threat model). Reports that
matter most:

- a way for a change to reach `main` past the `memory-gate` check once branch protection is on
  (for example, a pull request that makes the base revision's guard accept it);
- a way for an agent (actor kind `agent`) to write above L0 through the guard;
- a path trick (case, Unicode, separators, renames, symlinks) that changes a file's level;
- a secret or a restricted note's name reaching the published Atlas (`web/data/graph.json`);
- misattribution that the per-commit check in CI accepts.

## What is out of scope, by design

- **Anything before branch protection is on.** Until `main` is protected, the guard on each laptop
  is a guard-rail, not a boundary; a process with write access to a checkout can skip it. This is
  documented, not a vulnerability.
- Secret detection is pattern-based; novel secret formats pass. Better patterns are welcome as
  ordinary pull requests.
- Anyone who can read a private restricted submodule can read its files.

## Supported versions

Only the latest commit on `main` is supported.
