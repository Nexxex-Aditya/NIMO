# PROGRESS.md — current build state

Imported by the session brief — loads automatically at the start of every session,
before any user message. Updated at **milestone cadence only** (a phase's
gate passing), per `docs/04-build-standards.md` §1a. Between milestones,
`git log --oneline` is the resumability signal — read it since the last
milestone commit named below, then verify with `make check` (or its four
commands directly) before trusting either source.

## Right now

Phase: P11 (LLM adjudication) — NOT STARTED
Last completed milestone: P10 (calibration) — machinery built, NO curve fitted.
Next milestone: P11. **Cannot be executed off the NIQ network** (CIS endpoint is
RFC1918). Write it and fixture-test it (`04` §6); execute on the office laptop.
Authority: `03` §4 stage 4 Layer B, `05` §1 (untrusted content in prompts —
injection fixture tests are DoD), `05` §3.

**THE NUMBER THAT MATTERS FOR PLANNING:** the full pipeline works end to end
(first registry write-back fired on `qa:5`), but free search yields **8 rows
per cooldown window** before all three engines block. A 412-row qa run is
~13 hours unattended on free engines, if blocks lift on schedule. **A paid
search API is required for a submission run in a working day.** Free engines
serve the 10-row demo, development, and warm cache re-runs. Q6 is now the
blocking decision.

**P10 state:** `calibrated_prob` mirrors `raw_score` (tested); abstention is
OFF (`tau_abstain: 0.0`); `data/calibration/pairs.jsonl` holds 1 pair. The
fit takes over automatically once >=30 pairs exist — the harvest is
`harvest_pairs` over the runner's `fetch` artifacts, offline, reproducible.

## Carried-forward work, explicitly not done

- **P4 is partial by design: 6 of 50 sampled rows labelled** (5 `correct`,
  1 `ambiguous`). The other 44 are unlabelled and resumable directly from
  the frozen sample at `data/gold/sample.txt`. Do **not** fill them in
  without actually opening and inspecting each page — `specs/gold.md`
  explains why a fabricated URL is worse than a missing one, and P9/P10 both
  fit against this file.
- **The CIS LLM endpoint is unreachable off-VPN.** It resolves to
  `10.249.224.116` (RFC1918); TCP 443 times out from here while public
  internet is fine. P11–P13 can be written and fixture-tested off-network
  (`04` §6 requires that anyway) but can only be *executed* on the NIQ
  network. Verify connectivity before P11 rather than at demo time.
- **32 of 59 modules are unreachable by the P5 classifier**, `TOOTHBRUSHES -
  MANUAL - INTERDENTAL` among them (`01` §6). Deferred deliberately, not
  dropped — `specs/classify.md` §6 has the two rejected fixes and the
  measured lever (`qa:259`, margin +0.195) for the stage that has page
  evidence.

## Verified state (re-check on resume, don't trust blindly)

Last `make check`: PASS as of the P7 commit. `make` is absent on
this machine; ran its four commands directly per `04` §11:
  uv run ruff check src tests            -> EXIT 0
  uv run ruff format --check src tests   -> EXIT 0
  uv run mypy --strict src tests         -> EXIT 0
  uv run pytest                          -> EXIT 0  (581 passed)

## Do NOT re-do

- P0–P10: done (P7's recall gate open; P10's curve unfitted — both stated), gates verified by execution, committed.
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
- **P6: a row gets BOTH a GTIN block key and a fingerprint key**, never one
  or the other. `qa` has a clean barcode on 412/412 rows, so the original
  either/or rule in `03` §4 stage 1 made Tier 1 unreachable for the whole
  evaluation set while Tier 0 missed all 412. Don't "simplify" it back.
- **P6: no similarity function separates same-product from different-product
  on this data.** Measured over 20 hand-adjudicated pairs; a true positive
  (0.629) scores below a true negative (0.723) for every candidate tried, and
  `test_a_true_positive_scores_below_a_true_negative` pins that inversion on
  purpose. `τ_ann=0.75` is a precision-first cut with a known recall loss, not
  a separating threshold — don't lower it to "catch more".
