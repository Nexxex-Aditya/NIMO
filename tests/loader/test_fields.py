"""Unit tests for the loader's pure field parsers — `specs/loader.md` §2–§7.

Small inline-string fixtures throughout, each one naming the real input
string it protects. No I/O, no network.
"""

import pytest

from nimo.loader.fields import (
    barcode_valid,
    collapse_whitespace,
    normalize_characteristic_name,
    parse_barcode,
    parse_brand,
    parse_countries,
    repair_encoding,
)

# --- §2a encoding repair -------------------------------------------------
# The mojibake below is the genuine `dev.BRAND` value (3 rows), not a
# constructed example. `01` §13 / `02-decision-log.md`.
REAL_MOJIBAKE_BRAND = "JASÃƒâ€“N"


def test_encoding_repair_fixes_the_real_corrupted_brand() -> None:
    """It must resolve correctly, not merely "do some repair"."""
    fixed, changed = repair_encoding(REAL_MOJIBAKE_BRAND)
    assert fixed == "JASÖN"
    assert changed is True


@pytest.mark.parametrize("text", ["pärla", "antibactérien", "colgate®", "aquafresh whitening"])
def test_encoding_repair_is_a_noop_on_legitimate_text(text: str) -> None:
    """Why unconditional application is safe — no "looks corrupted" branch.

    These are all real values already present in `dev`/`qa` (`01` §13).
    """
    fixed, changed = repair_encoding(text)
    assert fixed == text
    assert changed is False


# --- §2 barcode ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["5000000000000", "5030000000000", "8010000000000", "6280000000000", "20800000000"],
)
def test_corrupt_barcodes_are_nulled_not_passed_through(raw: str) -> None:
    """The registry-safety rule, not a formatting choice (`specs/loader.md` §2).

    A rounded value kept as `barcode` would let two unrelated products collide
    in Tier-0 lookup or the stage-4 GTIN hard rule — the registry-poisoning
    mode `05` §4/§5 exists to prevent.
    """
    barcode, barcode_raw, corrupt = parse_barcode(raw)
    assert corrupt is True
    assert barcode is None, "a corrupt barcode must never reach the `barcode` field"
    assert barcode_raw == raw, "the original is preserved for audit only"


@pytest.mark.parametrize(
    "raw", ["5014697056627", "5028763013070", "50376773", "0792554701778", "8902418000011"]
)
def test_intact_barcodes_pass_through(raw: str) -> None:
    barcode, barcode_raw, corrupt = parse_barcode(raw)
    assert corrupt is False
    assert barcode == raw
    assert barcode_raw == raw


def test_empty_barcode_cell() -> None:
    assert parse_barcode(None) == (None, None, False)


def test_corruption_regex_does_not_overmatch() -> None:
    """`specs/loader.md` §2: narrow to this defect, not "looks suspicious".

    Real GTINs can legitimately end in several zeros; only the rounded
    3-significant-figure signature counts.
    """
    for legitimate in ("5010000100000", "8901030100000"):
        barcode, _, corrupt = parse_barcode(legitimate)
        assert corrupt is False, f"{legitimate} is a plausible real GTIN, not the defect"
        assert barcode == legitimate


def test_leading_apostrophe_is_stripped_upstream_of_parse() -> None:
    """`sample_output`-style value (`01` §3). The strip happens in the cell
    reader (§1/§2); this pins the expected post-strip result."""
    raw = "'8714789613970"
    barcode, _, corrupt = parse_barcode(raw.lstrip("'").strip())
    assert barcode == "8714789613970"
    assert corrupt is False


@pytest.mark.parametrize(
    "barcode,expected",
    [
        ("8714789613970", True),  # EAN-13
        ("50376773", True),  # GTIN-8
        ("012345678905", True),  # UPC-A
        ("10012345678902", True),  # GTIN-14
        ("266611", False),  # 6 digits — real dev value, not a GTIN
        ("1071580", False),  # 7 digits — real dev value, not a GTIN
        (None, False),
    ],
)
def test_barcode_valid(barcode: str | None, expected: bool) -> None:
    assert barcode_valid(barcode) is expected


