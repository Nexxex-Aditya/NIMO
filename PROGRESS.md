# PROGRESS.md — current build state

Imported by the session brief — loads automatically at the start of every session,
before any user message. Updated at **milestone cadence only** (a phase's
gate passing), per `docs/04-build-standards.md` §1a. Between milestones,
`git log --oneline` is the resumability signal — read it since the last
milestone commit named below, then verify with `make check` (or its four
commands directly) before trusting either source.

## Right now

Phase: P4 (gold set) — IN PROGRESS
Last completed milestone: P3 (normalizer), gate passed.
Next milestone: P4 (gold set). **No spec file exists yet** — write
`specs/gold.md` first, then build it. Gate (`04` §1): ~50 hand-labelled
URLs, stratified by module, committed as `data/gold/urls.jsonl`.
Authority: `03` §6 (L3/L4), `01` §6 (why it must exist at all — there is no
URL ground truth in the dataset, so if we don't make it, it doesn't exist).

**Hard rule for P4, stated here because it is the phase's whole point:**
a fabricated or guessed URL is worse than a missing one. It would silently
miscalibrate P9 precision@1 and P10's calibration curve with no error
anywhere — exactly the latent-failure class `05` §5 exists to name. Every
entry must be genuinely verified, and unverified rows must be absent rather
than filled in optimistically.

## Verified state (re-check on resume, don't trust blindly)

Last `make check`: PASS as of the P3 milestone commit. `make` is absent on
this machine; ran its four commands directly per `04` §11:
  uv run ruff check src tests            -> EXIT 0
  uv run ruff format --check src tests   -> EXIT 0
  uv run mypy --strict src tests         -> EXIT 0
  uv run pytest                          -> EXIT 0  (232 passed)
Last milestone commit: 7b31f59 "P3 normalizer: RawRow -> ProductQuery,
93-test suite (specs/normalize.md)"

## Do NOT re-do

- P0, P1, P2, P3: done, gates verified by execution, committed.
- `data/raw/` holds the workbook and is read-only (`04` §12). Tests that
  need a mutated workbook copy to `tmp_path` first.
- `config/retailers.yaml` — all 50 entries hand-reviewed. Do not regenerate
  from a regex; it fails on 21 of 50, one silently.
- `config/normalize.yaml` — `free` and `extra` are deliberately NOT junk
  tokens, and `multiplier_claim_words` deliberately exists. Both are
  measured guards, not stylistic choices.
- Decided, logged contract points — do not "fix" any of these:
  `CandidateEvidence.jsonld_product`/`.og` are `dict[str, Any]`;
  `barcode_valid` is a function, not a `RawRow` field; `DescTokens` and
  `CanonicalEntity` carry BOTH `size_ml_equiv` and `size_g_equiv`, never
  interconverted.
- `pandas-stubs`/`types-openpyxl`/`types-PyYAML` are deliberate; they caught
  two real loader defects. Do not swap them for `ignore_missing_imports`.
- Doc versions currently in force: `01` v1.3, `03` v0.6, `04` v0.7, `05` v0.2.
