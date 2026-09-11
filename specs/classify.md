# specs/classify.md — P5: Module baseline

Authority: `03-architecture.md` §4 stage `[5]`, `03` §6 L1. Build standards:
`04-build-standards.md`. Authored during the full-autonomy
run, per the shared-authorship change in `02-decision-log.md` (2026-09-10).

Depends on P2 (`RawRow`) and P3 (`ProductQuery.desc_clean`, `DescTokens`).
Depends on nothing downstream — **no URL, no fetch, no LLM, no network.**

Every number in this file was measured against the real 412-row `dev` sheet
before the spec was written, not estimated. The measurements are reproduced
inline because they are the *reason* for each design choice, and a later
reader who disagrees with a choice needs the evidence, not the conclusion.

---

## 1. What this phase is, and what it is deliberately not

`03` §4 stage 5 asks for a **text-only baseline, built first**, from
`RETAILER_DESC` + `BRAND` alone, with no URL involved. Two stated reasons:
it may capture most of the module signal for free, and it is the fallback
when stage 4 abstains or retrieval fails — without it, one retrieval miss
costs all 14 output columns for that row.

So this phase produces one thing: a deterministic classifier from cleaned
description text to a `MODULE` value, plus an honest measurement of how good
it is per module.

**Not in scope, and each exclusion is load-bearing:**

- **No page evidence.** That is the "layer on top and measure the delta" step
  `03` §4 stage 5 describes, and it needs P7/P8, which do not exist.
- **No LLM.** Same reason, plus the CIS endpoint is unreachable off-VPN
  (`02-decision-log.md`, Q7).
- **No attempt to solve the 32-unseen-module problem by guessing.** §6 has
  the measurement that killed this, and it is the most important finding in
  the phase.
- **No abstention.** The classifier always emits its best module. Stage 5 is
  the *fallback* path; a fallback that declines to answer is not a fallback.
  Confidence is carried on the prediction so a later stage can override it.

## 2. Ground truth, and the one thing that makes this phase special

`MODULE` is populated in **412 of 412** `dev` rows and empty in all of `qa`
(`01` §6). This is the only stage in the whole pipeline with real, measurable
ground truth. Everything else is scored against a 6-row hand-labelled gold
set or not at all.

Ground truth is loaded by `nimo.loader.load_module_labels(workbook, sheet,
rules)`, which returns `list[str]` positionally aligned with `load_rows` —
the same shape `nimo.gold.sample.stratify_by_module` already consumes.

**It is deliberately not a field on `RawRow`.** `RawRow` is the input
contract; putting the answer on the input row would make it structurally
possible for a predictor to read its own label. The loader function also
asserts every label is in `char_value_list`'s module set — the
silent-schema-drift guardrail (`05` §5) applied to labels rather than inputs.

### The distribution, measured

27 of the 59 defined modules appear in `dev`. The tail is not a detail:

| rows | modules | cumulative share of `dev` |
|---|---|---|
| 133 | TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH) | 32.3% |
| 94 | MOUTHWASH/... - FOAM/GEL/LIQUID - MULTI DOSE | 55.1% |
| 52 | TOOTHBRUSHES - MANUAL - REGULAR | 67.7% |
| 38 | TOOTHBRUSHES - ELECTRIC - COMPLETE PACK | 76.9% |
| 13 … 4 | 7 modules | 91.3% |
| 3 … 2 | 11 modules | 99.0% |
| 1 | 4 modules | 100% |

**Overall accuracy is not a usable metric here and must never be the headline
number.** A classifier that predicts only the top 4 modules and gets every
one of them right scores 76.9% overall while being wrong about 23 of the 27
module types. `01` §9 and `04` §1's P5 gate both say per-module stratified —
this spec makes that binding: the headline is **macro accuracy** (unweighted
mean of per-module accuracy), reported alongside overall, never instead of it.

**Four modules have exactly one `dev` row.** Those rows are unpredictable
under *any* held-out protocol including leave-one-out: removing the row
removes the class. Their per-module accuracy is structurally 0% and that is
not a bug to fix — it is reported as-is, and the 12 rows in 2-row modules are
nearly as constrained. Do not "improve" macro accuracy by dropping small
modules from the denominator; that is the exact invisibility `01` §9 warns
against.

