"""JSON-LD extraction — `specs/fetch.md` §5, `03` §4 stage 3.

Pure: HTML in, parsed product markup out. No network.

Three behaviours here come from measuring real pages rather than from the
schema.org documentation, and each one is a page that would otherwise yield
nothing:

- **`@graph` nesting.** chemist-4-u's Product sits inside an
  `ItemPage`/`WebPage` `@graph`. A top-level `@type == "Product"` check finds
  nothing on that page.
- **A malformed block among valid ones.** aquafresh ships 5 `ld+json` blocks
  and one fails to parse. One bad block is a parse warning, not a failed page.
- **`@type` as a list.** `["ItemPage", "WebPage"]` is real markup, so a
  string comparison against `@type` misses it.
"""

import json
import re
from typing import Any

# Deliberately a regex rather than a full HTML parse: this runs over pages up
# to ~1.4 MB, the target is unambiguous, and a malformed page must still yield
# whatever blocks it does have. `extruct` handles microdata/RDFa where a real
# parse earns its cost.
_LD_JSON = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.S | re.I,
)


def _types_of(node: dict[str, Any]) -> list[str]:
    """`@type` normalized to a list. Real markup uses both forms."""
    raw = node.get("@type")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def _walk(node: object, found: list[dict[str, Any]]) -> None:
    """Collect every `Product` node, however deeply nested.

    Recurses through `@graph`, lists and nested objects. `mainEntity` and
    `isPartOf` chains put Products several levels down on real sites, so
    depth-limited traversal would be another thing to tune; walking the whole
    document is cheap at these sizes and has nothing to get wrong.
    """
    if isinstance(node, dict):
        if any("Product" in kind for kind in _types_of(node)):
            found.append(node)
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, found)


def extract_jsonld_products(html: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Every `schema.org/Product` node in the page, plus parse warnings.

    Returns `(products, warnings)`. A block that fails to parse contributes a
    warning and nothing else — `03` §3's `parse_warnings` exists so a page
    with partial evidence stays usable instead of being discarded.
    """
    products: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, block in enumerate(_LD_JSON.findall(html)):
        text = block.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError as error:
            warnings.append(f"ld+json block {index}: unparseable ({error})")
            continue
        _walk(parsed, products)

    return products, warnings


def first_gtin(products: list[dict[str, Any]]) -> str | None:
    """The first GTIN found, in schema.org's order of specificity.

    `03` §4 stage 4 makes a confirmed GTIN near-decisive, so this returns the
    value verbatim — no padding, no normalization, no guessing which length it
    "should" be. Comparing it to the query barcode is the matcher's job, and a
    silently reshaped identifier is exactly the defect `01` §3 is about.
    """
    for product in products:
        for key in ("gtin13", "gtin14", "gtin12", "gtin8", "gtin"):
            value = product.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, int):
                return str(value)
    return None


def product_name(products: list[dict[str, Any]]) -> str | None:
    for product in products:
        name = product.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def product_brand(products: list[dict[str, Any]]) -> str | None:
    """Brand, which schema.org allows as a string or a nested `Brand` object."""
    for product in products:
        brand = product.get("brand")
        if isinstance(brand, str) and brand.strip():
            return brand.strip()
        if isinstance(brand, dict):
            name = brand.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None
