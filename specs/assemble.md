# Spec — P14 assembly (`src/nimo/assemble/`)

Authority: `03` §4 stage 8, `03` §3 `OutputRow`, `01` §10 #7 ("qa's exact
header, exact column order, no extra columns, no reordered rows"), `01` §3
(`EXTERNAL_CODE` as text), `04` §4 (never a partial row), `04` §5 (twice-run
byte-identical is a CI test), `05` §5 (type coercion across the output write).

## 1. Inputs

The runner's eight artifact trees for a sheet (`data/out/artifacts/<sheet>/`)
and the workbook. No network, no model.

## 2. Row assembly

For every row of the sheet, in sheet order:

- **Input columns are passthrough from the workbook, verbatim** — read with
  `dtype=str`, not from `RawRow`: `RawRow.brand_raw` and `desc_raw` are
  encoding-repaired and whitespace-collapsed (`01` §13, `01` §10 #6), and a
  submission must carry the organizers' bytes, not ours. `EXTERNAL_CODE` is
  the text the loader read (leading apostrophe stripped, `01` §3), never a
  number. A cheap alignment check: the artifact's `nan_key`/`item_code`
  must equal the sheet row's, or assembly raises.
- **Output columns come from the artifacts** when the row is complete
  (`is_row_complete`): `PRODUCT_URL` from `Selection` (§3), `REASONING` from
  `Reasoning.text`, `MODULE` from `ModulePrediction.module`, the 13
  characteristics from `CharacteristicValues.values`.
- **A failed or missing row gets every output column empty.** `04` §4:
  "a row either has a complete validated result or is recorded as failed.
  Half-filled rows in the submission are worse than blanks." The report
  lists them.

## 3. `PRODUCT_URL` — `[PROVISIONAL — Q2]`

`config/output.yaml`'s `product_url_field` is `url` (default) or `title`.
`01` §5: `sample_output` holds page titles; until Q2 resolves the real URL
is emitted and the title is available in the same run's `match/` artifacts
and the trace. The switch changes a config value, not a module. `None`
serializes to an empty cell either way.

## 4. Validation on assembly — belt and braces

Every `OutputRow` is validated before writing, and a violation **raises**
rather than being fixed up (`04` §4): the artifacts should never violate,
so a violation is drift, and drift must not become a submission.

- `MODULE`, when set, is in `char_value_list`'s module set.
- Every non-`None` characteristic is applicable to `MODULE` (`01` §7), and
  a closed one validates per `&` component (`01` §11) — the same validator
  P12 used.
- `EXTERNAL_CODE` is a string of digits, never numeric; `NAN_KEY` and
  `ITEM_CODE` are ints (the workbook's own type).
- Column order equals the live `qa` header, asserted at load (`03` §3's
  assembly note).

## 5. Files and byte-identity

- `<out-dir>/submission_<sheet>.csv` — UTF-8, `\n`, exact header, one row
  per sheet row. The canonical artifact for `04` §5's byte-identity test.
- `<out-dir>/submission_<sheet>.xlsx` — one sheet named after the source
  sheet, exact header, `EXTERNAL_CODE`/`NAN_KEY`/`ITEM_CODE` written with a
  text number format so Excel cannot reintroduce the `0.00E+00` defect
  (`05` §5; the defect this project started with). Workbook properties
  (`created`/`modified`) are pinned to a fixed instant so the file is
  byte-identical on re-run; **verified by writing twice and comparing
  bytes, not assumed** — openpyxl stamps the current time by default.
- `<out-dir>/assembly_<sheet>.txt` — the report: rows, complete rows, blank
  rows (with their `row_uid`s and failure stages from `failures.jsonl` when
  present), tier distribution, per-column fill counts, and the
  `product_url_field` in force.

## 6. Tests

- header equality against the workbook; a reordered/renamed header raises;
- a complete row carries the artifact values; a failed row is all-blank in
  the output columns and passthrough in the input ones;
- passthrough is the workbook's bytes (an encoding-corrupt `BRAND` survives
  unrepaired in the output);
- `EXTERNAL_CODE` is text in the xlsx read back through openpyxl
  (`data_type == "s"`), `NAN_KEY` is an int;
- a `MODULE` outside the set, or a non-applicable characteristic value,
  raises;
- `product_url_field: title` emits the title;
- twice-run: both files byte-identical.

## 7. CLI

`uv run python -m nimo.assemble --sheet qa [--out-dir D] [--artifacts D]`
prints the report and writes the three files. `print` is the CLI's output
(`04` §10).
