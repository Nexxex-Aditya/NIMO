"""P6 blocking tests — `specs/registry.md` §2, §9."""

import pytest

from nimo.contracts import DescTokens, ProductQuery
from nimo.registry import block_keys, entity_id, fingerprint, fingerprint_block_key, gtin_block_key


def tokens(
    size_ml: float | None = 100.0, size_g: float | None = None, count: int | None = None
) -> DescTokens:
    return DescTokens(
        variant_terms=["whitening"],
        size_value=size_ml or size_g,
        size_unit="ml" if size_ml else "g",
        size_ml_equiv=size_ml,
        size_g_equiv=size_g,
        count=count,
        format_hints=[],
        stripped_junk=[],
    )


def query(
    row_uid: str = "dev:0",
    barcode: str | None = None,
    corrupt: bool = False,
    desc_tokens: DescTokens | None = None,
    brand: str = "AQUAFRESH",
) -> ProductQuery:
    return ProductQuery(
        row_uid=row_uid,
        nan_key=1,
        item_code=1,
        barcode=barcode,
        barcode_raw=barcode,
        barcode_corrupt=corrupt,
        brand_raw=f"{brand} (HALEON)",
        brand=brand,
        brand_owner="HALEON",
        brand_encoding_suspect=False,
        retailer_raw="P00R4 (GB) BOOTS",
        retailer="BOOTS",
        countries=["GB"],
        desc_raw="x",
        desc_encoding_suspect=False,
        desc_clean="x",
        tokens=desc_tokens if desc_tokens is not None else tokens(),
    )


def test_clean_barcode_gives_a_gtin_key() -> None:
    key = gtin_block_key(query(barcode="5014697056627"))
    assert key is not None
    assert key.method == "exact_gtin"
    assert key.key == "5014697056627"


def test_corrupt_barcode_never_becomes_a_key() -> None:
    """`01` §3: two unrelated products that round to the same truncated value
    would otherwise block together — registry poisoning from the source data."""
    assert gtin_block_key(query(barcode="5000000000000", corrupt=True)) is None


def test_unsized_row_gets_no_fingerprint_key() -> None:
    """A deliberate coverage limit: blocking on brand+count alone would put
    every unsized Colgate row in one block (`specs/registry.md` §2)."""
    unsized = tokens(size_ml=None, size_g=None)
    assert fingerprint_block_key(query(desc_tokens=unsized)) is None
    assert block_keys(query(desc_tokens=unsized)) == []


def test_a_row_with_a_barcode_still_gets_a_fingerprint_key() -> None:
    """The correction to `03` §4 stage 1 step 1's "clean barcode ... else
    fingerprint". `qa` carries a clean barcode on 412/412 rows, so under an
    either/or rule no `qa` row would ever get a fingerprint key and Tier 1
    would be unreachable for the entire evaluation set — while 0 of those
    GTINs appear in `dev`, so Tier 0 misses all 412 too."""
    keys = block_keys(query(barcode="5014697056627"))
    assert [key.method for key in keys] == ["exact_gtin", "fingerprint"]


def test_both_size_dimensions_participate() -> None:
    """35 rows are mass-only; a fingerprint reading only ml would collapse
    every mass-sized product of a brand into one block (`03` §3 size note)."""
    ml = fingerprint("AQUAFRESH", 100.0, None, 1)
    grams = fingerprint("AQUAFRESH", None, 100.0, 1)
    assert ml != grams


def test_integer_and_float_sizes_do_not_split_a_block() -> None:
    assert fingerprint("AQUAFRESH", 100, None, 1) == fingerprint("AQUAFRESH", 100.0, None, 1)


def test_absent_count_is_treated_as_one() -> None:
    """`DescTokens.count` is None for a single, per `03` §3."""
    single = fingerprint_block_key(query(desc_tokens=tokens(count=None)))
    explicit = fingerprint_block_key(query(desc_tokens=tokens(count=1)))
    assert single is not None and explicit is not None
    assert single.key == explicit.key


def test_multipack_blocks_separately_from_a_single() -> None:
    """`03` §4 stage 0: multipack count is a hard identity attribute."""
    single = fingerprint_block_key(query(desc_tokens=tokens(count=1)))
    pack = fingerprint_block_key(query(desc_tokens=tokens(count=2)))
    assert single is not None and pack is not None
    assert single.key != pack.key


def test_brand_is_case_and_whitespace_insensitive() -> None:
    assert fingerprint(" aquafresh ", 100.0, None, 1) == fingerprint("AQUAFRESH", 100.0, None, 1)


def test_entity_id_is_stable_and_method_prefixed() -> None:
    """`03` §3 forbids a random uuid: the same product resolved on two
    different days in two different runs must land on the same id, or the
    registry cannot warm-start across runs (`03` §5)."""
    gtin = gtin_block_key(query(barcode="5014697056627"))
    assert gtin is not None
    assert entity_id(gtin) == entity_id(gtin)
    assert entity_id(gtin).startswith("gtin:")

    fp = fingerprint_block_key(query())
    assert fp is not None
    assert entity_id(fp).startswith("fp:")


def test_a_gtin_and_a_fingerprint_never_collide_on_one_id() -> None:
    gtin = gtin_block_key(query(barcode="5014697056627"))
    fp = fingerprint_block_key(query())
    assert gtin is not None and fp is not None
    assert entity_id(gtin) != entity_id(fp)


@pytest.mark.parametrize("brand", ["AQUAFRESH", "COLGATE", "SENSODYNE"])
def test_different_brands_block_separately(brand: str) -> None:
    keys = {fingerprint(other, 100.0, None, 1) for other in ("AQUAFRESH", "COLGATE", "SENSODYNE")}
    assert len(keys) == 3
    assert fingerprint(brand, 100.0, None, 1) in keys
