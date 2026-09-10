"""Block-key computation — `specs/registry.md` §2, `03` §4 stage 1 step 1.

Pure. No I/O, no state, no clock.
"""

import hashlib

from nimo.contracts import BlockKey, ProductQuery


def fingerprint(
    brand: str,
    size_ml_equiv: float | None,
    size_g_equiv: float | None,
    count: int,
) -> str:
    """Deterministic identity fingerprint. `03` §1a.

    Both size dimensions participate because 35 rows are mass-only and the two
    are never interconverted (`03` §3's size note) — a fingerprint that read
    only ml would collapse every mass-sized product of a brand into one block.

    Formatted through `repr`-stable pieces rather than an f-string on floats,
    so `100` and `100.0` cannot produce two different blocks for one product.
    """
    parts = [
        brand.strip().upper(),
        "" if size_ml_equiv is None else f"{float(size_ml_equiv):.4f}",
        "" if size_g_equiv is None else f"{float(size_g_equiv):.4f}",
        str(count),
    ]
    return "|".join(parts)


def gtin_block_key(query: ProductQuery) -> BlockKey | None:
    """The row's Tier-0 key: a clean GTIN, or `None`.

    A corrupt barcode never becomes a key — `01` §3, and the decision log's
    "barcode nulling is a registry safety rule": two unrelated products that
    round to the same truncated value would otherwise block together.
    """
    if query.barcode is not None and not query.barcode_corrupt:
        return BlockKey(key=query.barcode, method="exact_gtin")
    return None


def fingerprint_block_key(query: ProductQuery) -> BlockKey | None:
    """The row's Tier-1 key: a content fingerprint, or `None` when unsized.

    `None` for a row with no parsed size, a deliberate coverage limit rather
    than an oversight (`specs/registry.md` §2): blocking on `brand + count`
    alone would put every unsized Colgate row in one block, and over-broad
    blocking is the failure this design is most exposed to (`03` §1a).
    """
    tokens = query.tokens
    if tokens.size_ml_equiv is None and tokens.size_g_equiv is None:
        return None
    return BlockKey(
        key=fingerprint(
            query.brand,
            tokens.size_ml_equiv,
            tokens.size_g_equiv,
            tokens.count if tokens.count is not None else 1,
        ),
        method="fingerprint",
    )


def block_keys(query: ProductQuery) -> list[BlockKey]:
    """Every key this row can be blocked under, in tier order.

    **A row gets BOTH keys where it has both**, and that is a correction to
    `03` §4 stage 1 step 1, which read "block key = clean barcode when
    present, **else** a fingerprint". The `else` is wrong, and measurably so:
    `qa` carries a clean barcode on 412 of 412 rows, so under an either/or
    rule every `qa` row gets a GTIN key, no `qa` row ever gets a fingerprint
    key, and **Tier 1 is unreachable for the entire evaluation set** — while
    0 of those GTINs appear in `dev`, so Tier 0 misses all 412 too.

    A Tier-0 miss does not mean the product is new. It means nobody has
    resolved *that GTIN* before; the same product may well sit in the registry
    under a different retailer's row whose barcode was absent or corrupt. So
    the fingerprint key has to remain available as the Tier-1 fallback, which
    is what `03` §4 stage 1 step 3's "no exact hit → ... within the same
    block" always implied.
    """
    keys = [key for key in (gtin_block_key(query), fingerprint_block_key(query)) if key is not None]
    return keys


def entity_id(key: BlockKey) -> str:
    """Stable, reproducible entity id — `03` §3 forbids a random uuid.

    The same product resolved on two different days in two different runs
    must land on the same id, or the registry cannot warm-start across runs
    (`03` §5), which is the whole point of persisting it.
    """
    digest = hashlib.sha256(key.key.encode("utf-8")).hexdigest()[:16]
    prefix = "gtin" if key.method == "exact_gtin" else "fp"
    return f"{prefix}:{digest}"
