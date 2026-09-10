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
4. Within a module, order by `nan_key` ascending and take from the front.

Deterministic in the `04` §5 sense: same workbook in, same sample out, no
randomness at all. The sampler is a pure function of the loaded rows and is
tested for stability.

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

**Explicitly not a gate: reaching 50 entries.** The number is a target from
`03` §6, not a correctness property, and inventing rows to reach it would
defeat the phase. The committed count and the remaining unlabelled sample
are both reported.
