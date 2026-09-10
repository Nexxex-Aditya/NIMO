# 01 — Dataset Contract

Version 1.2 — 2026-09-10. File: `product_truth_agent_dataset.xlsx`.
Everything below was verified by direct inspection of the workbook, not
inferred from the brief. Where the brief and the file disagree, **the file
wins**. v1.1 corrected three blocking errors and several mischaracterizations
found by a second, independent verification pass against the real file. v1.2
resolves the encoding-repair gap that pass's own recommendation (§13) left
unimplemented — see `02-decision-log.md` for both rounds of changes. Where
this document and an earlier reading of it disagree, this version wins.

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
| `RETAILER_DESC` | str | Retailer product description. Real junk is coded suffixes and `unit \d+` fragments — **not** whitespace or casing (see §12: 0/412 dev rows have double spaces or leading/trailing whitespace; 412/412 are lowercase). The heavily-padded, mixed-case example elsewhere in this project came from `sample_output`, not `dev`/`qa` — don't generalize from it |
| `RETAILER` | str | Coded retailer name, e.g. `"P00R4 (GB) BOOTS"`, `"AMAZON (GB)"`. **50 distinct across `dev`+`qa` combined** — not 44; 44 was a dev-only count. See §12 — a mechanical parser fails on 21 of the 50 |
| `BRAND` | str | Brand, e.g. `"AQUAFRESH (HALEON)"`. The `(OWNER)` suffix is **not universal** — 71 of 171 distinct brands (42%) have no owner in parens, e.g. `"GENGIGEL"`. Treat no-parens as the common case a parser must handle, not a rare exception |

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
  `GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS` is null in 0 rows (always applicable
  — though see §13, 7 of the non-null values are stored as bare `'1'` rather
  than the guideline's `99%`-style format, a dev ground-truth inconsistency to
  be aware of, not something to silently "fix" away); `GLOBAL_BRISTLE_STRENGTH_CLAIM`
  null in 306 (toothbrush-only).
- **`GLOBAL_INTERSPACE_CLAIM` is null in all 412 `dev` rows, but it is not a
  dead column — don't read the null rate as "never applicable."** It's
  applicable to exactly one module, `TOOTHBRUSHES - MANUAL - INTERDENTAL`,
  which happens to have zero `dev` rows — but **two `qa` rows** are candidates
  for it (`nan_key` 45138583 and 55543381, both mention "interdental" in
  `RETAILER_DESC`). The applicability logic must mark this characteristic
  applicable for that module regardless of `dev`'s coverage, and predict it
  for those two `qa` rows specifically.
- **The applicability cross-check is resolved, confirmed exact.** With the
  corrected characteristic-name alias map (§8), `dev`'s fill/null pattern
  agrees with `char_value_list` on all 412 rows in both directions — zero
  violations — and per-characteristic, the filled count equals the
  applicable-module row count for all 13 characteristics. `MODULE`
  deterministically determines the null pattern. This was flagged as an open
  risk in an earlier version of this document; it no longer is. The stakes
  this raises: get `MODULE` right (stage 5) and the applicability gate is
  provably free; get it wrong and both the characteristic *and* its correct
  null pattern are lost together.

## 7. `char_value_list` — the applicability and vocabulary table

195 rows. Columns: `category`, `module`, `characteristic`, `open_close`,
`binary`, `possible_values`, `Notes`. **`characteristic` is in spaced,
uppercase form here too** (`"GLOBAL BRISTLE STRENGTH CLAIM"`) — not
underscored. An earlier version of this document said otherwise; it was
wrong. Both rule sheets (`char_value_list` and `char_guidelines`) use spaced
names; only `dev`/`qa` are underscored. See §8 for the normalization this
requires.

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
a hard constraint at generation time — no LLM free-text into a closed field —
**but see §11: "one of `possible_values`, exactly" is true per component, not
per whole string.** A closed value can be an `&`-joined combination of
multiple allowed values, and that's the common case for two characteristics
specifically, not a rare exception.

## 8. `char_guidelines`

196 rows: `HALEON CATEGORY`, `MODULE NAME`, `CHARACTERISTICS NAME`, `Guidelines`.
Free-text business rules for translating page evidence into values. Retrieve the
relevant row(s) and inject into the extraction prompt for the specific
(module, characteristic) pair being predicted — do not dump all 196 into
context.

