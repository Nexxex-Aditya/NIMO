"""Pure field-level parsers for the loader — `specs/loader.md` §2–§7.

Every function here is deterministic, does no I/O, and is unit-tested in
isolation. The workbook reading and row assembly that use them live in
`dataset.py`.
"""

import re

import ftfy

# `01` §3's corruption signature: a value rounded to ~3 significant figures by
# Excel's `0.00E+00` cell format. Deliberately narrow — it matches THIS defect,
# not "looks suspicious" in general. Do not widen it to reject barcodes that
# legitimately end in zeros (`specs/loader.md` §2).
_CORRUPT_BARCODE_RE = re.compile(r"\d{1,3}0{6,}")

# `NAME (OWNER)`. The no-parens branch is the common case, not an edge case:
# 71 of 171 distinct brands (42%) have no owner suffix (`01` §2).
_BRAND_RE = re.compile(r"(?P<brand>.+?)\s*\((?P<owner>[^)]+)\)\s*")

_WHITESPACE_RE = re.compile(r"\s+")

# GTIN-8 / UPC-A / EAN-13 / GTIN-14.
_VALID_BARCODE_LENGTHS = frozenset({8, 12, 13, 14})

# `01` §8: 12 of 13 characteristic names normalize mechanically; one drops
# "IF WITH " entirely rather than transforming it. A hand-coded exception
# table is more honest than a regex clever enough to absorb an irregular
# abbreviation — and it fails visibly if a 14th name ever appears.
CHARACTERISTIC_NAME_ALIASES = {
    "GLOBAL IF WITH INTERSPACE CLAIM": "GLOBAL_INTERSPACE_CLAIM",
}


def repair_encoding(raw: str) -> tuple[str, bool]:
    """Repair mojibake, and report whether anything actually changed.

    `specs/loader.md` §2a. Applied unconditionally — `ftfy` decides internally
    whether a repair is warranted, more reliably than a "does this look
    corrupted" branch would. Verified a no-op on the legitimate multilingual
    text already in the data.
    """
    fixed = ftfy.fix_text(raw)
    return fixed, fixed != raw


def parse_barcode(raw_str: str | None) -> tuple[str | None, str | None, bool]:
    """`EXTERNAL_CODE` -> (barcode, barcode_raw, barcode_corrupt).

    `specs/loader.md` §2. `barcode` is `None` whenever `barcode_corrupt` is
    True — a safety rule, not formatting. A rounded value kept as if real
    would let two unrelated products collide in Tier-0 registry lookup or the
    stage-4 GTIN hard rule, which is the registry-poisoning failure mode
    `05` §4/§5 exists to prevent. The original is preserved in `barcode_raw`
    for audit only and must never be used for matching or blocking.
    """
    if raw_str is None:
        return None, None, False
    if _CORRUPT_BARCODE_RE.fullmatch(raw_str):
        return None, raw_str, True
    return raw_str, raw_str, False


def barcode_valid(barcode: str | None) -> bool:
    """`01` §10 criterion 1's validity signal, as a derived function.

    Not a `RawRow` field: it is a pure function of `barcode`, which the row
    already carries, and duplicated derived state can drift out of sync with
    its source. `03` §3 is the contract authority and does not list it.
    """
    return barcode is not None and len(barcode) in _VALID_BARCODE_LENGTHS


def parse_brand(brand_raw: str) -> tuple[str, str | None]:
    """`BRAND` -> (brand, brand_owner). `specs/loader.md` §3.

    Expects an already encoding-repaired string (§2a runs first).
    """
    match = _BRAND_RE.fullmatch(brand_raw)
    if match:
        return match["brand"].strip(), match["owner"].strip()
    return brand_raw.strip(), None


def parse_countries(country_raw: str) -> list[str]:
    """`COUNTRY` -> `list[str]`. `specs/loader.md` §5."""
    return [c.strip() for c in country_raw.split(",")]


def collapse_whitespace(text: str) -> str:
    """`specs/loader.md` §6. Verified a no-op on real `dev`/`qa` data; kept as
    a cheap defensive step, since the encoding repair that runs first (§2a)
    can in principle introduce whitespace-like artifacts."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_characteristic_name(spaced: str) -> str:
    """Spaced rule-sheet name -> the underscored `dev`/`qa` column name.

    `specs/loader.md` §7. Alias table first, mechanical rule as fallback.
    Relying on the mechanical rule alone produces
    `GLOBAL_IF_WITH_INTERSPACE_CLAIM`, which is not a real column, and the
    bijectivity assertion then raises on the real file.
    """
    stripped = spaced.strip()
    if stripped in CHARACTERISTIC_NAME_ALIASES:
        return CHARACTERISTIC_NAME_ALIASES[stripped]
    return stripped.upper().replace("/", "_").replace(" ", "_")
