# Claude Code team telemetry

[initial-specs.md](initial-specs.md) is the behaviour spec. Read [docs/decisions.md](docs/decisions.md) before changing code: it records the architecture decisions, the deliberate deviations from the spec, and what is unfinished. [docs/invariants.md](docs/invariants.md) lists the rules that tests enforce. [local-architecture.md](local-architecture.md) has the diagrams for running it on a Mac.

Before finishing a change, run from the repo root:

- `make check` (this is `ruff check .` and the unit tests)

Python is standard library only. Tests are named `<name>_test.py`, beside the module; a `test_<name>.py` file is never found. Commit only when asked.

## Enforced by a check

- Functions are short: aim for 5 to 10 lines, over 20 fails. If a step wants a comment, extract it into a function named for the step.
- No comments and no docstrings: name things so they are not needed. `# noqa`, `# type:`, `# pragma` and a shebang are allowed.
- Indentation depth is at most 4. `telemetry/style_baseline.json` lists code older than these rules: a listed function may not grow, nothing new may break a limit. After shortening code run `python3 telemetry/style_test.py --update`; `--report` shows the distance to the goal.
- pathlib over `os.path`, absolute imports, imports at module level, an explicit encoding on every file read and write, no re-export aliases, empty `__init__.py`, no `try`/`except`/`pass`.
- Ruff rules are only ever added, never removed.

## By convention (no check)

- Look before you leap: test a condition rather than catching the exception it would raise. Catch exceptions at boundaries only: parsing JSON, SQLite, the network.
- The hook path is privacy-critical and latency-critical. Never add a field to an event without adding it to the allowlist constants, `docs/privacy.md` and a test in `invariants_test.py`. Never import a network library into the hook path (INV-11).
- Build the event from named fields; never copy, forward, log or `repr` the raw hook input.
- No backwards-compatibility shims: change the shape and migrate callers in the same change. Spool schema changes are the exception: append a migration, never edit a shipped one.
- Declare a variable next to its use.

## Keeping the spec in step

`telemetry/spec_sync_test.py` and `telemetry/invariants_test.py` fail when code, docs and spec drift apart. When you change [initial-specs.md](initial-specs.md), update the code and docs it affects, then run `python3 -m telemetry.spec_sync_test --accept` to record the new spec hash. Only a person should change the spec; if code needs to differ, write it down in docs/decisions.md as a deviation instead.