**Corrected characteristic-name mapping** (an earlier version of this document
had this wrong — it said `char_value_list` was already underscored like
`dev`/`qa`; it isn't). The real split: `char_value_list` **and**
`char_guidelines` both use spaced, uppercase names
(`"GLOBAL BRISTLE STRENGTH CLAIM"`); `dev`/`qa` use underscored ones
(`"GLOBAL_BRISTLE_STRENGTH_CLAIM"`). Both rule sheets need normalizing against
the `dev`/`qa` form, not just `char_guidelines` against `char_value_list`.

**The mapping is not a pure mechanical transform — 12 of 13 names normalize by
space→underscore (with `/` also → `_`), one does not:**

    GLOBAL FLAVOUR/FRAGRANCE/INGREDIENT GROUP  ->  GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP   (mechanical: space and / both -> _)
    GLOBAL IF WITH INTERSPACE CLAIM            ->  GLOBAL_INTERSPACE_CLAIM                      (NOT mechanical: "IF WITH " is dropped)

A naive space→underscore normalizer produces
`GLOBAL_IF_WITH_INTERSPACE_CLAIM` for the second case, which is not a real
`dev`/`qa` column — an assertion that the mapping is "total and bijective
under a single pure function" (as an earlier version of `specs/loader.md`
required) **will raise and halt P2 on the real file.** The fix: a small
hand-coded alias table for exceptions to the mechanical rule, checked first,
falling back to the mechanical transform for the other 12. Don't chase a
cleverer regex that happens to cover this one case — a two-entry exception
table (currently one entry) is more honest about what's actually going on than
a rule "clever" enough to absorb an irregular abbreviation.

Assert the mapping is total and bijective **after** the alias table is
applied — that check is still correct and still required, it just can't be
the *only* mechanism.

Also assert `MODULE NAME` values in `char_guidelines` are a subset of the
module set from `char_value_list` — this is a cross-sheet consistency check
the organizers' own files should satisfy; if they don't, that's worth
surfacing (a candidate organizer question), not silently absorbing.

## 9. Distribution notes (dev)

- **Modules are severely long-tailed.** Top 4 cover 317/412 (77%):
  tooth cleaning paste/gel 133, multi-dose mouthwash 94, manual toothbrush 52,
  electric toothbrush complete pack 38. 27 modules present in dev out of 59
  defined; many have 1–3 rows.
  → Stratify any eval split by module. Report per-module accuracy, not just
  overall, or the tail will be invisible.
- **Country**: 322 rows are GB-only; the rest are comma-joined multi-market
  lists always containing GB. Treat GB as the retrieval market.
- **Retailer**: **50 distinct across `dev`+`qa` combined** — not 44; that was
  a `dev`-only count. Heavy at Boots (49), Amazon GB (44+29), Positive
  Solutions (37), Brandbank (36) within `dev`. See §12 for parsing this field.
- **dev/qa overlap**: 40 `ITEM_CODE` values are common to both — but this
  overlap is **not usable as a clean-barcode Tier-0 demonstration**, the
  barcode corruption defect (§3) hits it too. Separately, and not yet used in
  any design decision: **23 `NAN_KEY` values are also common to both sets** —
  a tighter, distinct overlap worth keeping in mind if `NAN_KEY` turns out to
  be a more reliable repeat-observation signal than `ITEM_CODE`.

## 10. Loader acceptance criteria

Any dataset loader must:

1. Read `EXTERNAL_CODE` as `str` from all three sheets; strip leading `'`;
   emit `barcode_valid: bool` and `barcode_corrupt_rounded: bool` per row.
2. Refuse to start if `dev` barcode corruption rate differs from the recorded
   377/412 — the file changed, re-verify everything here.
3. Parse `possible_values` via `ast.literal_eval` into `list[str]`.
4. Build a `(module, characteristic) -> {open_close, binary, allowed_values}`
   lookup, and expose `applicable_characteristics(module) -> list[str]`.
5. Normalize characteristic names from **both** `char_value_list` and
   `char_guidelines` (both spaced-form, §7/§8) to the underscored form
   `dev`/`qa` use, via a hand-coded alias table for the one irregular case
   (§8) falling back to mechanical space/slash→underscore for the rest.
   Assert the resulting mapping is total and bijective.
