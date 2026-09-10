"""Query strategy construction, S1–S5 — `specs/retrieval.md` §2, `03` §4 stage 2.

Pure: a `ProductQuery` in, a list of `SearchQuery` out, no network.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from nimo.contracts import ProductQuery
from nimo.loader import barcode_valid

StrategyName = Literal["S1", "S2", "S3", "S4", "S5"]


@dataclass(frozen=True)
class SearchQuery:
    """One query to issue, with the strategy that produced it.

    A frozen dataclass rather than a `contracts.py` model: it never crosses a
    pipeline stage boundary — it is consumed inside `retrieval/` and what
    leaves is `CandidateURL`, which carries `source_query` (`03` §3). Same
    reasoning as `ClassifierReport` at P5.
    """

    strategy: StrategyName
    text: str


@lru_cache(maxsize=4)
def _retailer_table(retailers_path: Path) -> dict[str, object]:
    """Parse `config/retailers.yaml` once, not once per row.

    Cached like every other config loader in this codebase
    (`normalize/vocab.py`, `classify/config.py`): `retailer_domain` is called
    per row, so an uncached read meant 412+ YAML parses per run.
    """
    table = yaml.safe_load(retailers_path.read_text(encoding="utf-8"))
    return table if isinstance(table, dict) else {}


def retailer_domain(retailer_raw: str, retailers_path: Path) -> str | None:
    """The retailer's product domain, or `None` when it has none.

    28 of 50 entries in `config/retailers.yaml` carry a domain; the rest are
    marketplaces, panels or aggregators with no single product site
    (`BRANDBANK`, `CWS CENSUS`, `POSITIVE SOLUTIONS`). `03` §4 stage 2:
    unmapped retailers skip S4.
    """
    entry = _retailer_table(retailers_path).get(retailer_raw)
    if not isinstance(entry, dict):
        return None
    domain = entry.get("domain")
    return domain if isinstance(domain, str) and domain else None


def _identity_phrase(query: ProductQuery) -> str:
    """Brand + variant terms + **format hints** + size — the S3/S4 payload.

    **The format hints are where the product-type noun lives, and omitting
    them made S3 nonsense.** P3 extracts `toothpaste`, `mouthwash`,
    `toothbrush`, `foam`, `spray` into `format_hints` rather than
    `variant_terms`, so an identity phrase built from variants alone drops the
    single most search-relevant word in the description. Measured on `dev`:
    252 of 412 rows carry at least one hint and **171 had one silently
    omitted** from their query.

    What that produced, live, before the fix:

        dev:68  "ultradex one go mouthwash on the go liquid sachets, 10 x 15ml"
                -> S3 "ULTRADEX one go on liquid 15ml"      (no "mouthwash")
        dev:92  "curaprox aligner care foam 40 ml"
                -> S3 "CURAPROX aligner care 40ml"           (no "foam")

    The first returned Stack Overflow and Server Fault pages, because
    "one go on liquid" is not a product query. `03` §4 stage 2's S3 shape is
    "brand + variant + size"; hints are part of the variant signal, not a
    separate axis, and `MatchFeatures.format_consistent` scoring them
    downstream does not help a query that never mentioned the product.
    """
    tokens = query.tokens
    parts = [query.brand, *tokens.variant_terms, *tokens.format_hints]
    if tokens.size_value is not None and tokens.size_unit:
        parts.append(f"{tokens.size_value:g}{tokens.size_unit}")
    return " ".join(part for part in parts if part).strip()


def build_queries(query: ProductQuery, retailers_path: Path) -> list[SearchQuery]:
    """S1–S5 for one row, in strategy order, skipping the ones it cannot use.

    **S1/S2 are gated on `barcode_valid`, not merely on "not corrupt", and on
    `dev` that is most of the strategy.** 35 `dev` rows survive the rounding
    defect but `01` §3 measured that only 18 are valid GTIN lengths — the rest
    are 6–7 digits (`266611`, `1071580`) and are not GTINs at all. Searching a
    non-GTIN as though it were one returns unrelated results with no error
    anywhere, which is a latent failure (`05` §5) rather than a bad query.
    """
    queries: list[SearchQuery] = []

    if barcode_valid(query.barcode) and not query.barcode_corrupt:
        barcode = query.barcode
        assert barcode is not None  # barcode_valid is False for None
        queries.append(SearchQuery("S1", f'"{barcode}"'))
        queries.append(SearchQuery("S2", f"{barcode} {query.brand}".strip()))

    identity = _identity_phrase(query)
    if identity:
        queries.append(SearchQuery("S3", identity))
        domain = retailer_domain(query.retailer_raw, retailers_path)
        if domain:
            queries.append(SearchQuery("S4", f"site:{domain} {identity}"))

    if query.desc_clean.strip():
        queries.append(SearchQuery("S5", query.desc_clean.strip()))

    return queries
