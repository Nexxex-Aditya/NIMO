# PROGRESS.md — current build state

Imported by the session brief — loads automatically at the start of every session,
before any user message. Updated at **milestone cadence only** (a phase's
gate passing), per `docs/04-build-standards.md` §1a. Between milestones,
`git log --oneline` is the resumability signal — read it since the last
milestone commit named below, then verify with `make check` (or its four
commands directly) before trusting either source.

## Right now

Phase: P2 (loader) — IN PROGRESS
Last completed milestone: P1 (contracts), gate passed.
Next milestone: P2 (loader), spec: `specs/loader.md`.

## Verified state (re-check on resume, don't trust blindly)

Last `make check`: PASS as of the P1 milestone commit. `make` is absent on
this machine; ran its four commands directly per `04` §11:
  uv run ruff check src tests            -> EXIT 0
  uv run ruff format --check src tests   -> EXIT 0
  uv run mypy --strict src tests         -> EXIT 0
  uv run pytest                          -> EXIT 0  (58 passed)
Last milestone commit: 42aae6a "P1 contracts: all 13 pydantic models +
round-trip/frozen/literal test suite"

## Do NOT re-do

- P0: done, all six `specs/scaffold.md` acceptance criteria verified by
  execution, committed.
- P1: done, `specs/contracts.md` DoD fully verified. All 13 models exist,
  frozen, Literals verbatim, field-for-field identical to `03` §3 (checked
  mechanically, and that check is now a permanent test —
  `test_contracts_match_architecture_section_3_field_for_field`).
- The dataset is already at its canonical path: `git mv`'d from
  `Project_info/` to `data/raw/product_truth_agent_dataset.xlsx`, tracked
  once, not duplicated. `data/raw/` is read-only from here on (`04` §12).
- `pyproject.toml` already carries the three verified P0 fixes
  (`[build-system]` uv_build, `plugins = ["pydantic.mypy"]`, ruff
  `extend-exclude` + Makefile scoped to `src tests`). If `import nimo` ever
  fails again, that is a regression, not the original unfixed defect.
- `CandidateEvidence.jsonld_product` / `.og` being `dict[str, Any]` is a
  decided, documented deviation from `03` §3's original bare `dict` — do not
  "tighten" it to `dict[str, object]`, that was tested and breaks nested
  JSON-LD access. See the decision log.