6. Split `COUNTRY` into `list[str]`; collapse whitespace in `RETAILER_DESC`
   (verified a no-op on real `dev`/`qa` data — §2, §12 — keep it anyway as a
   cheap defensive no-op, don't remove it on the strength of that finding).
7. Emit `qa` predictions with `qa`'s exact header, exact column order, no extra
   columns, no reordered rows.
8. Validate closed characteristics **per `&`-separated component**, not
   against the whole string — §11. A component-wise check that a 2- or
   3-part combination's every part is in `possible_values` is correct; a
   whole-string equality check is not and will reject valid answers.
9. Repair encoding-corrupt `BRAND`/`RETAILER_DESC` values via `ftfy` — never
   silently: always flag whenever a repair actually changed the value — §13.

## 11. DEFECT — closed-characteristic ground truth uses `&` as a combinator

189 of `dev`'s 412 ground-truth characteristic values violate "must be one of
`possible_values`, exactly" as a whole-string check. 187 of those are
`&`-joined combinations of individually-valid allowed values — 176 in
`GLOBAL_ORAL_CARE_FUNCTION`, 11 in `GLOBAL_CONSUMER_LIFESTAGE_CLAIM`; 123
two-component, 64 three-component. No individual allowed value anywhere in
`char_value_list` contains `&`, so it's unambiguous as a combinator, never
part of a value. `sample_output` confirms the same pattern:
`GLOBAL_ORAL_CARE_FUNCTION = 'ANTI BACTERIAL & FRESHENING & WHITENING'`.

**A validator that checks the whole string against `possible_values` rejects
the organizers' own reference answers.** The fix is small — split on `&`,
validate each component independently against `possible_values` — but it's
load-bearing: it changes the closed-field validation contract (§10 point 8)
and the security argument that depends on it (closed fields being
"structurally immune" to prompt injection assumed whole-string validation;
component-wise validation is still a hard constraint, just implemented
differently — each component must still be in a fixed vocabulary, so the
immunity claim holds, but the mechanism description needs to match reality).

The remaining **2 of the 189** are not the `&` pattern — they're a genuine
organizer data error: `GLOBAL_PACKAGING_MATERIAL = 'GLASS'` for module
`TOOTH CLEANING - GUM/TABLETS (NATURAL TEETH)`, where the allowed set is
`['CARDBOARD', 'PAPER', 'PLASTIC']`. Worth raising with the organizers; not
something to design around.

## 12. DEFECT — the `RETAILER` field has no reliable mechanical parse

50 distinct `RETAILER` values across `dev`+`qa` (§2, §9 — not 44). An
`(?:[A-Z0-9]{4,6}\s+)?\([A-Z]{2,3}\)\s*(?P<name>.+)`-style regex — the
obvious first attempt, matching the `[CODE] (COUNTRY) NAME` shape — **fails
to match 21 of the 50 (42%).**

Most of those 21 fail *loudly* (no match, falls back to the unmodified raw
string) — annoying but safe: `"AMAZON (GB)"` and `"BRANDBANK (UK)"` keep
their `(COUNTRY)` suffix attached instead of being stripped, because a
6-letter all-caps brand name like `AMAZON` matches the optional
`[A-Z0-9]{4,6}` "code" group just as well as a real code does, leaving
nothing for `(?P<name>.+)` to capture and forcing the whole match to fail.
`"InTouch (GB)"` fails for a different reason — mixed case doesn't match
`[A-Z0-9]{4,6}` at all.

**One fails *silently*, which is the dangerous case:** `"BOOTS (GB)
(HOMESCAN)"` **does** match — `BOOTS` satisfies the optional code group,
`(GB)` satisfies the country group, and `(?P<name>.+)` captures whatever's
left: `"(HOMESCAN)"`. The retailer name most worth getting right in this
whole dataset (Boots is the single largest retailer, 49 rows) gets silently
discarded and replaced with a value that isn't a retailer name at all — no
exception, no warning, a plausible-looking wrong string flows downstream.
This is a live instance of the latent-failure class `05` §5 exists to name,
not a hypothetical one.

**Given the field has only 50 distinct values total, the right design is not
a cleverer regex — it's a hand-reviewed lookup table**, the same pattern
already committed to for `config/retailers.yaml`'s domain mapping (`03` §4
stage 2, S4). A regex can generate a first-pass draft of that table, but
every one of the 50 entries needs human review before the table is trusted,
given a 42% mechanical failure rate including one silent wrong answer.
`specs/loader.md` needs updating accordingly (see decision log).

## 13. Undocumented defect — character encoding corruption

Not previously documented anywhere in this project.

- `dev.BRAND` contains `'JASÃƒâ€“N'` (3 rows) — the signature of **double-encoded
  UTF-8** (a UTF-8 byte sequence that was decoded as Latin-1/CP1252 and then
  re-encoded as UTF-8). The real value is presumably `JASÖN`.
- 10 `dev` and 13 `qa` `RETAILER_DESC` rows contain non-ASCII characters,
  mixing two genuinely different things that need different handling:
  legitimate multilingual text (`pärla`, `antibactérien`, `colgate®`) and
  actual corruption (a mangled `¿` appearing mid-word, e.g. `"...fights root
  cause"` with a stray replacement-adjacent character where an apostrophe or
  similar should be).
- `sample_output`'s `PRODUCT_URL` contains a `U+2011` non-breaking hyphen —
  minor, but URL canonicalization (`03` §4 stage 2) needs to normalize this
  class of lookalike-character rather than treat it as a literal hyphen.

This matters concretely for query construction (`03` §4 stage 2) — a mojibake
string fed verbatim into a search query returns garbage results, silently
degrading retrieval recall for exactly those rows with no error anywhere to
signal it.

**Handling, verified, not just recommended:** use `ftfy.fix_text()` rather
than a hand-rolled Latin-1/UTF-8 roundtrip — tested directly against the real
corrupted value, `ftfy.fix_text("JASÃƒâ€“N")` correctly recovers `"JASÖN"` in
one call (this is genuinely *double* mis-encoded, which a single-pass
roundtrip would not fully repair). Tested separately that it's a safe no-op
on legitimate multilingual text already in the data — `pärla`,
`antibactérien`, `colgate®` all pass through unchanged. Apply it
unconditionally (don't branch on "does this look corrupted" first — that's
what the library already does internally, more reliably than a hand-written
heuristic would); set `*_encoding_suspect: bool` to whether the value
actually changed. Implementation: `specs/loader.md` §2a.

