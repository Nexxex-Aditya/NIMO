"""End-to-end normalizer tests — `specs/normalize.md` acceptance criteria.

The parametrized block below is the P3 gate (`04` §1): hand-written cases
built from **real** `dev`/`qa` rows, each asserting the fields that row is
protecting. The whole-dataset invariants at the bottom run against the real
committed workbook.
"""

from pathlib import Path

import pytest

from nimo.contracts import ProductQuery, RawRow
from nimo.loader import load_rows
from nimo.normalize import normalize_row, normalize_rows
from nimo.normalize.vocab import load_vocabularies

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
RETAILERS = REPO_ROOT / "config" / "retailers.yaml"


def make_row(desc: str, brand: str, retailer_raw: str, retailer: str) -> RawRow:
    """A minimal RawRow carrying only what the normalizer reads."""
    return RawRow(
        nan_key=1,
        item_code=1,
        barcode=None,
        barcode_raw=None,
        barcode_corrupt=False,
        brand_raw=brand,
        brand=brand,
        brand_owner=None,
        brand_encoding_suspect=False,
        retailer_raw=retailer_raw,
        retailer=retailer,
        countries=["GB"],
        desc_raw=desc,
        desc_encoding_suspect=False,
    )


# Each tuple: (label, desc_raw, brand, retailer_raw, retailer,
#              expected size_value, size_unit, size_ml_equiv, size_g_equiv, count)
# Every `desc_raw` below is a real string from the committed workbook.
REAL_CASES: list[
    tuple[str, str, str, str, str, float | None, str | None, float | None, float | None, int | None]
] = [
    (
        "canonical worked example — junk both sides, ml size, pump format",
        "aquafresh whitening pump 100ml unit 00000012 e0028",
        "AQUAFRESH",
        "E0028 (GB) WAITROSE",
        "WAITROSE",
        100.0,
        "ml",
        100.0,
        None,
        None,
    ),
    (
        "brand repeated mid-string + concentration percentage",
        "wisdom mouthwash chlorhexidine digluconate 0.2% original alcohol free 300ml "
        "wisdom chlorhexidine mouthwash intouch",
        "WISDOM",
        "InTouch (GB)",
        "INTOUCH",
        300.0,
        "ml",
        300.0,
        None,
        None,
    ),
    (
        "THE size trap — x 250ml must not become count 250",
        "dentex anti plaque and whitening mouthwash twin pack x 250ml 0.89 home bargains",
        "MEDEX",
        "HOME BARGAINS",
        "HOME BARGAINS",
        250.0,
        "ml",
        250.0,
        None,
        2,
    ),
    (
        "mass-only row — size_g_equiv, not size_ml_equiv",
        "crest 3d charcoal tooth paste 85g p00d6",
        "CREST",
        "P00D6 (GB) POSITIVE SOLUTIONS LTD",
        "POSITIVE SOLUTIONS LTD",
        85.0,
        "g",
        None,
        85.0,
        None,
    ),
    (
        "mass-only row, second real example",
        "tom's pepermint toothpaste 170g p00d6",
        "TOMS",
        "P00D6 (GB) POSITIVE SOLUTIONS LTD",
        "POSITIVE SOLUTIONS LTD",
        170.0,
        "g",
        None,
        170.0,
        None,
    ),
    (
        "duplicate size + amazon boilerplate count",
        "jason coconut mint strengthening toothpaste 119g|119.00 g (pack of 1) amazon",
        "JASON",
        "AMAZON (GB)",
        "AMAZON",
        119.0,
        "g",
        None,
        119.0,
        1,
    ),
    (
        "non-ASCII brand token survives tokenization",
        "nûby all natural toddler training clear toothpaste 6m+ 45g brandbank",
        "NUBY",
        "BRANDBANK (UK)",
        "BRANDBANK",
        45.0,
        "g",
        None,
        45.0,
        None,
    ),
    (
        "x8 suffix count, unit-of-sale 'u' stripped",
        "listerine go tabs x8 u e0055",
        "LISTERINE",
        "E0055 (GB) SAINSBURY",
        "SAINSBURY",
        None,
        None,
        None,
        None,
        8,
    ),
    (
        "xN after a product noun",
        "sensodyne complete toothbrush medium x12 e00d9",
        "SENSODYNE",
        "E00D9 (GB) OXFORD OFFICE USE ONLY",
        "OXFORD OFFICE USE ONLY",
        None,
        None,
        None,
        None,
        12,
    ),
    (
        "leading multiplier beats trailing amazon boilerplate",
        "12x wisdom smokers extra hard brush toothbrush (previously addis)"
        "|1 count (pack of 12) amazon new",
        "WISDOM",
        "AMAZON NEW (GB)",
        "AMAZON",
        None,
        None,
        None,
        None,
        12,
    ),
    (
        "N x followed by a size — sachet multipack",
        "ultradex one go mouthwash on the go liquid sachets, 10 x 15ml"
        "|1 count (pack of 10) amazon new",
        "ULTRADEX",
        "AMAZON NEW (GB)",
        "AMAZON",
        15.0,
        "ml",
        15.0,
        None,
        10,
    ),
    (
        "2 x 150g — count and mass together",
        "colgate total 12 hour protection professional whitening antibacteria & "
        "fluoride toothpaste 2 x 150g brandbank",
        "COLGATE",
        "BRANDBANK (UK)",
        "BRANDBANK",
        150.0,
        "g",
        None,
        150.0,
        2,
    ),
    (
        "Ns count form",
        "oral b eb 417-2 dual action refills 2s each e00n3",
        "ORAL B",
        "E00N3 (GB) CWS CENSUS",
        "CWS",
        None,
        None,
        None,
        None,
        2,
    ),
    (
        "N's count form with asterisk separators and gm mass",
        "c/dg spearmint sensation*18 gm*sgl*10's*std e00f9",
        "COLGATE",
        "E00F9 (GB) FIELD RETAIL AUDIT",
        "FIELD RETAIL AUDIT",
        18.0,
        "g",
        None,
        18.0,
        10,
    ),
    (
        "promotional percentage is not a size",
        "colgate superfresh 75ml*75 ml*sgl*50% extra e00f9",
        "COLGATE",
        "E00F9 (GB) FIELD RETAIL AUDIT",
        "FIELD RETAIL AUDIT",
        75.0,
        "ml",
        75.0,
        None,
        None,
    ),
    (
        "spelled-out unit",
        "listerine coolmint 500 millilitres p00n8",
        "LISTERINE",
        "P00N8 (GB) MARKS & SPENCER",
        "MARKS & SPENCER",
        500.0,
        "ml",
        500.0,
        None,
        None,
    ),
    (
        "x30 denture tablets",
        "s/d denture tab ext/s x30 e0030",
        "SUPERDRUG",
        "E0030 (GB) SUPERDRUG",
        "SUPERDRUG",
        None,
        None,
        None,
        None,
        30,
    ),
    (
        "pack of 8 beats the trailing count boilerplate",
        "oral-b pro kids toothbrush heads featuring disney the lion king, "
        "pack of 8 counts|8 count (pack of 1) amazon new",
        "ORAL B",
        "AMAZON NEW (GB)",
        "AMAZON",
        None,
        None,
        None,
        None,
        8,
    ),
    (
        "marketing claim 3x more — must not become a 3-pack",
        "colgate total active prevention+ decay + erosion defence toothpaste 75ml, "
        "3x more effective at fighting plaque brandbank",
        "COLGATE",
        "BRANDBANK (UK)",
        "BRANDBANK",
        75.0,
        "ml",
        75.0,
        None,
        None,
    ),
    (
        "marketing claim 2x stronger — must not become a 2-pack",
        "sensodyne pronamel junior 6-12 years toothpaste for juniors, "
        "2x stronger enamel defence brandbank",
        "SENSODYNE",
        "BRANDBANK (UK)",
        "BRANDBANK",
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "no size, no count — the common case (368 of 824 rows have no size)",
        "philips sonicare 1 series power up ocado",
        "PHILIPS SONICARE",
        "OCADO",
        "OCADO",
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "mouthspray with small ml size",
        "macleans confidence mouthspray 15ml e00n3",
        "MACLEANS",
        "E00N3 (GB) CWS CENSUS",
        "CWS",
        15.0,
        "ml",
        15.0,
        None,
        None,
    ),
    (
        "twin pack without an x",
        "colgate max white sparkle diamonds toothpaste twin pack 75ml brandbank",
        "COLGATE",
        "BRANDBANK (UK)",
        "BRANDBANK",
        75.0,
        "ml",
        75.0,
        None,
        2,
    ),
    (
        "2pk suffix",
        "morrisons savers twin pack toothbrushes medium 2pk e00r7",
        "MORRISONS",
        "E00R7 (GB) MORRISONS",
        "MORRISONS",
        None,
        None,
        None,
        None,
        2,
    ),
    (
        "large tablet count",
        "clear brushd freshmint mthwsh tblts 120s p00d6",
        "BRUSHD",
        "P00D6 (GB) POSITIVE SOLUTIONS LTD",
        "POSITIVE SOLUTIONS LTD",
        None,
        None,
        None,
        None,
        120,
    ),
    (
        "500s count",
        "sotol tabs 500's so055 500 p00d6",
        "SOTOL",
        "P00D6 (GB) POSITIVE SOLUTIONS LTD",
        "POSITIVE SOLUTIONS LTD",
        None,
        None,
        None,
        None,
        500,
    ),
    (
        "x 6 with a space",
        "b tooth wipes junior x 6 p00d6",
        "BRUSHBABY",
        "P00D6 (GB) POSITIVE SOLUTIONS LTD",
        "POSITIVE SOLUTIONS LTD",
        None,
        None,
        None,
        None,
        6,
    ),
    (
        "x2 replacement heads is a real multiplier, not a claim",
        "oral b rep head x2 e0022",
        "ORAL B",
        "E0022 (GB) TESCO",
        "TESCO",
        None,
        None,
        None,
        None,
        2,
    ),
    (
        "x 24 breath strips",
        "js breath strips x 24 e0055",
        "JS",
        "E0055 (GB) SAINSBURY",
        "SAINSBURY",
        None,
        None,
        None,
        None,
        24,
    ),
    (
        "mouthwash 500ml x12 — multipack of a sized product",
        "active whitening m/wash 500ml x12 (norchem) p00d6",
        "ACTIVE",
        "P00D6 (GB) POSITIVE SOLUTIONS LTD",
        "POSITIVE SOLUTIONS LTD",
        500.0,
        "ml",
        500.0,
        None,
        12,
    ),
    (
        "concatenated duplicate mass — corrupted but must not raise",
        "mumtaz after eat 300gmumtaz after eat300g e00i7",
        "MUMTAZ",
        "E00I7 (GB) WAL*MART",
        "WAL*MART",
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "denture tablets 30s",
        "bs den cle tabs mint 30 boots smile denture cleansetabs mint 30s p00r4",
        "BOOTS",
        "P00R4 (GB) BOOTS",
        "BOOTS",
        None,
        None,
        None,
        None,
        30,
    ),
]