- **P6: Tier 0 fires 0/412 in a single pass over this dataset** (0 shared
  dev/qa barcodes, 0 duplicates within qa) and 412/412 on a re-run. That is
  the warm-start property working, not a bug. Demo it as a re-run.
- **P7: `startpage` DOES NOT EXIST in this SearxNG build.** SearxNG silently
  falls back to its defaults on an unknown engine name; the client now raises
  on any result tagged with an unrequested engine. Real engines, measured with
  tags verified: `google cse` 87%, `duckduckgo` 82%, `brave` 95% when not
  suspended. Check names against `GET /config` before adding one.
- **P7: NFKC alone does NOT fold the lookalike hyphen.** Measured:
  `normalize("NFKC", "‑")` -> `‐`, still non-ASCII. `01` §13 and the
  first spec draft both assumed it did. An explicit dash-fold table plus
  deletion of invisible characters is required, and is regression-tested.
- **P7: S1/S2 fire only on `barcode_valid`** — 18 of dev's 35 surviving
  barcodes, not all 35. The other 17 are 6-7 digits and are not GTINs.
- **P7: unknown query parameters are KEPT.** Only tracking/session ones are
  stripped. Dropping `?variant=` would merge a 75ml and a 100ml listing.
- **P9: zero of the six gold rows have a usable GTIN.** The GTIN hard rule
  cannot be measured by Precision@1 on the gold set; the five adversarial
  tests `04` §8 names are the gate for it. Don't try to "fix" the gold set
  by inventing barcodes.
- **P10: `calibrated_prob` mirrors `raw_score` WITHOUT a curve and follows
  the curve WITH one — both states tested.** `fit_isotonic` refuses fewer than
  30 pairs; don't lower that to make a curve appear.
- **P10: the calibration instrument is the GTIN rule on qa, not the gold
  set.** The score fed to the fit is the weighted score BEFORE hard rules, so
  the oracle cannot leak into the number it labels.
- **P9: write-back fires on GTIN accept ONLY.** A high text score never
  writes to the registry until a real calibration exists.
- **P6a: the runner is the only `except Exception` in `src/`**, paired with a
  typed `RowFailure`, and `test_only_one_broad_except_exists_in_src` pins it.
  If that test fails, the fix is to remove the new broad except, not to add a
  path to the allowlist.
- **P6a: a failed row leaves NO artifacts**, not a partial set, and a row with
  some artifacts is re-run from scratch rather than trusted.
- **P5's classifier reads `desc_clean` only — BRAND is deliberately
  excluded**, measured at 7.5 points overall / 3.5 macro worse with it.
  `04` §1's gate wording was corrected to match the measurement. Don't
  "restore" BRAND; `config/classify.yaml` keeps the flag and the numbers.
- **P5 reports macro accuracy as the headline, not overall.** Measured:
  Complement NB scores within 2 points on overall and 11 worse on macro by
  collapsing the tail. Overall alone would have picked the wrong model.
- `config/retailers.yaml` (50 hand-reviewed entries),
  `config/normalize.yaml` (`free`/`extra` deliberately not junk;
  `multiplier_claim_words` deliberately present) and `config/classify.yaml`
  (swept n-gram sizes) are measured artifacts, not drafts. Don't regenerate
  any of them from a pattern.
- `pandas-stubs`/`types-openpyxl`/`types-PyYAML` are deliberate; they caught
  two real loader defects. Don't swap them for `ignore_missing_imports`.
- No scikit-learn. P5's model is hand-written and unit-tested against
  hand-computed vectors; the dependency would need an untyped-import
  override to buy an implementation of a hundred lines of arithmetic.
- Contract points decided and logged — don't "fix" any of them:
  `CandidateEvidence.jsonld_product`/`.og` are `dict[str, Any]`;
  `barcode_valid` is a function, not a field; `DescTokens`/`CanonicalEntity`
  carry both `size_ml_equiv` and `size_g_equiv`, never interconverted.
- Doc versions in force: `01` v1.4, `03` v0.8, `04` v0.7, `05` v0.2.
