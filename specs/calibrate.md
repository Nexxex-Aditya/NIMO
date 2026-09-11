# specs/calibrate.md — P10: Calibration & abstention

Authority: `03-architecture.md` §4 stage `[4]` ("Calibration", "Abstention",
"Write-back"). `04` §13 names calibration among the **HARD-20%** areas.
Depends on P9 (`MatchFeatures.raw_score`, the GTIN hard rule) and the wired
runner (`src/nimo/run/live.py`), which is what produces the instrument.

---

## 1. The instrument — and why the gold set is not it

`03` §4 stage 4: "Fit a calibration map (isotonic or Platt) on the
hand-labelled URL gold set so `calibrated_prob` is an actual probability."

The hand-labelled gold set is **5 URLs, none with a usable GTIN**
(`specs/match.md` §1). A calibration curve fitted on five points is a drawing,
not a measurement, and P9 recorded the live result on those five as unstable
between runs. Fitting there would produce a `calibrated_prob` that looks like
a probability and is not — the plausible-wrong-value shape `05` §5 names, on
the one field downstream abstention keys off.

**The instrument that exists is the GTIN hard rule, applied on `qa`.** Every
`qa` row carries a clean barcode (`01` §3: 412/412). Any fetched candidate
whose page publishes a GTIN is therefore *labelled for free*:

- page GTIN == query barcode ⇒ **this candidate is the product** (`03` §4
  stage 4 calls it near-decisive);
- page GTIN != query barcode ⇒ **this candidate is not** — a confirmed
  different product regardless of text;
- page has no GTIN ⇒ unlabelled, excluded from the fit.

That yields, for every labelled candidate, the pair
`(weighted_score_before_hard_rules, correct)`. Fitting `P(correct | score)` on
those pairs calibrates the **text-only** score using ground truth from the
**identifier** — which is exactly the population the calibrated score will be
used on: rows and pages where no GTIN is available (394 of 412 `dev` rows;
~70% of pages, `specs/fetch.md` §1).

The full-`qa` run through the wired pipeline (`uv run python -m nimo.run
--sheet qa --live`) is the harvest. Its `fetch` artifacts hold every
candidate's evidence; the pairs are recomputed from them offline, with no
network, so the fit is reproducible from committed artifacts.

**Selection bias, stated.** Pages that publish a GTIN are structured-data-rich
retailers (chemist-4-u, pharmazondirect, wholedent), not Amazon or the bot
walls. The calibration is fitted on the well-behaved end of the web and applied
to the whole of it. That is a limitation to report with the curve, not a reason
to fit on five points instead.

## 2. The fit — isotonic, hand-written

Isotonic regression via pool-adjacent-violators, ~40 lines. Same reasoning as
P5's classifier: no scikit-learn, no untyped import to buy an implementation of
something that fits on one screen and is unit-tested against hand-worked cases.
Isotonic over Platt because it makes no shape assumption — with a hard-rule
floor and demotion penalties in the score, the relationship is not sigmoid and
should not be forced to be.

Prediction for a new score: step function — the fitted value of the nearest
bin at or below the score; scores below the lowest fitted bin get that bin's
value. Monotone by construction, so a higher raw score never yields a lower
probability.

**Minimum sample size, enforced at fit time.** Fewer than
`min_labelled_pairs` labelled pairs ⇒ `CalibrationError`, not a curve. The
number is in `config/thresholds.yaml` with its reasoning. Below it,
`calibrated_prob` keeps mirroring `raw_score` and the run summary says so.

## 3. Abstention — `[PROVISIONAL — Q3]`

`03` §4 stage 4: "If `calibrated_prob < τ`, emit no URL. Whether that is
correct depends on whether a wrong URL is penalized more than a blank one."
Q3 is open. So:

- `tau_abstain` is a config value, applied to the **calibrated** probability
  only, never to `raw_score`;
- it is set to the value at which the fitted curve's probability of being
  right equals its probability of being wrong (0.5) — the only threshold with
  a defensible meaning absent a scoring rule — and marked provisional;
- until a calibration is fitted, abstention is **off** (`tau_abstain: 0.0`),
  because thresholding an uncalibrated number is thresholding noise.

## 4. `tau_merge` — the second write-back trigger

`03` §4 stage 4 gates write-back on a GTIN accept **or** `calibrated_prob ≥
τ_merge`. P9 shipped the first only. With a fitted calibration the second
becomes meaningful, and `tau_merge = 0.95` (P6, derived) is the bar: a merge
at a calibrated 95% is a merge that is wrong one time in twenty, and each of
those poisons every row that blocks against it (`03` §1a). The bar stays
strict; it is not lowered to make the registry fill faster.

## 5. What the gate reports

`04` §1: "Calibration curve reported." Concretely:

- number of labelled pairs, positives and negatives, and the number of `qa`
  rows they came from;
- the fitted step function (bin edges and values);
- **reliability**: for each bin, predicted probability vs observed rate, and
  the expected calibration error;
- **the abstention trade-off**: at each candidate `tau_abstain`, how many rows
  abstain and what the precision of the remaining selections is;
- the selection bias caveat from §1, every time.

If the harvest yields fewer than `min_labelled_pairs`, the report says so and
no curve is claimed. That is a valid gate outcome.

## 6. Files

```
config/thresholds.yaml           tau_abstain, min_labelled_pairs (tau_merge exists)
data/calibration/pairs.jsonl     harvested (score, correct) pairs — committed, reproducible
data/calibration/curve.json      the fitted step function — committed
src/nimo/calibrate/isotonic.py   PAV fit + predict — pure
src/nimo/calibrate/harvest.py    fetch artifacts -> labelled pairs — offline
src/nimo/calibrate/report.py     reliability + abstention trade-off
tests/calibrate/
```

## 7. Acceptance criteria

1. PAV reproduces hand-worked fits, including a violator pool.
2. Prediction is monotone non-decreasing in the raw score.
3. Fewer than `min_labelled_pairs` ⇒ `CalibrationError`; the mirror stays.
4. `calibrated_prob` diverges from `raw_score` **only** when a curve is
   loaded — `test_calibrated_prob_mirrors_raw_score_until_p10` is replaced by
   a test of both states, deliberately.
5. Abstention applies to calibrated probability only.
6. The harvest is reproducible from committed artifacts with zero network.
7. The report states n, the bias caveat, and the reliability table.