@pytest.mark.parametrize(
    "label,desc,brand,retailer_raw,retailer,size_value,size_unit,ml,g,count",
    REAL_CASES,
    ids=[case[0] for case in REAL_CASES],
)
def test_real_row_cases(
    label: str,
    desc: str,
    brand: str,
    retailer_raw: str,
    retailer: str,
    size_value: float | None,
    size_unit: str | None,
    ml: float | None,
    g: float | None,
    count: int | None,
) -> None:
    """The P3 gate: hand-written cases from real dev/qa description strings."""
    query = normalize_row(make_row(desc, brand, retailer_raw, retailer))
    tokens = query.tokens
    assert tokens.size_value == size_value, label
    assert tokens.size_unit == size_unit, label
    assert tokens.size_ml_equiv == ml, label
    assert tokens.size_g_equiv == g, label
    assert tokens.count == count, label


def test_the_gate_has_at_least_thirty_cases() -> None:
    """`04` §1 P3 gate: 30 hand-written cases from real dev rows."""
    assert len(REAL_CASES) >= 30


# --- Whole-dataset invariants (acceptance criteria 5–8) ------------------


@pytest.fixture(scope="module")
def all_queries() -> list[ProductQuery]:
    rows = load_rows(WORKBOOK, "dev", RETAILERS) + load_rows(WORKBOOK, "qa", RETAILERS)
    return normalize_rows(rows)


