"""Assembly — `03` §4 stage 8, `specs/assemble.md`.

Reads the runner's artifact trees and the workbook, produces one validated
`OutputRow` per sheet row in sheet order, and writes the submission files.
Passthrough columns are the workbook's own bytes; a failed row is all-blank
in the output columns (`04` §4); every violation raises (`04` §4) — the
artifacts should never violate, so a violation is drift, and drift must not
become a submission.
"""

import csv
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

import openpyxl
import pandas as pd
import yaml
from openpyxl.styles.numbers import FORMAT_TEXT

from nimo.characteristics import CHARACTERISTIC_COLUMNS, applicable_rules, validate
from nimo.contracts import (
    CharacteristicRule,
    CharacteristicValues,
    ModulePrediction,
    OutputRow,
    Reasoning,
    RegistryLookupResult,
    RowFailure,
    Selection,
)
from nimo.loader import DatasetSchemaError, read_external_codes, read_header
from nimo.run.artifacts import artifact_path, is_row_complete

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "output.yaml"
INPUT_COLUMNS = (
    "ITEM_CODE",
    "NAN_KEY",
    "EXTERNAL_CODE",
    "COUNTRY",
    "RETAILER_DESC",
    "RETAILER",
    "BRAND",
)
# Written with a text number format so Excel cannot reintroduce the
# `0.00E+00` rounding defect this project started with (`01` §3, `05` §5).
TEXT_COLUMNS = ("ITEM_CODE", "NAN_KEY", "EXTERNAL_CODE")


class AssemblyError(Exception):
    """A row could not be assembled into a valid `OutputRow`, or the files
    could not be written faithfully."""


class OutputConfigError(Exception):
    """`config/output.yaml` is missing, malformed, or missing a key."""


@dataclass(frozen=True)
class OutputConfig:
    product_url_field: Literal["url", "title"]
    xlsx_sheet_name_from_source: bool
    fixed_timestamp: datetime


