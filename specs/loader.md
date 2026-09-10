# specs/loader.md — P2: Dataset Loader

Authority: `01-dataset-contract.md` (schema, defects, §10 acceptance criteria),
`03-architecture.md` §3 (`RawRow`, `CharacteristicRule`,
`CharacteristicGuideline` contracts). Read both fully before writing code —
this spec assumes their content, it doesn't restate all of it.

Depends on P0 (scaffold) and P1 (contracts — `specs/contracts.md` — must
already exist in `src/nimo/contracts.py`). Do not start this phase with P1
incomplete.

## Precondition

`data/raw/product_truth_agent_dataset.xlsx` present, per `specs/scaffold.md`'s
precondition. If it's still absent, stop and say so — do not write a loader
against assumptions instead of the real file.

**`config/retailers.yaml`'s `name` field, for all 50 entries, is also a
precondition of this phase being done — not deferred to P7.** §4 below
replaced regex-based retailer parsing with a lookup into this file after
measuring a 42% failure rate on the obvious regex, including one silent
wrong-answer case. That means P2 cannot be correct on all rows until the
table exists and is complete. `domain` (needed for retrieval, P7) can stay
partially populated for now — only `name` blocks this phase. If you reach §4
and the table isn't there yet, building it (regex draft + full hand review of
all 50, `01` §12) is in scope for P2, not a separate task to defer.

## Scope

This phase produces:
1. `list[RawRow]` for `dev`, `list[RawRow]` for `qa` — one per data row.
2. `list[CharacteristicRule]`, built from `char_value_list` — the
   applicability + vocabulary table. Source `characteristic` names are
   spaced, uppercase form; normalized on load (§7).
3. `list[CharacteristicGuideline]`, built from `char_guidelines`, using the
   same normalization as (2) — both source sheets use the spaced form, only
   `dev`/`qa` are underscored (§7 corrects an earlier, wrong version of this
   claim).
4. `qa_header: list[str]` — captured and validated, for the assembler (P14) to
   consume later. **This loader does not write predictions or touch the qa
   sheet's data rows** — `01` §10 criterion 7 is about capturing and asserting
   the header contract here, not producing output here. That's stage 8's job.

Both (2) and (3) are flat lists, not dicts keyed by `(module, characteristic)`
— `03` §3's contracts note explains why (JSON round-trip: tuple keys aren't
valid JSON object keys). Build whatever in-memory dict you want from these
lists *inside* the loader module for your own convenience (e.g. to implement
`applicable_characteristics(module)` — a plain function, not a contract type,
returning `list[str]` by filtering `list[CharacteristicRule]` for the given
module) — just don't make a dict the thing that crosses the module boundary.

Explicitly out of scope for this phase: `desc_clean`, `DescTokens` (P3,
normalizer — `RawRow` intentionally excludes these, see `03` §3's
`RawRow`/`ProductQuery` split), anything touching `sample_output` beyond an
optional, non-blocking parse for later test fixtures.

## 1. Sheet reading

Read all sheets from the one workbook. `dataset_understanding_guide` and `S`
need no structured parsing — `S` is empty, skip it; the guide is prose, not
data, load it only if you want it queryable for debug output, never required.