## 3. Features — character n-grams over `desc_clean`, and not BRAND

### 3a. Why character n-grams

Measured, leave-one-out over all 412 `dev` rows, nearest-centroid in every
row so only the feature set varies:

| features | overall | macro |
|---|---|---|
| word unigrams over `desc_raw` | 68.9% | 35.4% |
| word unigrams over `desc_clean` | 72.1% | 41.2% |
| word unigrams + brand over `desc_clean` | 69.7% | 40.4% |
| words + brand + char 4-grams over `desc_clean` | 80.3% | 47.9% |
| **char 4-grams alone over `desc_clean`** | **80.3%** | **49.7%** |

Character n-grams win by ~8 points overall and ~8 macro over word tokens, and
adding word features on top of them buys nothing. The mechanism is visible in
the data: this dataset writes the same product as `toothpaste`, `tooth paste`,
`t/paste`, `dentifrice`, `pste`, `zahnpasta` and `aufsteckbürsten` across
retailers and languages, and it truncates aggressively (`s/d t/c tooth stain
erase`, `ob g&e es man tbrush`). Word tokens treat every one of those as a
distinct feature. 4-grams share substrings across all of them.

**P3's normalizer measurably earns its place here:** `desc_clean` beats
`desc_raw` by 3.2 points overall and 5.8 macro on identical features. That is
independent evidence for P3's retailer-suffix stripping and junk removal,
measured on a downstream task rather than asserted.

### 3b. n-gram size, swept

Leave-one-out, char n-grams over `desc_clean`, nearest-centroid:

| sizes | overall | macro |
|---|---|---|
| (3,) | 78.9% | 47.9% |
| **(4,)** | **80.3%** | **49.7%** |
| (5,) | 79.1% | 47.2% |
| (3,4) | 80.1% | 48.5% |
| (4,5) | 79.9% | 50.7% |
| (3,4,5) | 80.1% | 50.3% |

Everything from 4 upward is within a point of everything else — with 27
classes and modules holding 1–3 rows, a one-point macro difference is a
single row changing in a single small module, which is noise, not signal.
**Default `[4]`**: best overall, within noise on macro, and a third of the
feature count of `(3,4,5)`, which matters for a model whose whole appeal is
that it is auditable. The sizes are a config list, so re-tuning is a config
edit and this table is the record of what was already tried.

### 3c. BRAND is excluded, which contradicts `04` §1's own gate wording

`04` §1's P5 gate says "text-only classifier over `RETAILER_DESC` + `BRAND`".
Measured, same protocol, char (3,4,5)-grams:

| features | overall | macro |
|---|---|---|
| `desc_clean` only | **80.1%** | **50.3%** |
| `BRAND` prepended to `desc_clean` | 72.6% | 46.8% |

Including BRAND costs **7.5 points overall and 3.5 macro**. This is far too
large to be noise and the mechanism is clear: brand does not predict module.
`ORAL-B` makes manual toothbrushes, electric toothbrushes, refill heads and
toothpaste; `COLGATE` makes paste, mouthwash and brushes. A brand's n-grams
pull every one of its products toward whichever module dominates that brand.

There is a second, subtler reason, and it is worth stating because it would
otherwise look like a bug: P3's `strip_repeated_brand` deliberately removes
the brand where it is repeated inside the description. Prepending `BRAND`
puts it back, undoing a normalization P3 made on measured grounds.

**Decision: the classifier reads `desc_clean` only.** BRAND remains available
behind a config flag (`use_brand: false`) so the finding stays reproducible
rather than becoming folklore, and `04` §1's gate wording is corrected to
match the measurement. See `02-decision-log.md`.

## 4. Model — TF-IDF nearest centroid

Chosen over three measured alternatives, leave-one-out, best feature set for
each:

| model | overall | macro |
|---|---|---|
| **TF-IDF nearest centroid** | **80.3%** | **49.7%** |
| Multinomial NB, empirical prior | 73.1% | 22.6% |
| Multinomial NB, uniform prior | 74.5% | 27.2% |
| Complement NB, uniform prior | 78.4% | 38.3% |
| k-NN cosine, k=1 | 66.3% | 32.1% |
| k-NN cosine, k=3 | 66.0% | 30.9% |

Naive Bayes is the instructive failure. Its best overall (78.4%) is close to
the centroid's, and its macro (38.3%) is 11 points worse — it buys head
accuracy by collapsing the tail, which is precisely the metric-shaped trap §2
describes. Reporting only overall accuracy would have made NB look competitive.

**No scikit-learn.** 412 rows × 27 classes × a linear model is a hundred
lines of arithmetic; the dependency would add an untyped import needing an
`ignore_missing_imports` override (`04` §3) to buy an implementation of
something already written and unit-tested here. It also keeps every scoring
step inspectable, which §5's evidence fields depend on.

### Definitions, stated exactly so the implementation is unambiguous

For a document's token multiset and a fitted `idf`:

- **tf** is sublinear: `1 + log(count)`.
- **idf** is smoothed: `log((n_docs + 1) / (df + 1)) + 1`.
- A vector is `{term: tf * idf}` for terms present in `idf`, then **L2
  normalized**. Terms absent from `idf` (unseen at fit time) are dropped, not
  smoothed — an unseen 4-gram carries no information about a class it was
  never observed with.
- A **centroid** is the sum of its class's member vectors, L2 normalized. Not
  the mean: after normalization the two are identical, so summing avoids a
  division that can only introduce float noise.
- **Score** is cosine similarity, which for L2-normalized vectors is the dot
  product.
- **Prediction** is the highest-scoring module, ties broken by module name
  ascending — never by dict or set iteration order (`04` §5).

Confidence is the winning cosine, in `[0, 1]`. It is **not** a calibrated
probability and must not be presented as one; `03` §4's calibration machinery
is P10's job and applies to URL selection, not here.

## 5. Output contract — `ModulePrediction`

New in `03` §3, added by this phase (decision-log entry required, `04` §11).

`03` §2 draws stage `[5]`'s output as a bare `MODULE` string. That is too thin
the moment anything downstream has to *decide* with it: `03` §4 stage 5 makes
this the fallback path, which means the runner needs to know how much to trust
it, and `04` §3 requires inter-module values to be contracts rather than bare
values anyway.

```python
class ModulePrediction:            # P5 — stage [5] output
    row_uid: str                   # `01` §14 — never nan_key
    module: str                    # one of char_value_list's 59; always set, never None
    confidence: float              # winning cosine, 0..1 — NOT a calibrated probability
    runner_up: str | None          # None only when the model knows exactly one module
    runner_up_gap: float           # confidence - runner-up score; 0.0 when runner_up is None
    nearest_example_row_uid: str | None   # closest labelled training row — the audit surface
    nearest_example_similarity: float     # its cosine; 0.0 when there is no training row
    source: Literal["text_baseline", "page_evidence", "registry"]
```

**`nearest_example_row_uid` is the transparency mechanism, and it is why the
model is a centroid rather than a black box.** The brief scores "clear and
transparent reasoning" and `03` §4 stage 7 requires every factual claim in
`REASONING` to trace to a field. A char-4-gram weight vector explains nothing
to a human — the top features are strings like `othp` and `aste`. The nearest
labelled example does: *"classified TOOTH CLEANING - PASTE because it most
resembles `dev:12` `aquafresh whitening pump 100ml`, cosine 0.82, which is
labelled that module."* That is a citation, it is verifiable by opening the
row, and it costs one extra similarity pass.

`source` exists so a row resolved by page evidence (later) or carried from a
registry entity (`03` §4 stage 6) is distinguishable from a baseline guess in
the trace. P5 only ever emits `"text_baseline"`.

## 6. The 32 unseen modules — measured, and deliberately not solved here

`dev` covers 27 of 59 modules. **A model fitted on `dev` labels can never
emit the other 32.** `01` §6 names a concrete casualty: `TOOTHBRUSHES -
MANUAL - INTERDENTAL` has zero `dev` rows and at least one `qa` row that
needs it.