# --- §3 brand ------------------------------------------------------------
# The no-owner branch is 42% of distinct brands (`01` §2), so it gets equal
# coverage here rather than one token case.


@pytest.mark.parametrize(
    "raw,brand,owner",
    [
        ("AQUAFRESH (HALEON)", "AQUAFRESH", "HALEON"),
        ("COLGATE (COLGATE PALMOLIVE)", "COLGATE", "COLGATE PALMOLIVE"),
        ("PEARL DROPS (CHURCH & DWIGHT)", "PEARL DROPS", "CHURCH & DWIGHT"),
        ("BLANX (COSWELL)", "BLANX", "COSWELL"),
        ("MACLEANS (HALEON)", "MACLEANS", "HALEON"),
        ("WISDOM (WISDOM TOOTHBRUSH)", "WISDOM", "WISDOM TOOTHBRUSH"),
    ],
)
def test_brand_with_owner(raw: str, brand: str, owner: str) -> None:
    assert parse_brand(raw) == (brand, owner)


@pytest.mark.parametrize(
    "raw",
    [
        "GENGIGEL",
        "ORAL B",
        "POLIGRIP",
        "SENSODYNE",
        "LISTERINE",
        "THE HUMBLE CO.",
        "PHILIPS SONICARE",
    ],
)
def test_brand_without_owner(raw: str) -> None:
    """71 of 171 distinct brands (42%) take this branch — the common case."""
    assert parse_brand(raw) == (raw, None)


# --- §5 countries --------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("GB", ["GB"]),
        ("BE,GB,NL", ["BE", "GB", "NL"]),
        ("GB, IE", ["GB", "IE"]),
        ("FR,GB", ["FR", "GB"]),
    ],
)
def test_parse_countries(raw: str, expected: list[str]) -> None:
    assert parse_countries(raw) == expected


# --- §6 whitespace -------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("aquafresh whitening pump 100ml", "aquafresh whitening pump 100ml"),  # real: a no-op
        ("Colgate Total  Pump 100ML   ", "Colgate Total Pump 100ML"),  # sample_output shape
        ("  leading and trailing  ", "leading and trailing"),
        ("tabs\tand\nnewlines", "tabs and newlines"),
    ],
)
def test_collapse_whitespace(raw: str, expected: str) -> None:
    assert collapse_whitespace(raw) == expected


# --- §7 characteristic-name normalization --------------------------------


def test_alias_handles_the_one_irregular_name() -> None:
    """Asserted explicitly, not left to pass incidentally in the full-file check.

    A purely mechanical rule yields `GLOBAL_IF_WITH_INTERSPACE_CLAIM`, which
    is not a real `dev`/`qa` column, and the bijectivity assertion then raises
    on the real file (`01` §8).
    """
    assert normalize_characteristic_name("GLOBAL IF WITH INTERSPACE CLAIM") == (
        "GLOBAL_INTERSPACE_CLAIM"
    )


@pytest.mark.parametrize(
    "spaced,expected",
    [
        (
            "GLOBAL FLAVOUR/FRAGRANCE/INGREDIENT GROUP",
            "GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP",
        ),
        ("GLOBAL METHOD OF APPLICATION/DISPENSE", "GLOBAL_METHOD_OF_APPLICATION_DISPENSE"),
        ("GLOBAL BRISTLE STRENGTH CLAIM", "GLOBAL_BRISTLE_STRENGTH_CLAIM"),
        ("GLOBAL IF WITH FLUORIDE", "GLOBAL_IF_WITH_FLUORIDE"),
        ("GLOBAL PACKAGING", "GLOBAL_PACKAGING"),
        (
            "GLOBAL DESCRIPTIVE SIZE OF TOOTHBRUSH HEAD CLAIM",
            "GLOBAL_DESCRIPTIVE_SIZE_OF_TOOTHBRUSH_HEAD_CLAIM",
        ),
    ],
)
def test_mechanical_fallback_handles_spaces_and_slashes(spaced: str, expected: str) -> None:
    assert normalize_characteristic_name(spaced) == expected
