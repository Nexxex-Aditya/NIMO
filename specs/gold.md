# specs/gold.md — P4: Hand-labelled URL Gold Set

Authority: `03-architecture.md` §6 (L3/L4), `01-dataset-contract.md` §6 (why
this must exist), `04` §1 (P4 gate).

Depends on P2 (loader) and P3 (normalizer) for the rows being labelled.

## Why this phase exists, and why it comes before retrieval

`01` §6: **there is no URL ground truth anywhere in the dataset.**
`PRODUCT_URL` is 100% null in both `dev` and `qa`. So stage-1 URL selection
cannot be scored against the workbook at all — only against a set we build
ourselves. `04` §1 puts P4 before P7 deliberately: "building retrieval before
you can measure it produces confident, unmeasurable code."

Downstream, this set is the *only* input to:

- **L3** — URL correctness (`03` §6)
- **L4** — abstention calibration: whether `calibrated_prob` is honest
- **P9** — precision@1 gate
- **P10** — the isotonic/Platt fit, and `τ_abstain` / `τ_merge` / `τ_ann`

## The rule that matters more than the count

**A fabricated, guessed, or plausible-looking-but-unverified URL is worse
than a missing one.** It does not fail; it silently miscalibrates every
threshold fitted against it and every precision number reported from it —
the exact latent-failure shape `05` §5 exists to name, injected directly
into the measurement instrument. There is no downstream check that would
catch it, because this *is* the check.

Therefore:

- Every `label: "correct"` entry must have been opened and inspected.
- A row that cannot be resolved is recorded as `no_page_found` or
  `ambiguous`, **not** omitted silently and **not** filled optimistically.
- `evidence` states what was actually checked on the page (brand, size,
  variant, format, barcode if shown). "Looks right" is not evidence.
- Partial coverage is acceptable and expected; a partial honest set is
  strictly more useful than a full invented one. Report the count.

## Contract

`GoldUrl` in `03` §3 (added for this phase — see `02-decision-log.md`).
Stored as JSON Lines at `data/gold/urls.jsonl`, one object per line, sorted
by `(sheet, nan_key)` so the file is diffable and the order is deterministic.

`data/gold/` is **not** gitignored (`specs/scaffold.md`) — this is
hand-produced, expensive, and irreplaceable state.

## Stratified sample selection

`03` §6 asks for "~50 rows stratified by module". Straight random sampling
would be wrong here: `01` §9 records that the top 4 modules are 317/412 of
`dev` (77%), so a proportional sample would leave most of the 27 modules with
zero rows and per-module accuracy unmeasurable for the tail — the precise
failure `01` §9 warns about.

Selection rule, deterministic and committed:

1. Group `dev` rows by `MODULE`.
2. Take up to `per_module_floor` rows from every module, so each module
   present in `dev` is represented before any module gets a second row.
3. Distribute the remaining slots over modules by descending row count,
   round-robin, so the big modules get proportionally more without starving
   the tail.
4. Within a module, order by source position (`row_uid`) ascending and take
   from the front. Ordering by `nan_key` would be wrong twice over — it is
   not unique, so a `nan_key`-keyed selection silently drops rows, and its
   numeric order is meaningless where the value is a rounding artifact
   (`01` §14).

Deterministic in the `04` §5 sense: same workbook in, same sample out, no
randomness at all. The sampler is a pure function of the loaded rows and is
tested for stability.

**The sample is frozen to `data/gold/sample.txt`, not recomputed on demand.**
This was learned the hard way during P4: the sampler originally selected by
`nan_key`, that turned out to be non-unique (`01` §14), and fixing it changed
which 50 rows were chosen — *after* labels had been written against the old
selection. A recomputed sample can silently re-base the measurement set under
existing labels, with no error. A test asserts the frozen file still equals
the sampler's output, so any future sampler change fails loudly instead.

`dev` only. `qa` has no `MODULE`, so it cannot be stratified, and `dev` is
where the module labels that make stratification meaningful live.