def test_every_real_row_normalizes_without_raising(all_queries: list[ProductQuery]) -> None:
    """AC5 — 824 rows, no exceptions."""
    assert len(all_queries) == 824


def test_size_dimensions_are_mutually_exclusive(all_queries: list[ProductQuery]) -> None:
    """AC5 — never both, on any real row. The invariant `03` §3 states."""
    for query in all_queries:
        tokens = query.tokens
        if tokens.size_value is None:
            assert tokens.size_ml_equiv is None and tokens.size_g_equiv is None
        else:
            assert (tokens.size_ml_equiv is None) != (tokens.size_g_equiv is None)


def test_retailer_suffix_stripped_on_every_row(all_queries: list[ProductQuery]) -> None:
    """AC6 — the measured 824/824, asserted so a regression is visible."""
    assert all(query.tokens.stripped_junk for query in all_queries)


def test_every_stripped_token_belongs_to_a_named_junk_class(
    all_queries: list[ProductQuery],
) -> None:
    """AC6 — nothing is removed that isn't one of the five classes in §1.

    This is the safety property behind "strip, never delete silently"
    (`03` §4): every entry in `stripped_junk` must be attributable to a rule,
    so an over-eager rule shows up here rather than as quietly missing
    content. The classes are §1a retailer suffix, §1b `unit N`, §1c
    unit-of-sale code, §1d duplicate size, §1e repeated brand.
    """
    unit_of_sale, _, _, _ = load_vocabularies()
    for query in all_queries:
        retailer_text = f"{query.retailer_raw} {query.retailer}".lower()
        brand_text = f"{query.brand} {query.brand_raw}".lower()
        for junk in query.tokens.stripped_junk:
            cleaned = junk.lower().strip()
            attributable = (
                cleaned in retailer_text  # §1a
                or cleaned.startswith("unit ")  # §1b
                or cleaned in unit_of_sale  # §1c
                or any(char.isdigit() for char in cleaned)  # §1d duplicate size
                or cleaned in brand_text  # §1e repeated brand
            )
            assert attributable, (
                f"{junk!r} stripped from nan_key={query.nan_key} matches none of the five "
                f"junk classes in specs/normalize.md §1 — retailer "
                f"{query.retailer_raw!r}, brand {query.brand!r}"
            )


