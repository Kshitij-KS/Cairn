# Contributing to Cairn

Thanks for helping. Cairn is small on purpose: a few standard-library Python scripts, Markdown, and
git. Please keep it that way.

## Ground rules

- **Standard library only** for everything under `scripts/`. A script must run with nothing but
  Python 3.9+ and git (`uv run --script` is how people launch them, not a dependency).
- **Every behaviour change comes with a test**, and the test must be shown to fail without the
  change. Say how you proved it in the pull request.
- **Every suite states how many checks it expected to run** and fails if fewer ran.
- **Security fixes and gate changes need a regression test in `tools/test_security.py` or
  `tools/test_gate.py`.** The gate is judged by the base revision's own tests, so weakening them
  shows up as a red check.
- **No real people, companies or projects in examples or fixtures.** Use `example.test` addresses
  and invented names (the test identity is `alex`, see `tools/testpolicy.py`).
- **ASCII in the PowerShell scripts.** Windows PowerShell 5.1 misreads UTF-8 without a BOM;
  `tools/test_sync.py` enforces this.
- Keep line endings LF (`.gitattributes` does this for you).

## Running the checks

```bash
bash tools/run_tests.sh                      # every offline Python suite plus config checks
cd web/test && npm ci && npm test            # the Atlas page and its rendered-page privacy oracle
python3 tools/test_sync.py --impl all        # both sync implementations, where PowerShell exists
```

Windows: use `py` instead of `python3`.

Nothing needs a network connection or an API key.

## Pull requests

1. Fork, branch (`fix/<slug>`, `feat/<slug>`), change, test.
2. Describe what changed, why, and the command that proves it.
3. Update `ARCHITECTURE.md` when you change a component, a folder's level, an exit code or a
   workflow.

By contributing you agree that your contribution is licensed under the Apache License 2.0
(see `LICENSE`, section 5).

## Reporting a vulnerability

Please do not open a public issue. See [SECURITY.md](SECURITY.md).
