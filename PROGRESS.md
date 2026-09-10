# PROGRESS.md — current build state

Imported by the session brief — loads automatically at the start of every session,
before any user message. Updated at **milestone cadence only** (a phase's
gate passing), per `docs/04-build-standards.md` §1a. Between milestones,
`git log --oneline` is the resumability signal — read it since the last
milestone commit named below, then verify with `make check` (or its four
commands directly) before trusting either source.

## Right now

Phase: P3 (normalizer) — IN PROGRESS
Last completed milestone: P2 (loader), gate passed.
Next milestone: P3 (normalizer). **No spec file exists yet** — write
`specs/normalize.md` first, to the same standard as the existing three
(literal content where applicable, explicit acceptance criteria, verified
against real behaviour), then implement against it. Authority: `03` §4
stage `[0]`, `03` §3 `DescTokens`.

## Verified state (re-check on resume, don't trust blindly)

Last `make check`: PASS as of the P2 milestone commit. `make` is absent on
this machine; ran its four commands directly per `04` §11:
  uv run ruff check src tests            -> EXIT 0
  uv run ruff format --check src tests   -> EXIT 0
  uv run mypy --strict src tests         -> EXIT 0
  uv run pytest                          -> EXIT 0  (139 passed)
Last milestone commit: 70f3095 "P2 loader: dataset ingest, drift guards,
139-test suite (specs/loader.md)"

## Do NOT re-do

- P0, P1, P2: done, gates verified by execution, committed.
- The dataset is at `data/raw/product_truth_agent_dataset.xlsx`, `git mv`'d
  from `Project_info/`, tracked once. `data/raw/` is read-only (`04` §12) —
  every test that needs a mutated workbook copies to `tmp_path` first.
- `config/retailers.yaml` is complete: all 50 entries hand-reviewed, `name`
  populated for every one, `domain` for 28. Do not regenerate it from a
  regex — the regex fails on 21 of 50, one silently.
- `pandas-stubs`/`types-openpyxl`/`types-PyYAML` are in the dev group
  deliberately, not accidentally. Do not replace them with
  `ignore_missing_imports`: they caught two real defects in the loader.
- Known contract deviations, both decided and logged — do not "fix" either:
  `CandidateEvidence.jsonld_product`/`.og` are `dict[str, Any]`;
  `barcode_valid` is a function in `nimo.loader.fields`, not a `RawRow` field.
- `01` is at v1.3. §3 now says **18**, not 35, usable dev barcodes.
