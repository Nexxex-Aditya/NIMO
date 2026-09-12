"""Bring-your-own product lists (`specs/input.md`): read as text, parsed by
the loader's own field parsers, keyed apart from the dataset."""

from pathlib import Path

import openpyxl
import pytest

from nimo.loader import DatasetSchemaError, input_name, input_rows, load_input
from tests.run.test_runner import CONFIG_DIR

RETAILERS = CONFIG_DIR / "retailers.yaml"

HEADER = ["RETAILER_DESC", "BRAND", "EXTERNAL_CODE", "RETAILER", "COUNTRY"]
ROWS: list[list[object]] = [
    ["aquafresh whitening pump 100ml", "AQUAFRESH (HALEON)", 5014697056627, "AMAZON (GB)", "GB"],
    ["listerine cool mint 500ml", "LISTERINE", "'5010123456789", "Corner Shop", None],
    ["sensodyne repair 75ml", "SENSODYNE (HALEON)", 5000000000000, None, "BE,GB"],
    ["  colgate   total  75ml ", "COLGATE", None, "BOOTS (GB) (HOMESCAN)", "GB"],
]


def write_xlsx(path: Path, header: list[str] = HEADER, rows: list[list[object]] = ROWS) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


def test_an_xlsx_with_the_input_columns_becomes_rows_through_the_loaders_parsers(
    tmp_path: Path,
) -> None:
    table = load_input(write_xlsx(tmp_path / "My Products (1).xlsx"))
    assert table.name == "my_products_1" and len(table.records) == 4
    rows = input_rows(table, RETAILERS)
    assert [r.row_uid for r in rows] == [f"my_products_1:{i}" for i in range(4)]

    first = rows[0]
    assert (first.brand, first.brand_owner) == ("AQUAFRESH", "HALEON")
    assert first.barcode == "5014697056627" and not first.barcode_corrupt  # int cell -> text
    assert first.retailer == "AMAZON"  # the hand-reviewed table, when it knows the string
    assert first.countries == ["GB"]
    assert (first.item_code, first.nan_key) == (0, 0)  # absent columns: visibly not codes

    second = rows[1]
    assert second.barcode == "5010123456789"  # the leading apostrophe stripped (`01` §3)
    assert second.retailer == "Corner Shop"  # unknown retailer: kept, not refused
    assert second.countries == ["GB"]  # no COUNTRY: the dataset's market, stated

    third = rows[2]
    assert third.barcode is None and third.barcode_corrupt  # a rounded value is a hole, not a code
    assert third.retailer == "UNKNOWN" and third.countries == ["BE", "GB"]

    fourth = rows[3]
    assert fourth.desc_raw == "colgate total 75ml"  # whitespace collapsed, like the dataset
    assert fourth.retailer == "BOOTS"  # `01` §12's silent-failure case, via the table


def test_a_csv_reads_the_same_way(tmp_path: Path) -> None:
    csv = tmp_path / "shelf.csv"
    csv.write_text(
        "RETAILER_DESC,BRAND,EXTERNAL_CODE\n"
        "oral-b pro 3 electric toothbrush,ORAL-B,4210201213925\n"
        "corsodyl daily mouthwash 500ml,CORSODYL (HALEON),\n",
        encoding="utf-8",
    )
    rows = input_rows(load_input(csv), RETAILERS)
    assert [r.row_uid for r in rows] == ["shelf:0", "shelf:1"]
    assert rows[0].barcode == "4210201213925" and rows[1].barcode is None
    assert rows[1].brand_owner == "HALEON"


def test_a_float_rendered_integer_barcode_is_read_as_the_integer(tmp_path: Path) -> None:
    csv = tmp_path / "codes.csv"
    csv.write_text("RETAILER_DESC,BRAND,EXTERNAL_CODE\nx toothpaste,X,5014697056627.0\n", "utf-8")
    assert input_rows(load_input(csv), RETAILERS)[0].barcode == "5014697056627"


def test_missing_required_columns_and_empty_files_are_refused(tmp_path: Path) -> None:
    with pytest.raises(DatasetSchemaError, match="RETAILER_DESC and BRAND"):
        load_input(write_xlsx(tmp_path / "bad.xlsx", ["RETAILER_DESC", "SIZE"], [["a", "b"]]))
    with pytest.raises(DatasetSchemaError, match="no data rows"):
        load_input(write_xlsx(tmp_path / "empty.xlsx", HEADER, []))
    (tmp_path / "list.txt").write_text("RETAILER_DESC,BRAND\nx,y\n", encoding="utf-8")
    with pytest.raises(DatasetSchemaError, match="expected .xlsx or .csv"):
        load_input(tmp_path / "list.txt")
    with pytest.raises(DatasetSchemaError, match="not found"):
        load_input(tmp_path / "nowhere.csv")
    blank = tmp_path / "blank.csv"
    blank.write_text("RETAILER_DESC,BRAND\n,X\n", encoding="utf-8")
    with pytest.raises(DatasetSchemaError, match="RETAILER_DESC is empty"):
        input_rows(load_input(blank), RETAILERS)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("My Products (1).xlsx", "my_products_1"),
        ("qa.csv", "input_qa"),  # cannot masquerade as the evaluation sheet
        ("dev.xlsx", "input_dev"),
        ("___.csv", "input"),
    ],
)
def test_the_name_is_derived_from_the_file_and_never_a_reserved_sheet(
    filename: str, expected: str
) -> None:
    assert input_name(Path(filename)) == expected