This was not accepted without trying. Two mechanisms were built and measured.

**Attempt 1 — module-name pseudo-documents.** Add each of the 59 module names
to its own class as an extra training document, weighted `w`, so every module
exists in the model. Leave-one-out, char (3,4,5)-grams:

| | overall | macro |
|---|---|---|
| 27-way, no name prior | **80.1%** | **50.3%** |
| 59-way, w=0.25 | 77.2% | 46.8% |
| 59-way, w=0.5 | 76.9% | 45.0% |
| 59-way, w=1.0 | 77.2% | 44.7% |
| 59-way, w=2.0 | 77.9% | 44.5% |

Costs 3 points overall and 4–6 macro at every weight tried. Rejected.

**Attempt 2 — a separate zero-shot arm over the 32 absent modules**, scoring
a row against each absent module's *name* in the same TF-IDF space, and
routing to it when it outscores the supervised arm by a margin `δ`.

`dev` measures the cost of this exactly, which is the useful part: **`dev`
contains none of the 32, so every `dev` row the arm claims is a false route
by construction.**

| δ | dev rows routed | correct answers destroyed | dev overall after | qa rows routed | of which to INTERDENTAL |
|---|---|---|---|---|---|
| +0.00 | 35 | 18 | 76.0% | 37 | 2 |
| +0.05 | 23 | 11 | 77.7% | 21 | 2 |
| +0.10 | 16 | 6 | 78.9% | 11 | 2 |
| +0.15 | 9 | 3 | 79.6% | 4 | 1 |
| +0.20 | 4 | 0 | 80.3% | 1 | 0 |
| +0.25 | 3 | 0 | 80.3% | 0 | 0 |

There is no setting that is both free and useful. At δ=+0.20 the arm costs
nothing and does nothing; at δ=+0.10 it reaches the interdental rows and
destroys 6 correct `dev` answers.

**And the qualitative evidence is worse than the table.** Inspecting the
actual routes at δ=+0.10:

    qa:259  "wisdom advanced interdental toothbrush 2pack"
            -> TOOTHBRUSHES - MANUAL - INTERDENTAL          correct
    qa:364  "tung brush"        -> TONGUE CLEANING - BRUSH/SCRAPER    correct
    qa:289  "poli-grip liquid foam cleanser 125ml"
            -> ORTHODONTIC CLEANSERS - GEL/LIQUID/PASTE     wrong (Poligrip is denture care)
    qa:371  "colgate 2 in 1 whitening liquid gel 100ml"
            -> ORTHODONTIC CLEANSERS - GEL/LIQUID/PASTE     wrong (it is toothpaste)
    qa:65   "fluorigard weekly dental rinse 150ml"
            -> DENTAL ACCESSORIES - ORTHODONTIC WAX         wrong (it is a mouthrinse)
    qa:64   "ob g&e es man tbrush ... care extra soft manual"
            -> TOOTHBRUSHES - MANUAL - INTERDENTAL          wrong (it is a regular brush)

Roughly 4 of 11 routes are right. The `dev` false routes show the mechanism
precisely — the arm gets the **family** right and the **form** wrong:

    "x-press dental stain remover"      -> TOOTH STAIN REMOVERS - KITS
    "galpharm mouth ulcer treatment 3s" -> ORAL TREATMENT - GRANULES/POWDER - MULTI DOSE

Module names encode the form axis in category jargon — `FOAM/GEL/LIQUID/PASTE`,
`KITS`, `MULTI DOSE`, `PRE CUT PIECES/SINGLES` — which retail descriptions
never use. Name matching therefore resolves the family and then guesses the
form, and a wrong form is a wrong module, scored identically to a wildly
wrong answer.

**Decision: compute the unseen-arm score, record it, never act on it at P5.**
The classifier reports `unseen_candidate` and `unseen_score` in its
evaluation report and trace, so the signal exists for a later stage that has
what this one lacks — an actual product page saying "interdental brush", or
an LLM able to read one. `03` §4 stage 5 already plans that step. Solving it
here means guessing a form axis from a 40-character retailer string, and the
measurement says that guess is wrong more often than right.

