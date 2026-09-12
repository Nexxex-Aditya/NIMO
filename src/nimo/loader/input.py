"""Bring-your-own product list — `specs/input.md`.

The dataset loader (`dataset.py`) is pinned to the organizers' workbook on
purpose: it asserts the file's fingerprint so a changed file is caught, not
silently processed (`05` §5). This module is the other door: any `.xlsx` or
`.csv` with the dataset's input columns — only `RETAILER_DESC` and `BRAND`
are required — becomes a list of `RawRow`s through the *same* parsers the
dataset and the UI's ad-hoc form use (`fields.py`), keyed under a name
derived from the file so it can never collide with `dev`, `qa` or `adhoc`.

What is deliberately NOT done here: no fingerprint (there is nothing to pin
a stranger's file to), no `RetailerNotMappedError` (an unknown retailer is a
real possibility and costs only the site-restricted query — the ad-hoc form
already treats it that way), and no repair of a numeric barcode column
beyond the float-rendered-integer case: a value pandas hands back as
`5014697056627.0` is the integer `5014697056627`; anything else that is not
a digit string is recorded as no barcode, never guessed.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import structlog

from nimo.contracts import RawRow
from nimo.loader.dataset import retailer_name
from nimo.loader.errors import DatasetSchemaError
from nimo.loader.fields import (
    collapse_whitespace,
    parse_barcode,
    parse_brand,
    parse_countries,
    repair_encoding,
)

log = structlog.get_logger(__name__)

REQUIRED_COLUMNS = ("RETAILER_DESC", "BRAND")
OPTIONAL_COLUMNS = ("EXTERNAL_CODE", "RETAILER", "COUNTRY", "ITEM_CODE", "NAN_KEY")
# `01` §9: GB is the retrieval market for this dataset; a file without a
# COUNTRY column is assumed to be the same market. Stated, not hidden.
DEFAULT_COUNTRY = "GB"
RESERVED_NAMES = frozenset({"dev", "qa", "adhoc", "sample_output"})
_NAME_CHARS = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class InputTable:
    """A product list as read: string cells, in file order, plus the name
    its rows are keyed under (`<name>:<index>`)."""

    name: str
    source: Path
    columns: tuple[str, ...]
    records: tuple[dict[str, str | None], ...]


def input_name(path: Path) -> str:
    """`My Products (1).xlsx` -> `my_products_1`; a reserved name is prefixed
    so a file called `qa.csv` cannot masquerade as the evaluation sheet."""
    name = _NAME_CHARS.sub("_", path.stem.lower()).strip("_") or "input"
    return f"input_{name}" if name in RESERVED_NAMES else name


def _clean(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value)
    stripped = text.strip()
    if stripped in ("", "nan", "None"):
        return None
    # A whole number that Excel/pandas rendered as a float.
    if stripped.endswith(".0") and stripped[:-2].isdigit():
        return stripped[:-2]
    # Otherwise the cell's own text, untrimmed: the assembler passes it
    # through as the file holds it (`specs/assemble.md`); the parsers below
    # trim what they need.
    return text


def load_input(path: Path, sheet_name: str | None = None) -> InputTable:
    """Read an `.xlsx` (first sheet, or `sheet_name`) or a `.csv`, every cell
    as text — the numeric-coercion defect `01` §3 documents must not be
    re-created on the way in."""
    if not path.exists():
        raise DatasetSchemaError(f"{path}: not found")
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        frame = pd.read_excel(path, sheet_name=sheet_name or 0, dtype=str)
    elif suffix == ".csv":
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    else:
        raise DatasetSchemaError(f"{path}: expected .xlsx or .csv, got {suffix or '(none)'}")
    columns = tuple(str(c).strip() for c in frame.columns)
    frame.columns = list(columns)
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise DatasetSchemaError(
            f"{path}: required column(s) missing: {missing}. A product list needs at least "
            f"RETAILER_DESC and BRAND; {list(OPTIONAL_COLUMNS)} are optional."
        )
    if len(frame) == 0:
        raise DatasetSchemaError(f"{path}: no data rows")
    records = tuple(
        {column: _clean(record.get(column)) for column in columns}
        for record in frame.to_dict("records")
    )
    return InputTable(name=input_name(path), source=path, columns=columns, records=records)


def external_code(record: dict[str, str | None]) -> str | None:
    """`EXTERNAL_CODE` as the dataset reader would hand it over: the literal
    leading apostrophe some text cells carry stripped (`01` §3), trimmed,
    `None` when empty."""
    raw = record.get("EXTERNAL_CODE")
    if raw is None:
        return None
    text = raw.lstrip("'").strip()
    return text or None


def int_key(value: str | None) -> int:
    """`ITEM_CODE`/`NAN_KEY` are traceability-only (`01` §14); a file without
    them carries 0, which is visibly not a code."""
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def input_rows(table: InputTable, retailers_path: Path) -> list[RawRow]:
    """One `RawRow` per record, in file order, through the loader's parsers."""
    rows: list[RawRow] = []
    for position, record in enumerate(table.records):
        desc_cell = record.get("RETAILER_DESC")
        if not desc_cell:
            raise DatasetSchemaError(f"{table.source} row {position + 2}: RETAILER_DESC is empty")
        brand_cell = (record.get("BRAND") or "UNKNOWN").strip() or "UNKNOWN"
        barcode, barcode_raw, corrupt = parse_barcode(external_code(record))
        if corrupt:
            log.warning("barcode_corrupt_rounded", sheet=table.name, barcode_raw=barcode_raw)
        brand_fixed, brand_suspect = repair_encoding(brand_cell)
        brand, owner = parse_brand(brand_fixed)
        desc_fixed, desc_suspect = repair_encoding(desc_cell)
        retailer_raw = (record.get("RETAILER") or "UNKNOWN").strip() or "UNKNOWN"
        known = retailer_name(retailer_raw, retailers_path)
        if known is None:
            log.info("retailer_not_in_table", sheet=table.name, retailer=retailer_raw)
        retailer = known if known is not None else retailer_raw
        country_cell = (record.get("COUNTRY") or DEFAULT_COUNTRY).strip() or DEFAULT_COUNTRY
        countries = parse_countries(country_cell) or [DEFAULT_COUNTRY]
        rows.append(
            RawRow(
                row_uid=f"{table.name}:{position}",
                nan_key=int_key(record.get("NAN_KEY")),
                item_code=int_key(record.get("ITEM_CODE")),
                barcode=barcode,
                barcode_raw=barcode_raw,
                barcode_corrupt=corrupt,
                brand_raw=brand_fixed,
                brand=brand,
                brand_owner=owner,
                brand_encoding_suspect=brand_suspect,
                retailer_raw=retailer_raw,
                retailer=retailer,
                countries=countries,
                desc_raw=collapse_whitespace(desc_fixed),
                desc_encoding_suspect=desc_suspect,
            )
        )
    return rows
