# PROGRESS.md — current build state

Imported by the session brief — loads automatically at the start of every session,
before any user message. Updated at **milestone cadence only** (a phase's
gate passing), per `docs/04-build-standards.md` §1a. Between milestones,
`git log --oneline` is the resumability signal — read it since the last
milestone commit named below, then verify with `make check` (or its four
commands directly) before trusting either source.

## Right now

Phase: P5 (module baseline) — NOT STARTED
Last completed milestone: P4 (gold set), gate passed.
Next milestone: P5. **No spec file exists yet** — write `specs/classify.md`
first, then implement. Gate (`04` §1): per-module stratified accuracy
reported for a text-only classifier over `RETAILER_DESC` + `BRAND`, no URL.
Authority: `03` §4 stage `[5]`, `03` §6 L1.

Two things `03` §4 stage 5 is explicit about and that shape the phase:
`MODULE` is the **only** stage with real measurable ground truth (412/412
labelled in `dev`), and overall accuracy is misleading because the top 4
modules are 77% of `dev` — report **per-module stratified** accuracy or the
23-module tail stays invisible.

## Carried-forward work, explicitly not done

- **P4 is partial by design: 6 of 50 sampled rows labelled** (5 `correct`,
  1 `ambiguous`). The other 44 are unlabelled and resumable directly from
  the frozen sample at `data/gold/sample.txt`. Do **not** fill them in
  without actually opening and inspecting each page — `specs/gold.md`
  explains why a fabricated URL is worse than a missing one, and P9/P10 both
  fit against this file.

## Verified state (re-check on resume, don't trust blindly)

Last `make check`: PASS as of the P4 milestone commit. `make` is absent on
this machine; ran its four commands directly per `04` §11:
  uv run ruff check src tests            -> EXIT 0
  uv run ruff format --check src tests   -> EXIT 0
  uv run mypy --strict src tests         -> EXIT 0
  uv run pytest                          -> EXIT 0  (260 passed)
Last milestone commit: 8ca028f "P4 gold set: frozen stratified sample +
6 hand-verified labels"

## Do NOT re-do

- P0–P4: done, gates verified by execution, committed.
- **Row identity is `row_uid` (`"dev:0"`), never `NAN_KEY`/`ITEM_CODE`.**
  `01` §14: all three columns carry the same rounding corruption. Never key
  an artifact, a cache entry, a registry member or a gold label on
  `NAN_KEY`. This bug has already been introduced twice (the loader, then
  the P4 sampler) and caught twice by tests.
- **There is no dev/qa overlap.** All 40 shared `ITEM_CODE`s and all 23
  shared `NAN_KEY`s are rounding artifacts. Do not resurrect the "40
  overlapping rows" framing; P6 measures a content fingerprint instead.
- **The fingerprint is a BLOCKING key, not a match key.** Measured: shared
  fingerprints include genuinely different products (Aquafresh Extra Care
  vs Aquafresh Intense Clean, both 500ml). Tier-1 similarity inside the
  block is what discriminates, and P6 reports block hit rate *and*
  within-block precision for exactly this reason.
- `config/retailers.yaml` (50 hand-reviewed entries) and
  `config/normalize.yaml` (`free`/`extra` deliberately not junk;
  `multiplier_claim_words` deliberately present) are measured artifacts, not
  drafts. Don't regenerate either from a pattern.
- `pandas-stubs`/`types-openpyxl`/`types-PyYAML` are deliberate; they caught
  two real loader defects. Don't swap them for `ignore_missing_imports`.
- Contract points decided and logged — don't "fix" any of them:
  `CandidateEvidence.jsonld_product`/`.og` are `dict[str, Any]`;
  `barcode_valid` is a function, not a field; `DescTokens`/`CanonicalEntity`
  carry both `size_ml_equiv` and `size_g_equiv`, never interconverted.
- Doc versions in force: `01` v1.4, `03` v0.7, `04` v0.7, `05` v0.2.