`01` §6's requirement stands and is deferred, not dropped: `qa:259` is
reachable with margin +0.195, which is a concrete lever for P11/P12. `qa:124`
(`tesco proformula interdental sticks 100's`) is genuinely ambiguous — the
supervised model calls it `DENTAL ACCESSORIES - TOOTHPICKS - MANUAL -
DISPOSABLE` at confidence 0.391, which is defensible for an interdental
*stick*. `01` §6 called both rows candidates, not confirmed labels.

## 6a. Page evidence as a module signal — measured 2026-09-12, rejected

`03` §4 stage 5 asked for the delta from layering page evidence on the text
baseline. Measured over the full 412-row `dev` harvest (every row has a
selected page), leave-one-out with the shipped classifier, the held-out
row's `desc_clean` augmented with its selected page's text — the numbers
are in `03` §4 stage 5. **No variant beats text-only**, on either metric:
concatenating the title costs 0.4 overall / 1.5 macro; adding the JSON-LD
name and breadcrumbs costs more; the title alone is 19 points worse; gating
the title on low text confidence never exceeds the baseline (its best
setting is the one that almost never routes); and a second centroid model
fitted on titles and summed in hurts in proportion to its weight. Restricting
to the 329 rows whose page is ~97% likely correct (calibrated ≥ 0.60) gives
the same sign: 84.8 → 83.0 overall, 52.1 → 48.8 macro.

Why, from the pages themselves: a retailer title is the retailer's *category
vocabulary* plus boilerplate — `| Boots`, `Buy … online`, `Superdrug`,
`… - 75ml - Pack of 2` — and its character 4-grams pull toward whichever
module dominates that retailer, exactly the mechanism that made BRAND
harmful (§3c). The errors the baseline makes are on the *form* axis
(electric vs manual, paste vs stain remover); a title states the form no
more reliably than the retailer description already does, and body text —
which does state it — would dilute a bag-of-4-grams even further.

**Deliberately not built:** a module layer that reads page text. What
remains open from §6 (the 32 unseen modules, `qa:259`) is now a job for
the stage that reads evidence *semantically* — the characteristics call
already sees the page and the guideline text — not for this classifier.
Two forms were rejected, and both are recorded so they are not rebuilt:
(a) concatenation (any amount), (b) a title-trained second model at any
weight. Script: `measure_page_module.py` in the session scratchpad; the
numbers are reproducible from `data/out/artifacts/dev/` and the workbook.

## 7. Evaluation protocol

Two protocols, for two different jobs. Both are fully deterministic — no RNG
anywhere, no `random.seed()`, nothing to reproduce (`04` §5).

**Leave-one-out over all 412 `dev` rows — the reported number.** 412 fits.
Every row is tested against a model that never saw it. This is what `04` §1's
gate reports, and it is the honest figure because at n=412 a held-out split
large enough to measure the tail is large enough to cripple training.

