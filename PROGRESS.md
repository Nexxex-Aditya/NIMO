# PROGRESS.md — current build state

Imported by the session brief — loads automatically at the start of every session,
before any user message. Updated at **milestone cadence only** (a phase's
gate passing), per `docs/04-build-standards.md` §1a. Between milestones,
`git log --oneline` is the resumability signal — read it since the last
milestone commit named below, then verify with `make check` (or its four
commands directly) before trusting either source.

## Right now

Phase: P1 (contracts) — IN PROGRESS
Last completed milestone: P0 (scaffold), gate passed.
Next milestone: P1 (contracts), spec: `specs/contracts.md`.

## Verified state (re-check on resume, don't trust blindly)

Last `make check`: PASS as of the P0 milestone commit. `make` is absent on
this machine; ran its four commands directly per `04` §11:
  uv run ruff check src tests            -> EXIT 0
  uv run ruff format --check src tests   -> EXIT 0
  uv run mypy --strict src tests         -> EXIT 0
  uv run pytest                          -> EXIT 0  (1 passed)
Last milestone commit: cbcacb6 "P0 scaffold: repo layout, deps, config
stubs, logging, settings, CI"

## Do NOT re-do

- P0: done, all six `specs/scaffold.md` acceptance criteria verified by
  execution (not asserted), committed.
- The dataset is already at its canonical path: `git mv`'d from
  `Project_info/` to `data/raw/product_truth_agent_dataset.xlsx`. It is
  tracked once, not duplicated. `data/raw/` is read-only from here on
  (`04` §12).
- `pyproject.toml` already carries the three verified P0 fixes
  (`[build-system]` uv_build, `plugins = ["pydantic.mypy"]`, ruff
  `extend-exclude` + Makefile scoped to `src tests`). `nimo` installs into
  the venv correctly — if `import nimo` ever fails again, that is a
  regression, not the original unfixed defect.
