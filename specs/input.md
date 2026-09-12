# specs/input.md — a product list of your own (P18)

Authored 2026-09-12, under the shared-authority rule
(`02-decision-log.md` 2026-09-10). Authority: `01` §2 (the input columns),
`01` §3/§14 (what must not be re-created on the way in), `specs/loader.md`
(the parsers), `specs/ui.md` (the ad-hoc form, whose rules this generalizes).

## 0. What it is for

The dataset loader is pinned to the organizers' workbook by design: it
asserts the file's fingerprint so that a changed file is caught, not silently
processed (`05` §5). That leaves no door for the question a judge — or the
project head — will ask: *give it our own product list.* This is that door.

## 1. Input

`uv run python -m nimo.run --input FILE --live [--characteristics] [--out-dir D]`
then `uv run python -m nimo.assemble --input FILE --out-dir D` and
`uv run python -m nimo.site --input FILE --out-dir D`.

`FILE` is `.xlsx` (first sheet) or `.csv` (UTF-8, BOM tolerated) with a
header row. **Required columns:** `RETAILER_DESC`, `BRAND`. **Optional:**
`EXTERNAL_CODE` (barcode), `RETAILER`, `COUNTRY`, `ITEM_CODE`, `NAN_KEY`.
Other columns are ignored. Every cell is read as text (`dtype=str`) so the
numeric coercion `01` §3 documents cannot recur on the way in; the one
repair applied is a float-rendered whole number (`5014697056627.0` →
`5014697056627`), and a leading apostrophe on a barcode is stripped as the
dataset reader strips it.

## 2. Rows

Each record becomes a `RawRow` through the loader's own parsers
(`specs/loader.md` §2–§6: `ftfy` repair with the suspect flags, the brand
split, barcode nulling on the rounded shape, whitespace collapse, country
split), keyed `<name>:<index>` where `name` is the file's stem lower-cased
with non-alphanumerics folded to `_` (`My Products (1).xlsx` →
`my_products_1`), and prefixed `input_` if it would collide with `dev`,
`qa`, `adhoc` or `sample_output`. Artifacts land under `artifacts/<name>/`,
cache entries are keyed by content as always, and the registry is shared:
a product the dataset resolved answers a stranger's file from memory.

Where a file lacks a column, the row says so rather than guessing:

| absent | row carries | why |
|---|---|---|
| `EXTERNAL_CODE` | `barcode=None` | no identifier; the GTIN rule and S1/S2 simply do not fire |
| `RETAILER` | `retailer_raw="UNKNOWN"` | S4 (site-restricted) is skipped; nothing else reads it |
| `COUNTRY` | `["GB"]` | the dataset's market (`01` §9), stated in config-level constant `DEFAULT_COUNTRY` |
| `ITEM_CODE` / `NAN_KEY` | `0` | traceability-only columns (`01` §14); 0 is visibly not a code |

A `RETAILER` the hand-reviewed table does not know is **kept as typed**, not
refused — `RetailerNotMappedError` exists to catch the dataset's 50 strings
drifting, and a stranger's retailer is not drift. It is logged.

## 3. Output

`assemble_input_rows` produces the same 23-column `OutputRow`s as a sheet,
validated the same way (module in the 59, characteristics applicable and
in vocabulary), with the passthrough columns taken from the file's own
strings untrimmed — a column the file lacked is empty. `submission_<name>.csv`
and `.xlsx` (sheet named `<name>`), the assembly report, and the explorer
`site_<name>.html`.

## 4. What it needs

Rows the caches have not seen need a running SearxNG (`docker compose up
-d searxng`) and ordinary internet for the retailer pages; characteristics
need the model, i.e. the NIQ network. Rows already resolved into the
registry need neither. Without `--live`, the run is the offline baseline:
normalize, registry, classify, gate-only characteristics, reasoning.

## 5. Tests

`tests/loader/test_input.py`: an xlsx and a csv written in a temp dir go
through the parsers — an int cell becomes text, an apostrophe is stripped, a
rounded value is a hole, an unknown retailer is kept, an absent country is
GB, absent keys are 0, whitespace is collapsed on the row and kept on the
passthrough; required columns, empty files, wrong extensions and blank
descriptions are refused; the name is derived from the file and never a
reserved sheet. `tests/assemble/`: the offline runner over input rows
assembles to the contract's shape with the file's own passthrough.

## 6. Definition of Done

- [x] Offline end to end through the three CLIs on a three-row xlsx of
      products not in the dataset (2026-09-12).
- [ ] Live end to end (SearxNG up): the same file through retrieval, fetch
      and match — recorded in the decision log when run.
- [x] `04` §11 gate green.