## Verification procedure (what "hand-labelled" means here)

For each sampled row, using its `ProductQuery` (P3 output — `brand`,
`desc_clean`, `tokens.size_value`/`size_unit`, `tokens.count`,
`tokens.variant_terms`):

1. Search for the product by brand + variant + size.
2. Open the most plausible result.
3. Confirm on the page: **brand**, **size** (matching `size_ml_equiv` /
   `size_g_equiv`), **variant**, and **pack count** where the query has one.
   Record which of these were confirmed in `evidence`.
4. Reject and keep looking if the page is a different size, a different
   pack count, a refill vs. complete pack, or a bundle — these are exactly
   the "similar or misleading matches" the brief's success criteria name.
5. If no page can be confirmed after a reasonable search, record
   `no_page_found`. If two pages are equally defensible, record `ambiguous`.

`label` values, and what each means downstream:

| `label` | `url` | Meaning for L3/L4 |
|---|---|---|
| `correct` | set | The verified true page. Counts in precision@1. |
| `no_page_found` | `None` | No page exists//was findable. A correct abstention. |
| `ambiguous` | `None` | Two-plus defensible pages. Excluded from precision; useful for calibration. |

## Acceptance criteria (P4 gate)

1. `data/gold/urls.jsonl` exists, committed, one valid `GoldUrl` per line.
2. Every line parses into `GoldUrl` and round-trips through JSON.
3. Every `row_uid` is a real `dev` row, and no `row_uid` appears twice.
   Keyed on `row_uid`, **not** `nan_key` — `01` §14: `NAN_KEY` collides
   across genuinely different products, so it cannot identify a label's row.
4. `label == "correct"` implies `url` is a non-empty `http(s)` URL;
   any other label implies `url is None`. No entry has a URL without a label
   or a label without evidence.
5. The sampler is deterministic — two runs over the same workbook produce
   an identical sample.
6. Stratification is real: every module represented in the sample has at
   least one row, and the sample covers more modules than a proportional
   sample of the same size would.
7. The loader for this file fails loudly on a malformed line rather than
   skipping it (`04` §4).
8. `make check` green (or its four commands, `04` §11).

9. The frozen sample (`data/gold/sample.txt`) still equals the sampler's
   output, and covers every module present in `dev` (27/27).

**Explicitly not a gate: reaching 50 entries.** The number is a target from
`03` §6, not a correctness property, and inventing rows to reach it would
defeat the phase. The committed count and the remaining unlabelled sample
are both reported.

## Coverage as committed

**6 of 50 sampled rows are labelled: 5 `correct`, 1 `ambiguous`.** Every one
was searched for, opened in a browser and inspected; the `evidence` field on
each says what was confirmed. The remaining 44 are unlabelled — not
`no_page_found`, which would be a claim I have not earned by searching, but
simply not yet done.

This is a deliberately partial artifact, and `specs/gold.md`'s own rule is
why: at ~4 minutes and several searches per row, inventing the other 44 to
hit the round number in `03` §6 would have produced a measurement instrument
that silently miscalibrates P9's precision@1 and P10's threshold fit. A
6-entry honest set plus a frozen 50-row sample is resumable in one sitting;
a 50-entry invented one is worse than nothing and undetectable.

Two of the six (`dev:205`, `dev:410`) were labelled before the sample was
frozen and are outside the current 50 — named explicitly in the tests rather
than quietly excused.

Worth recording for whoever continues this: `tesco.com` returned a
bot-protection interstitial rather than the product page, so a row whose
correct answer is almost certainly a Tesco URL (`dev:193`, Diamond Whites
Black Edition 32g — the search result title matches exactly) could not be
confirmed by opening it and was left unlabelled rather than accepted on the
strength of a search snippet. That is a live instance of `05` §5's
"aggregate domain block" reaching the *labelling* process, not just the
fetcher, and it bears on Q6.