**Read `EXTERNAL_CODE` via `openpyxl` directly, not through `pandas`.** This
column is the one place raw cell type matters (`01` §3) — pandas' per-column
dtype inference already happened by the time you'd see it, and for `dev`
that inference is int64, which is fine (it doesn't lose anything beyond what
Excel's `0.00E+00` cell format already destroyed at authoring time), but for
`qa` and `sample_output`, cells are stored as text and sometimes carry a
literal leading apostrophe character embedded in the value itself (confirmed
by direct inspection — not a display-only Excel quote-prefix, an actual
character in the string). Reading through `openpyxl` and branching on
`cell.data_type` (`'n'` numeric vs `'s'`/`'str'` string) is the only way to
handle both cases correctly in one code path. Read every other column through
`pandas.read_excel` as usual — this exception is `EXTERNAL_CODE` only.

## 2. `EXTERNAL_CODE` → `barcode`, `barcode_raw`, `barcode_corrupt`

```
if cell is numeric:
    raw_str = str(int(cell_value))          # e.g. 5000000000000
elif cell is string:
    raw_str = cell_value.lstrip("'").strip() # strip leading apostrophe if present
else:
    raw_str = None                           # empty cell

if raw_str is None:
    barcode, barcode_raw, barcode_corrupt = None, None, False
elif re.fullmatch(r"\d{1,3}0{6,}", raw_str):   # `01` §3's corruption signature
    barcode, barcode_raw, barcode_corrupt = None, raw_str, True
else:
    barcode, barcode_raw, barcode_corrupt = raw_str, raw_str, False
```

**`barcode` is `None` whenever `barcode_corrupt` is `True` — this is a
safety rule, not a formatting choice.** See `02-decision-log.md`,
"Barcode nulling-on-corrupt is a registry safety rule": a rounded value kept
as if it were real would let two unrelated products that happen to round to
the same truncated digits collide in Tier-0 registry lookup or the stage-4
GTIN hard-rule (`03` §1a, §4) — a false-positive merge, which is precisely
the registry-poisoning failure mode `05` §4/§5 exists to prevent. Do not
"fix" this by keeping the rounded value with just a flag set; the flag alone
doesn't stop downstream code from using it unless nothing downstream ever
receives it in the `barcode` field.

The regex is a heuristic for *this specific defect signature*, not a general
"looks suspicious" filter — don't extend it to reject barcodes that
legitimately end in zeros for other reasons (some real EAN/UPC check-digit
patterns do). Log every row where it fires, at `WARNING`, with `nan_key` and
`barcode_raw` — this is the audit trail `05` §4 expects for anything that
alters an identity signal.

Validity, separately: `barcode_valid = barcode is not None and len(barcode) in (8, 12, 13, 14)`.

## 2a. Encoding-corruption repair — `BRAND` and `RETAILER_DESC` (`01` §10 #9, §13)

Applies **before** §3's brand-parenthetical split and before §6's
whitespace collapse — repair the raw cell value first, then run the
field-specific logic on the repaired string. This was missing from an
earlier version of this spec entirely (no contract field, no section) —
`02-decision-log.md` has the record.

Use `ftfy.fix_text()`, not a hand-rolled Latin-1/UTF-8 roundtrip. Verified
against the actual corrupted value in `dev.BRAND`:

```python
>>> import ftfy
>>> ftfy.fix_text("JASÃƒâ€“N")
'JASÖN'
```

This is a genuinely double mis-encoded string (UTF-8 bytes mis-decoded as
Latin-1, then re-encoded as UTF-8, twice) — `ftfy` handles it correctly in
one call where a single-pass hand-rolled fix would not. Verified separately
that `ftfy.fix_text()` is a no-op on legitimate multilingual text already in
the data — `"pärla"`, `"antibactérien"`, `"colgate®"` all pass through
unchanged. This is why blanket application is safe: don't branch on
"does this look corrupted" before calling it, just call it and compare.

```python
def repair_encoding(raw: str) -> tuple[str, bool]:
    fixed = ftfy.fix_text(raw)
    return fixed, fixed != raw
```

`brand_raw, brand_encoding_suspect = repair_encoding(cell_value)` — then §3
runs its parenthetical split against the *repaired* `brand_raw`, not the
original cell value. Same pattern for `desc_raw` in §6. `brand_encoding_suspect`
being `True` is not an error — it's the audit signal (`01` §10 #9 says "flag,
don't silently repair" — this satisfies both halves: the repair happens, and
it's never silent, because the flag is always set when a change occurred).
Log at `INFO` (not `WARNING` — this is routine, expected on ~1–2% of rows,
not an anomaly the way barcode corruption is) with `nan_key`, the original
value, and the repaired value, whenever either flag is `True`.

## 3. `BRAND` → `brand`, `brand_owner`

Pattern: `NAME (OWNER)` — but the no-parens case is **common, not an edge
case**: 71 of 171 distinct brands (42%) have no owner suffix, e.g.
`"GENGIGEL"`. Write test coverage proportional to that — this branch needs
several real examples, not one token "does it handle the edge case" test.

```
match = re.fullmatch(r"(?P<brand>.+?)\s*\((?P<owner>[^)]+)\)\s*", brand_raw)
if match:
    brand, brand_owner = match["brand"].strip(), match["owner"].strip()
else:
    brand, brand_owner = brand_raw.strip(), None
```

## 4. `RETAILER` → `retailer` — hand-reviewed table, not a regex

**Do not implement this as a regex.** An `(?:[A-Z0-9]{4,6}\s+)?\([A-Z]{2,3}\)\s*(?P<name>.+)`-style
pattern — the obvious first attempt — was tried and measured against all 50
distinct `RETAILER` values (`01` §9 — 50 across `dev`+`qa` combined, not 44).
It fails on 21 of 50 (42%). Most failures are loud (no match, falls back to
`retailer_raw` unmodified — `"AMAZON (GB)"` keeps its country suffix instead
of being stripped, because `AMAZON` itself satisfies the optional
`[A-Z0-9]{4,6}` "code" group, leaving nothing for the name capture and
failing the whole match). **One failure is silent and dangerous:**
`"BOOTS (GB) (HOMESCAN)"` *does* match — `BOOTS` satisfies the code group,
`(GB)` satisfies the country group, and the name group captures whatever's
left, `"(HOMESCAN)"` — silently discarding the actual retailer name for the
single largest retailer in the dataset (49 rows), with no exception raised
anywhere. Full analysis: `01` §12.

Given only 50 distinct values total, the correct design is a lookup table,
not a cleverer pattern. This is `config/retailers.yaml`, and it does double
duty — the same file already holds the retailer→domain map for retrieval
(`03` §4 stage 2, S4); add a `name` field alongside `domain` per entry rather
than maintaining two parallel 50-entry tables that can drift out of sync:

```yaml
"P00R4 (GB) BOOTS":
  name: BOOTS
  domain: boots.com
"BOOTS (GB) (HOMESCAN)":
  name: BOOTS
  domain: boots.com
"AMAZON (GB)":
  name: AMAZON
  domain: amazon.co.uk
```

Build the `name` column with a regex-generated first pass (fine as a draft
generator), then **every one of the 50 entries gets human review before P2 is
considered done** — not a sample, all 50. That's the actual cost of the
42%-failure finding; a spot-check would have missed the `BOOTS`/`HOMESCAN`
case in the first place. `retailer` is looked up from this table by
`retailer_raw`; if a `retailer_raw` value isn't in the table, that's a
loader-time error (`04` §4, fail loud), not a fallback to the raw string —
an unmapped retailer silently passing through is exactly the failure mode
that just cost 49 rows' worth of correct retailer names once already.

`retailer_raw` itself stays untouched, still the canonical key for both the
`name` and `domain` lookups.

## 4a. `row_uid` — the row identity (`01` §14)

`row_uid = f"{sheet}:{position}"`, with `position` the 0-based index of the
data row within its sheet (`"dev:0"` … `"dev:411"`, `"qa:0"` … `"qa:411"`).

**This exists because `NAN_KEY` is not unique and cannot be used as a key.**
`01` §14: 65 of 412 `dev` `NAN_KEY`s and 67 of 412 `qa` ones carry the same
`0.00E+00` rounding corruption as `EXTERNAL_CODE`. Every duplicated
`NAN_KEY` is one of those rounded values, and 11 `dev` `NAN_KEY`s span more
than one `MODULE` — i.e. genuinely different products sharing a key
(`147000000` is simultaneously a breath freshener, a Listerine mouthwash and
an Oral-B toothbrush).

`03` §2 keys every stage's on-disk artifact by row identity and `03` §5
resumes the batch runner by it. Under a colliding key, one product's cached
artifact is served for a different product and a completed row marks an
unrelated row done — with no exception anywhere. `row_uid` is positional, so
it is unique and deterministic by construction.

`nan_key` and `item_code` are still carried verbatim on `RawRow`, for
traceability and because the submission needs them — they are just never
used as keys.

## 5. `COUNTRY` → `countries`

`countries = [c.strip() for c in country_raw.split(",")]`. No further
validation needed — every observed value is a valid ISO-2-ish code already.

## 6. `RETAILER_DESC` → `desc_raw`

**Encoding repair first** (§2a), **then whitespace collapse** (`01` §10
criterion 6) — `re.sub(r"\s+", " ", repaired).strip()`. Order matters: a
corrupted byte sequence can itself contain whitespace-like artifacts, so
repair before collapsing, not after. Nothing else happens to this field. The
junk classes named in `03` §4 stage `[0]` (retailer codes, `unit \d+`
fragments, duplicated size suffixes) are P3's job, not this one. Resist the
temptation to do more here just because you're already touching the string —
that's scope drift into the normalizer.

Verified against the real file: the whitespace collapse itself is a no-op on
both `dev` and `qa` — 0 rows have double spaces or leading/trailing
whitespace, all rows are lowercase (`01` §2). Keep the step anyway, it's a
cheap defensive no-op; don't build test cases assuming `RETAILER_DESC` itself
is messy in that particular way — the padded, mixed-case example elsewhere in
this project is from `sample_output`, not real `dev`/`qa` data. The encoding
corruption (§2a) is real on a small number of rows, though — that's a
different kind of messy than whitespace, and it does need handling.

## 7. `char_value_list` and `char_guidelines` → shared characteristic-name normalization

**Both sheets use spaced, uppercase characteristic names** —
`char_value_list.characteristic` is `"GLOBAL BRISTLE STRENGTH CLAIM"`, not
already underscored as an earlier version of this spec claimed. Only
`dev`/`qa` columns are underscored. Both rule sheets need the same
normalization, applied by one shared function, not two separate ad-hoc ones.

**The mapping is not a pure mechanical transform.** 12 of 13 names normalize
by a straightforward space/slash→underscore rule:

    GLOBAL FLAVOUR/FRAGRANCE/INGREDIENT GROUP  ->  GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP

One does not — `"IF WITH "` is dropped, not transformed:

    GLOBAL IF WITH INTERSPACE CLAIM            ->  GLOBAL_INTERSPACE_CLAIM

A pure mechanical normalizer produces `GLOBAL_IF_WITH_INTERSPACE_CLAIM` for
this one, which isn't a real `dev`/`qa` column — **the "assert total and
bijective" check will raise and halt on the real file** if you rely on
mechanical transformation alone. The fix: a small hand-coded alias dict,
checked first, with the mechanical rule as fallback for everything else:

```python
CHARACTERISTIC_NAME_ALIASES = {
    "GLOBAL IF WITH INTERSPACE CLAIM": "GLOBAL_INTERSPACE_CLAIM",
}

def normalize_characteristic_name(spaced: str) -> str:
    if spaced in CHARACTERISTIC_NAME_ALIASES:
        return CHARACTERISTIC_NAME_ALIASES[spaced]
    return spaced.strip().upper().replace("/", "_").replace(" ", "_")
```

Apply this to **both** `char_value_list.characteristic` and
`char_guidelines.CHARACTERISTICS NAME` on load. Assert the result is total
and bijective against the 13 `dev`/`qa` characteristic columns **after** the
alias is applied — that check is still required, it just isn't the only
mechanism.

## 8. `char_value_list` → `list[CharacteristicRule]`

- Assert `category` is `"ORAL HEALTH"` for every row — single-category scope
  is a standing assumption across `03`/`04`/`05`; a second value appearing
  means the file changed underneath the whole design, not something to
  silently tolerate.
- Parse `possible_values` with `ast.literal_eval`, never `eval`, never string
  splitting — it's a Python list literal stored as text
  (`"['HARD', 'MEDIUM', 'NO CLAIM', 'SOFT']"`).
- `binary`: `"Y"` → `True`, `"N"` → `False`.
- `characteristic` normalized via §7's function before constructing the model.
- One `CharacteristicRule` per sheet row: `module`, `characteristic`
  (normalized, underscored), `open_close`, `binary`, `allowed_values`. Output
  is `list[CharacteristicRule]` — see `03` §3's note on why this is a list,
  not a dict keyed by `(module, characteristic)`.
- `applicable_characteristics(module: str) -> list[str]` is a plain function
  in this module, not a contract type: filter the list for matching `module`,
  return the `characteristic` values.

**Note for later phases, not this one:** `01` §11 documents that `dev`'s
ground-truth *values* for closed characteristics can be `&`-joined
combinations of multiple `possible_values` entries (common for
`GLOBAL_ORAL_CARE_FUNCTION`/`GLOBAL_CONSUMER_LIFESTAGE_CLAIM`, not rare).
This loader just needs to expose `allowed_values` correctly — the
per-component validation logic that uses it belongs to characteristic
extraction (P12, `03` §4 stage 6 step 3), not here.

## 9. `char_guidelines` → `list[CharacteristicGuideline]`

Same normalization function as §7/§8, applied to `CHARACTERISTICS NAME`.
Output is `list[CharacteristicGuideline]`: `module`, `characteristic`
(normalized), `guideline_text`.

Also assert `MODULE NAME` values in `char_guidelines` are a subset of the
module set from `char_value_list` — this is a cross-sheet consistency check
the organizers' own files should satisfy; if they don't, that's worth
surfacing (a candidate organizer question), not silently absorbing.

## 10. `qa` header capture

Read the `qa` sheet's header row as a plain `list[str]`, in order. Assert it
equals the 23-column set documented in `01` §2 exactly — name and order both.
Expose it as `qa_header`. This is what the assembler (`03` §4 stage 8) will
serialize `OutputRow` against later; this phase's job is to capture and
validate it exists as expected, not to produce any output rows.

## 11. Corruption-count self-check (`01` §10 criterion 2 — the P2 gate)

```
corrupt_count = sum(row.barcode_corrupt for row in dev_rows)
if corrupt_count != 377:
    raise DatasetDriftError(
        f"dev barcode corruption count is {corrupt_count}, expected 377 "
        f"(01-dataset-contract.md §3). The source file changed — re-verify "
        f"01-dataset-contract.md before proceeding, don't just update this number."
    )
```

This is the literal P2 gate in `04` §1 ("Corruption counts match `01` §3
exactly"). It is also the loader's instance of the schema-drift latent-failure
guardrail in `05` §5 — the pattern (assert a known fingerprint, fail loudly on
drift) generalizes to column set and dtypes too; implement those assertions
here as well, not just the corruption count.

## Error handling

Every violation above is a raised, named exception
(`DatasetDriftError`, `DatasetSchemaError`, or similar — pick a small
taxonomy, don't reuse a bare `ValueError` for everything) — never a logged
warning that lets loading continue on a wrong assumption. Per `04` §4: no
bare `except`, no default that masks a parse failure, no partial `RawRow`.

## Determinism

Row order matches source sheet order exactly — no re-sorting, no groupby
reordering. Same file in, byte-identical `RawRow` sequence out, every run.

## Tests

- **Regression, exact:** dev corruption count is 377/412; 98 distinct
  surviving barcode values. These numbers came from direct inspection of the
  real file (`01` §3) — assert them against the real committed
  `data/raw/` file, not a synthetic fixture; a synthetic fixture can't tell
  you whether the real defect is still being caught correctly.
- **Leading-apostrophe stripping:** a `sample_output`-style value
  (`"'8714789613970"`) parses to `barcode = "8714789613970"`.
- **Encoding repair, the real sentinel case:** `repair_encoding("JASÃƒâ€“N")`
  → `("JASÖN", True)` — this is the actual corrupted `dev.BRAND` value
  (§2a), not a constructed example; it must resolve correctly, not just
  "some repair happens." Also test that legitimate multilingual text is
  unchanged: `repair_encoding("pärla")` → `("pärla", False)`.
- **Brand parsing, several examples of each branch, not one:** the no-owner
  branch is 42% of distinct brands (§3) — test at least 4–5 real examples
  from each branch, not just `"AQUAFRESH (HALEON)"` →
  `("AQUAFRESH", "HALEON")` and `"GENGIGEL"` → `("GENGIGEL", None)`.
- **Retailer lookup, including the sentinel case:** `config/retailers.yaml`'s
  `name` field, once populated, is what's under test here, not a regex — the
  correctness test is that the table's `name` values match what a human
  reviewer confirmed for all 50 entries. One entry is mandatory as an
  explicit regression test, named for what it protects:
  `"BOOTS (GB) (HOMESCAN)"` → `"BOOTS"` — this is the case a naive regex gets
  silently, dangerously wrong (`01` §12); it must never regress back to
  `"(HOMESCAN)"` or similar. A `retailer_raw` value absent from the table
  raises at load time (§4) — test that too, with a fixture value not in the
  table.
- **`possible_values` parsing:** a handful of real `char_value_list` rows,
  including one with a single-quote-containing value if any exist, parse to
  the correct `list[str]` via `ast.literal_eval`.
- **Characteristic-name alias, both directions:** `"GLOBAL IF WITH
  INTERSPACE CLAIM"` (the one irregular case, §7) normalizes to
  `"GLOBAL_INTERSPACE_CLAIM"` — assert this explicitly, don't rely on it
  passing incidentally as part of the full-file bijective check. Also test
  that the mechanical fallback correctly handles the slash case:
  `"GLOBAL FLAVOUR/FRAGRANCE/INGREDIENT GROUP"` →
  `"GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP"`.
- **Bijective name mapping, on the real file:** with the alias applied, the
  normalized name sets from `char_value_list` and `char_guidelines` both
  equal the 13 `dev`/`qa` characteristic columns exactly. Additionally,
  deliberately rename one characteristic in a fixture copy of
  `char_guidelines` and assert the loader raises — proves the assertion
  actually fires, not just that it happens not to trigger on clean input.
- **`allowed_values` exposure for `&`-combinator characteristics:** confirm
  `CharacteristicRule.allowed_values` for `GLOBAL_ORAL_CARE_FUNCTION` and
  `GLOBAL_CONSUMER_LIFESTAGE_CLAIM` contains the individual atomic values
  (no `&`-joined entries) — this loader doesn't validate `&`-combinations
  (that's P12), but it must expose the vocabulary those atomic values are
  drawn from correctly.
- **`qa_header` exactness:** matches the documented 23 columns; a fixture with
  a reordered or extra column raises.
- **Drift detection:** a fixture `dev` copy with the corruption count changed
  (e.g. one corrupt row fixed) raises `DatasetDriftError` — proves criterion 2
  actually fires, not just that the number is hardcoded somewhere unused.
- **No network** — trivially true here, assert it anyway per the standing
  pattern (`04` §8).
- **`row_uid` uniqueness (§4a):** unique across all 412 rows of each sheet,
  no collision between sheets, and — as the counterpart assertion —
  `NAN_KEY` is confirmed *not* unique, so the test fails loudly if the
  organizers ever fix the source and the whole `01` §14 analysis needs
  revisiting.

Use small inline-string fixtures for the parsing-rule tests — fast, targeted,
and each one names exactly which real input string it's protecting. Use the
real committed file for the whole-dataset checks (corruption count,
`qa_header`, bijective mapping) where the real file's actual shape is the
thing under test, and for confirming `config/retailers.yaml` covers every
distinct `retailer_raw` value that actually appears in `dev`+`qa`.