**Deterministic module-stratified 5-fold — the regression guard.** Within
each module, rows in source order are dealt round-robin into `k` folds. No
shuffling, so no seed, so no way for a fold assignment to drift. 5 fits, 0.3
seconds, which is what makes it affordable in `make check` where LOO is not.
It reads slightly pessimistic (78.4% / 48.1% vs LOO's 80.3% / 49.7%) because
each fold trains on 80% of the data, which makes it a safe floor.

Reported per run, in the `ClassifierReport`:

- overall accuracy, macro accuracy, per-module accuracy for all 27 modules
  sorted by row count descending — the tail is the point
- the confusion pairs, most frequent first
- accuracy by confidence decile

That last one is not decoration. Measured, LOO:

| confidence decile | range | accuracy |
|---|---|---|
| 0 (lowest) | 0.027–0.117 | 31.7% |
| 1 | 0.118–0.165 | 73.2% |
| 4 | 0.231–0.253 | 85.7% |
| 7 | 0.317–0.357 | 95.1% |
| 9 (highest) | 0.402–0.708 | 95.2% |

Confidence carries real information — bottom decile 31.7%, top 95.2% — which
is what licenses `ModulePrediction.confidence` being used downstream as an
override signal at all. Had it been flat, the field would be decoration and
the spec would say so.

## 8. Files

```
config/classify.yaml            n-gram sizes, use_brand flag, the recorded unseen margin
src/nimo/classify/__init__.py   public surface only
src/nimo/classify/config.py     ClassifyConfig + loader, mirroring normalize/vocab.py
src/nimo/classify/features.py   char_ngrams, document_frequencies, inverse_document_frequencies,
                                tfidf_vector, cosine — pure, no I/O
src/nimo/classify/model.py      ModuleClassifier.fit / .predict -> ModulePrediction
src/nimo/classify/evaluate.py   leave_one_out, stratified_folds, evaluate -> ClassifierReport
tests/classify/                 mirrors the above exactly (`04` §2)
```

`ModuleClassifier` is a frozen dataclass, not a pydantic contract: it holds
fitted state and has behavior, so it is an implementation object of this
module rather than a value crossing a boundary. What crosses the boundary is
`ModulePrediction`, which is a contract.

## 9. Acceptance criteria

1. `nimo.loader.load_module_labels(workbook, "dev", rules)` returns 412
   labels, all in `char_value_list`'s module set, positionally aligned with
   `load_rows(workbook, "dev", retailers)`.
2. Leave-one-out over `dev` reports **overall ≥ 78% and macro ≥ 47%** with
   the committed default config. Measured: 80.3% / 49.7%.
3. Per-module accuracy is reported for **all 27** `dev` modules, including
   the four with a single row that are structurally 0%. A report that omits
   any module fails this criterion.
4. The deterministic 5-fold regression guard reproduces its pinned
   correct-row count exactly on a re-run. A change in that number is a real
   behavioral change to investigate, in the same spirit as the loader's
   `EXPECTED_*` fingerprints — not a number to quietly update.
5. `ModuleClassifier.fit` on identical input produces identical predictions
   across runs and across process restarts — no set iteration, no unseeded
   randomness, ties broken by module name (`04` §5).
6. `predict` returns a `ModulePrediction` whose `nearest_example_row_uid`
   names a real training row and whose `module` is in the fitted label set.
7. Zero network calls, zero LLM calls, zero reads of `PRODUCT_URL` (`04` §6).
8. `data/raw/` is never written (`04` §12).

## 10. Tests

Beyond `04` §11's checklist:

- **Feature purity**: `char_ngrams` is exact on hand-worked short strings,
  including the padding boundary; non-ASCII survives (`nûby`, `pärla` —
  the same rows `01` §13 and P3's tokenizer defect already concern).
- **TF-IDF definitions**: `tfidf_vector` matches a hand-computed vector on a
  3-document toy corpus, and every returned vector has unit L2 norm.
- **Unseen terms are dropped, not smoothed** — a term absent from `idf`
  contributes nothing.
- **Determinism**: fit twice, predict twice, assert identical; and assert the
  tie-break is by module name using a constructed exact tie.
- **The tail is reported**: assert the report contains an entry for every
  module in the training labels, specifically including a 1-row module.
- **Regression guard**: 5-fold correct-count pinned exactly; overall and
  macro floors asserted.
- **BRAND stays excluded**: assert the default config has `use_brand: false`,
  with the measurement in the assertion message so anyone flipping it finds
  the 7.5-point cost rather than rediscovering it.
- **No ground truth leaks into features**: assert `MODULE` text never appears
  in the feature path — the classifier is constructed from `desc_clean` only.

## 11. Definition of Done

`04` §11's full checklist, plus:

- [ ] `03` §3 carries `ModulePrediction`; `contracts.py` matches field for
  field; `specs/contracts.md`'s class list and count updated
- [ ] `04` §1's P5 row reflects the corrected gate wording (BRAND excluded,
  with the measured reason) and status `done`
- [ ] Decision-log entries for the `ModulePrediction` contract, the BRAND
  exclusion, and the unseen-module finding
- [ ] The per-module table for all 27 modules is in the phase report, not
  just the two headline numbers
