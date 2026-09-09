# 01 — Dataset Contract

File: `product_truth_agent_dataset.xlsx`. Everything below was verified by
direct inspection of the workbook, not inferred from the brief. Where the brief
and the file disagree, **the file wins**.

## 1. Sheets

| Sheet | Rows × Cols | Role |
|---|---|---|
| `dataset_understanding_guide` | 24 × 3 | Organizer's notes on how to read the workbook |
| `sample_output` | 6 × 23 | Reference output format + expected reasoning depth |
| `dev` | 412 × 23 | Development set. Partial ground truth (see §3) |
| `qa` | 412 × 23 | Evaluation set. No ground truth. **This is what we submit** |
| `char_value_list` | 195 × 7 | Module → applicable characteristics → allowed values |
| `char_guidelines` | 196 × 4 | Business rules for interpreting evidence into values |
| `S` | 0 × 0 | Empty. Ignore |

## 2. Column schema

**Input columns** (`dev` and `qa`, identical):

| Column | Type | Notes |
|---|---|---|
| `ITEM_CODE` | int | NIQ internal item id. **Not unique** — 331 distinct over 412 dev rows |
| `NAN_KEY` | int | NIQ internal key. 385 distinct over 412 rows |
| `EXTERNAL_CODE` | see §3 | GTIN/EAN barcode |
| `COUNTRY` | str | ISO-2, comma-joined for multi-market items (`"BE,GB,NL"`). GB present in every row |
| `RETAILER_DESC` | str | Raw retailer product description. Noisy: lowercase, coded suffixes, padded whitespace |
| `RETAILER` | str | Coded retailer name, e.g. `"P00R4 (GB) BOOTS"`, `"AMAZON (GB)"`. 44 distinct |
| `BRAND` | str | Brand with owner in parens, e.g. `"AQUAFRESH (HALEON)"` |

**Output columns** (what we must produce):

| Column | Notes |
|---|---|
| `PRODUCT_URL` | See §5 — the sample fills this with page *titles*, not URLs |
| `REASONING` | Free-text evidence-grounded justification |
| `MODULE` | Closed set. Determines which characteristics apply |
| `GLOBAL_INTERSPACE_CLAIM` | |
| `GLOBAL_CONSUMER_LIFESTAGE_CLAIM` | |
| `GLOBAL_PACKAGING` | |
| `GLOBAL_IF_MEDICATED` | |
| `GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS` | |
| `GLOBAL_IF_WITH_SENSITIVE_CLAIM` | |
| `GLOBAL_ORAL_CARE_FUNCTION` | |
| `GLOBAL_IF_WITH_FLUORIDE` | |
| `GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP` | |
| `GLOBAL_METHOD_OF_APPLICATION_DISPENSE` | |
| `GLOBAL_PACKAGING_MATERIAL` | |
| `GLOBAL_DESCRIPTIVE_SIZE_OF_TOOTHBRUSH_HEAD_CLAIM` | |
| `GLOBAL_BRISTLE_STRENGTH_CLAIM` | |

Schema drift to handle: `sample_output` has `ITEM_DIST` where `dev`/`qa` have
`COUNTRY`+`RETAILER`, and carries a 14th characteristic
`GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT` that `dev`/`qa` do not. Treat `qa`'s
header as the submission contract; treat `sample_output` as illustrative only.

## 3. DEFECT — barcodes in `dev` are destroyed

`EXTERNAL_CODE` in `dev` is stored as a **number with cell format `0.00E+00`**,
which has rounded the values to ~3 significant figures:

    5000000000000, 5030000000000, 8010000000000, 6280000000000, ...

- **377 of 412** dev rows are corrupted this way.
- Only **98 distinct** values survive across 412 rows.
- `qa` is **clean** — barcodes there are stored as text strings and intact
  (`"5014697056627"`).
- `sample_output` stores them as text with a leading apostrophe (`'8714789613970`)
  which must be stripped on read.

Consequences, and these are architectural, not cosmetic:

1. The barcode is the single strongest identity signal available, and it is
   unusable for most of the dev set. Any pipeline that leans on exact-GTIN
   lookup will look broken in dev and fine in qa, or vice versa.
2. Dev cannot be used to tune a barcode-matching component. Tune on the 35
   intact rows only, or reconstruct barcodes from `ITEM_CODE`/`NAN_KEY` joins if
   a clean source exists.
3. Loader must parse `EXTERNAL_CODE` as **string, never numeric**, and must
   flag rounded values rather than silently passing them downstream. A row whose
   barcode matches `^\d{1,3}0{6,}$` is not a barcode; it is a hole.
4. Ask the organizers for a corrected `dev` sheet. This is worth doing early.

## 4. DEFECT — the promised candidate webpages are absent

The brief lists *"a set of candidate webpages with extracted content and
metadata"* as part of the dataset. There is no such sheet, column, or file.
`PRODUCT_URL` is **100% null in both `dev` and `qa`**.

Therefore candidate generation is our problem: query construction from
`RETAILER_DESC` + `BRAND` + `EXTERNAL_CODE` + `COUNTRY`, retrieval via
meta-search (SearxNG, per project context), fetch, parse. That is a whole
subsystem the brief assumed away.

## 5. DEFECT — `PRODUCT_URL` in `sample_output` holds titles, not URLs

Observed values:

    "Buy Colgate Total Whitening Toothpaste Pump, 100 ml Online at Low Prices in India - Amazon.in"
    "Gengigel Mouthrinse 150ml | Toiletries | Superdrug"

