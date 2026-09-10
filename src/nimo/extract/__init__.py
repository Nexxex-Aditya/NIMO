"""P8 evidence extraction — `specs/fetch.md` §5.

Pure functions over fetched HTML. The network lives in `nimo.fetch`.
"""

from nimo.extract.jsonld import (
    extract_jsonld_products,
    first_gtin,
    product_brand,
    product_name,
)
from nimo.extract.page import (
    FetchStatus,
    extract_body_text,
    extract_evidence,
    extract_images,
    extract_open_graph,
    extract_title,
)

__all__ = [
    "FetchStatus",
    "extract_body_text",
    "extract_evidence",
    "extract_images",
    "extract_jsonld_products",
    "extract_open_graph",
    "extract_title",
    "first_gtin",
    "product_brand",
    "product_name",
]