@lru_cache(maxsize=1)
def load_output_config(path: Path = CONFIG_PATH) -> OutputConfig:
    if not path.exists():
        raise OutputConfigError(f"{path} not found — `specs/assemble.md` requires it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise OutputConfigError(f"{path} did not parse to a mapping")
    field_name = data.get("product_url_field")
    if field_name not in ("url", "title"):
        raise OutputConfigError(f"{path}: `product_url_field` must be `url` or `title`.")
    from_source = data.get("xlsx_sheet_name_from_source")
    if not isinstance(from_source, bool):
        raise OutputConfigError(f"{path}: `xlsx_sheet_name_from_source` must be a boolean.")
    stamp = data.get("fixed_timestamp")
    if not isinstance(stamp, str):
        raise OutputConfigError(f"{path}: `fixed_timestamp` must be an ISO-8601 string.")
    try:
        fixed = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as error:
        raise OutputConfigError(f"{path}: `fixed_timestamp` is not ISO-8601: {error}") from error
    return OutputConfig(
        product_url_field="title" if field_name == "title" else "url",
        xlsx_sheet_name_from_source=from_source,
        fixed_timestamp=fixed,
    )


@dataclass
class AssemblyReport:
    sheet: str
    rows: int
    complete: int
    blank_row_uids: list[str] = field(default_factory=list)
    failure_stages: dict[str, str] = field(default_factory=dict)  # row_uid -> stage
    tier_counts: Counter[str] = field(default_factory=Counter)
    column_fill: Counter[str] = field(default_factory=Counter)
    product_url_field: str = "url"


def _passthrough(workbook_path: Path, sheet: str) -> pd.DataFrame:
    """The input columns as the workbook holds them — `dtype=str`, no repair,
    no collapse. `EXTERNAL_CODE` needs the loader's cell-type-aware read for
    the leading-apostrophe case (`01` §3), so it is re-read the same way."""
    frame = pd.read_excel(workbook_path, sheet_name=sheet, dtype=str)
    missing = [name for name in INPUT_COLUMNS if name not in frame.columns]
    if missing:
        raise DatasetSchemaError(f"{sheet}: input column(s) missing: {missing}")
    return frame


def _cell(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value)
    return None if text in ("", "nan") else text


def _int_cell(frame: pd.DataFrame, index: int, column: str, sheet: str) -> int:
    raw = _cell(frame.at[index, column])
    if raw is None:
        raise AssemblyError(f"{sheet}:{index}: {column} is empty in the workbook")
    try:
        return int(float(raw))
    except ValueError as error:
        raise AssemblyError(f"{sheet}:{index}: {column} {raw!r} is not an integer") from error


def assemble_rows(
    workbook_path: Path,
    sheet: str,
    artifacts_root: Path,
    rules: list[CharacteristicRule],
    config: OutputConfig,
    failures_path: Path | None = None,
) -> tuple[list[OutputRow], AssemblyReport]:
    """One `OutputRow` per sheet row, in sheet order, validated."""
    header = read_header(workbook_path, sheet)
    expected = list(OutputRow.model_fields)
    if header != expected:
        raise AssemblyError(
            f"{sheet} header differs from OutputRow's field order.\n  sheet: {header}\n"
            f"  contract: {expected}\nA reordered submission scores zero (`03` §3)."
        )
    frame = _passthrough(workbook_path, sheet)
    external_codes = read_external_codes(workbook_path, sheet, len(frame))
    known_modules = {rule.module for rule in rules}
    failure_stages = _failure_stages(failures_path)

    report = AssemblyReport(
        sheet=sheet, rows=len(frame), complete=0, product_url_field=config.product_url_field
    )
    rows: list[OutputRow] = []
    for index in range(len(frame)):
        row_uid = f"{sheet}:{index}"
        inputs = {
            "ITEM_CODE": _int_cell(frame, index, "ITEM_CODE", sheet),
            "NAN_KEY": _int_cell(frame, index, "NAN_KEY", sheet),
            "EXTERNAL_CODE": external_codes[index] or "",
            "COUNTRY": _cell(frame.at[index, "COUNTRY"]) or "",
            "RETAILER_DESC": _cell(frame.at[index, "RETAILER_DESC"]) or "",
            "RETAILER": _cell(frame.at[index, "RETAILER"]) or "",
            "BRAND": _cell(frame.at[index, "BRAND"]) or "",
        }
        outputs: dict[str, str | None] = dict.fromkeys(
            ["PRODUCT_URL", "REASONING", "MODULE", *CHARACTERISTIC_COLUMNS]
        )
        if is_row_complete(artifacts_root, row_uid):
            outputs = _outputs_for(row_uid, artifacts_root, inputs, rules, known_modules, config)
            report.complete += 1
            registry = RegistryLookupResult.model_validate_json(
                artifact_path(artifacts_root, "registry", row_uid).read_text(encoding="utf-8")
            )
            selection = Selection.model_validate_json(
                artifact_path(artifacts_root, "match", row_uid).read_text(encoding="utf-8")
            )
            report.tier_counts[registry.tier if registry.hit else selection.resolution_tier] += 1
        else:
            report.blank_row_uids.append(row_uid)
            if row_uid in failure_stages:
                report.failure_stages[row_uid] = failure_stages[row_uid]
        for name, value in outputs.items():
            if value is not None:
                report.column_fill[name] += 1
        rows.append(OutputRow.model_validate({**inputs, **outputs}))
    return rows, report


def _failure_stages(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    stages: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            failure = RowFailure.model_validate_json(line)
            stages[failure.row_uid] = failure.stage  # last failure wins
    return stages


def _outputs_for(
    row_uid: str,
    root: Path,
    inputs: dict[str, object],
    rules: list[CharacteristicRule],
    known_modules: set[str],
    config: OutputConfig,
) -> dict[str, str | None]:
    selection = Selection.model_validate_json(
        artifact_path(root, "match", row_uid).read_text(encoding="utf-8")
    )
    prediction = ModulePrediction.model_validate_json(
        artifact_path(root, "classify", row_uid).read_text(encoding="utf-8")
    )
    values = CharacteristicValues.model_validate_json(
        artifact_path(root, "characteristics", row_uid).read_text(encoding="utf-8")
    )
    reasoning = Reasoning.model_validate_json(
        artifact_path(root, "reason", row_uid).read_text(encoding="utf-8")
    )
    for model in (prediction, values, reasoning):
        if model.row_uid != row_uid:
            raise AssemblyError(f"{row_uid}: artifact carries row_uid {model.row_uid!r} — misfiled")

    # `03` §4 stage 8 validation — belt and braces over what P5/P12 wrote.
    module = prediction.module
    if module not in known_modules:
        raise AssemblyError(f"{row_uid}: MODULE {module!r} is not in char_value_list's 59")
    applicable = {rule.characteristic: rule for rule in applicable_rules(rules, module)}
    outputs: dict[str, str | None] = {
        "PRODUCT_URL": selection.page_title
        if config.product_url_field == "title"
        else selection.url,
        "REASONING": reasoning.text or None,
        "MODULE": module,
    }
    for name in CHARACTERISTIC_COLUMNS:
        value = values.values.get(name)
        if value is None:
            outputs[name] = None
            continue
        rule = applicable.get(name)
        if rule is None:
            raise AssemblyError(
                f"{row_uid}: {name}={value!r} but it is not applicable to {module!r} (`01` §7)"
            )
        outcome = validate(rule, value)
        if outcome.rejected is not None:
            raise AssemblyError(f"{row_uid}: {name}={value!r} fails validation: {outcome.reason}")
        outputs[name] = outcome.value
    return outputs


# --- writers ---------------------------------------------------------------------


def to_csv_text(rows: list[OutputRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(OutputRow.model_fields))
    for row in rows:
        writer.writerow(
            ["" if value is None else str(value) for value in row.model_dump().values()]
        )
    return buffer.getvalue()


def write_csv(rows: list[OutputRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_csv_text(rows), encoding="utf-8", newline="")


def write_xlsx(rows: list[OutputRow], path: Path, sheet: str, config: OutputConfig) -> None:
    """Exact header, text-formatted identifier columns, pinned properties."""
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    if worksheet is None:
        raise AssemblyError("openpyxl returned no active worksheet")
    worksheet.title = sheet if config.xlsx_sheet_name_from_source else "Sheet1"
    columns = list(OutputRow.model_fields)
    worksheet.append(columns)
    text_indexes = [columns.index(name) + 1 for name in TEXT_COLUMNS]
    for row in rows:
        dumped = row.model_dump()
        worksheet.append(
            [
                (str(dumped[name]) if name in TEXT_COLUMNS else dumped[name])
                if dumped[name] is not None
                else None
                for name in columns
            ]
        )
        for column_index in text_indexes:
            worksheet.cell(row=worksheet.max_row, column=column_index).number_format = FORMAT_TEXT
    stamp = config.fixed_timestamp.replace(tzinfo=None)
    workbook.properties.created = stamp
    workbook.properties.modified = stamp
    workbook.properties.lastPrinted = None
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    _repack_deterministic(path, stamp)


def _repack_deterministic(path: Path, stamp: datetime) -> None:
    """Rewrite the xlsx zip with every entry's mtime pinned.

    Measured, not assumed, in two rounds: with the document properties
    pinned the two writes still differed at byte 11 — the zip local-header
    timestamp, which openpyxl fills from the wall clock — and after pinning
    that, at `docProps/core.xml`'s `<dcterms:modified>`, which `save()`
    re-stamps whatever the property was set to. `04` §5 wants byte-identical,
    so the entries are re-zipped with a fixed `date_time` in a fixed order
    and the two `dcterms` instants are rewritten to the pinned one.
    """
    iso = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    with zipfile.ZipFile(path) as source:
        entries = [(info.filename, source.read(info.filename)) for info in source.infolist()]
    pinned: list[tuple[str, bytes]] = []
    for name, data in entries:
        if name == "docProps/core.xml":
            text = data.decode("utf-8")
            text = re.sub(
                r"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)",
                rf"\g<1>{iso}\g<2>",
                text,
            )
            data = text.encode("utf-8")
        pinned.append((name, data))
    entries = pinned
    date_time = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, data)
    path.write_bytes(buffer.getvalue())


def format_report(report: AssemblyReport) -> str:
    lines = [
        f"assembly {report.sheet}: {report.rows} rows, {report.complete} complete, "
        f"{len(report.blank_row_uids)} blank (failed or missing)",
        f"PRODUCT_URL carries: {report.product_url_field}  [PROVISIONAL — Q2]",
        "resolution tiers: "
        + (
            ", ".join(f"{tier}={count}" for tier, count in sorted(report.tier_counts.items()))
            or "none"
        ),
        "filled per column:",
    ]
    for name in ["PRODUCT_URL", "REASONING", "MODULE", *CHARACTERISTIC_COLUMNS]:
        lines.append(f"  {name:52s} {report.column_fill[name]:4d}")
    if report.blank_row_uids:
        shown = report.blank_row_uids[:20]
        lines.append(
            "blank rows: "
            + ", ".join(f"{uid}({report.failure_stages.get(uid, '?')})" for uid in shown)
            + (" …" if len(report.blank_row_uids) > 20 else "")
        )
    return "\n".join(lines)


def assembly_summary_json(report: AssemblyReport) -> str:
    return json.dumps(
        {
            "sheet": report.sheet,
            "rows": report.rows,
            "complete": report.complete,
            "blank": len(report.blank_row_uids),
            "tier_counts": dict(report.tier_counts),
            "column_fill": dict(report.column_fill),
        },
        sort_keys=True,
    )