def test_free_and_extra_survive_as_variant_terms(all_queries: list[ProductQuery]) -> None:
    """AC7 — 43 rows say `alcohol free`, 31 say `extra soft`."""
    assert sum("free" in query.tokens.variant_terms for query in all_queries) > 20
    assert sum("extra" in query.tokens.variant_terms for query in all_queries) > 20


def test_normalization_is_deterministic(all_queries: list[ProductQuery]) -> None:
    """AC8 — twice-run byte-identical over the whole dataset (`04` §5)."""
    rows = load_rows(WORKBOOK, "dev", RETAILERS) + load_rows(WORKBOOK, "qa", RETAILERS)
    again = normalize_rows(rows)
    assert [query.model_dump_json() for query in again] == [
        query.model_dump_json() for query in all_queries
    ]


def test_row_order_is_preserved(all_queries: list[ProductQuery]) -> None:
    rows = load_rows(WORKBOOK, "dev", RETAILERS) + load_rows(WORKBOOK, "qa", RETAILERS)
    assert [query.nan_key for query in all_queries] == [row.nan_key for row in rows]


def test_product_query_carries_every_rawrow_field(all_queries: list[ProductQuery]) -> None:
    """`03` §3's inheritance split — nothing from the loader is dropped."""
    query = all_queries[0]
    assert isinstance(query, RawRow)
    for field in RawRow.model_fields:
        assert hasattr(query, field)