These are HTML `<title>` strings. Either the organizers exported titles by
mistake, or the expected submission value is the page title. Unresolved —
**flag for clarification**. Until resolved, emit the real URL and carry the page
title in a side column so either interpretation can be satisfied.

Note also that the Colgate example resolves to **Amazon.in** for a `FR,GB` item.
If that is genuinely the accepted answer, the market-consistency constraint is
weaker than it looks — a country-mismatch hard filter would reject the
organizers' own reference answer. Do not hard-filter on domain TLD; score it.

## 6. What ground truth actually exists

| Column | `dev` | `qa` |
|---|---|---|
| `MODULE` | **fully populated (412/412)** | empty |
| 13 characteristics | partially populated, module-dependent | empty |
| `PRODUCT_URL` | empty | empty |
| `REASONING` | empty | empty |

Read this carefully: **there is no URL ground truth anywhere.** The guide claims
`dev` "contains the ground truth", but what it contains is ground truth for
stage 2 (module + characteristics), not stage 1 (URL).

Direct implications:

- Stage-1 URL selection **cannot be scored directly**. It can only be evaluated
  *indirectly*, via whether the page it selected yields the correct module and
  characteristics — or by hand-labelling a small URL set ourselves.
- Build a hand-labelled URL gold set (~50 rows, stratified by module) early.
  Without it, stage-1 regressions are invisible.
- Characteristic null-rates in `dev` are the applicability signal. Examples:
  `GLOBAL_INTERSPACE_CLAIM` is null in all 412 rows (never applicable in this
  sample); `GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS` is null in 0 rows (always
  applicable); `GLOBAL_BRISTLE_STRENGTH_CLAIM` null in 306 (toothbrush-only).
  Cross-check these rates against `char_value_list` — disagreement between the
  two is a bug in our applicability logic or in the sheet, and needs resolving
  before it silently costs score.

## 7. `char_value_list` — the applicability and vocabulary table

195 rows. Columns: `category`, `module`, `characteristic`, `open_close`,
`binary`, `possible_values`, `Notes`.

- `category` is `ORAL HEALTH` for every row. Single-category problem.
- **59 distinct modules**, **13 distinct characteristics**. The table is the
  (module × characteristic) applicability matrix — a pair absent from this table
  is a characteristic that must be left empty for that module.
- `open_close`: `Close` (106 rows) — prediction must be one of `possible_values`,
  exactly. `Open-ended` (89 rows) — `possible_values` is illustrative; derive
  from evidence but stay consistent with `char_guidelines`.
- `binary`: `Y` for 41 rows, `N` for 154.
- `possible_values` is a **string containing a Python-style list literal**:
  `"['HARD', 'MEDIUM', 'NO CLAIM', 'SOFT']"`. Parse with `ast.literal_eval`,
  not `eval`, and not string-splitting.

Load this as a validation schema, not documentation. Closed characteristics get
a hard constraint at generation time — no LLM free-text into a closed field.

## 8. `char_guidelines`

196 rows: `HALEON CATEGORY`, `MODULE NAME`, `CHARACTERISTICS NAME`, `Guidelines`.
Free-text business rules for translating page evidence into values. Retrieve the
relevant row(s) and inject into the extraction prompt for the specific
(module, characteristic) pair being predicted — do not dump all 196 into
context.

Column-name mismatch: this sheet uses spaced, uppercase names
(`GLOBAL BRISTLE STRENGTH CLAIM`) while `dev`/`qa` use underscored ones
(`GLOBAL_BRISTLE_STRENGTH_CLAIM`). Normalize on load; assert the two vocabularies
reconcile 1:1 and fail loudly if they don't.

## 9. Distribution notes (dev)

- **Modules are severely long-tailed.** Top 4 cover 317/412 (77%):
  tooth cleaning paste/gel 133, multi-dose mouthwash 94, manual toothbrush 52,
  electric toothbrush complete pack 38. 27 modules present in dev out of 59
  defined; many have 1–3 rows.
  → Stratify any eval split by module. Report per-module accuracy, not just
  overall, or the tail will be invisible.
- **Country**: 322 rows are GB-only; the rest are comma-joined multi-market
  lists always containing GB. Treat GB as the retrieval market.
- **Retailer**: 44 distinct, heavy at Boots (49), Amazon GB (44+29), Positive
  Solutions (37), Brandbank (36).
- **dev/qa overlap**: only 40 `ITEM_CODE` values are common to both. The sets
  are largely disjoint — no leakage, but also no free answers.

## 10. Loader acceptance criteria

Any dataset loader must:

1. Read `EXTERNAL_CODE` as `str` from all three sheets; strip leading `'`;
   emit `barcode_valid: bool` and `barcode_corrupt_rounded: bool` per row.
2. Refuse to start if `dev` barcode corruption rate differs from the recorded
   377/412 — the file changed, re-verify everything here.
3. Parse `possible_values` via `ast.literal_eval` into `list[str]`.
4. Build a `(module, characteristic) -> {open_close, binary, allowed_values}`
   lookup, and expose `applicable_characteristics(module) -> list[str]`.
5. Normalize characteristic names between spaced and underscored forms, with an
   assertion that the mapping is total and bijective.
6. Split `COUNTRY` into `list[str]`; strip and collapse whitespace in
   `RETAILER_DESC`.
7. Emit `qa` predictions with `qa`'s exact header, exact column order, no extra
   columns, no reordered rows.
