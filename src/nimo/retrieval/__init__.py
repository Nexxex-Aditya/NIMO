"""P7 candidate generation — `specs/retrieval.md`.

Public surface only.
"""

from nimo.retrieval.canonical import (
    ALLOWED_SCHEMES,
    UrlError,
    canonicalize,
    is_private_host,
    is_safe_candidate,
)
from nimo.retrieval.client import SearchError, SearxngClient
from nimo.retrieval.config import (
    CONFIG_PATH,
    RetrievalConfig,
    RetrievalConfigError,
    load_retrieval_config,
)
from nimo.retrieval.queries import SearchQuery, StrategyName, build_queries, retailer_domain
from nimo.retrieval.search import SearchFn, SearchResult, merge_candidates

__all__ = [
    "ALLOWED_SCHEMES",
    "CONFIG_PATH",
    "RetrievalConfig",
    "RetrievalConfigError",
    "SearchError",
    "SearchFn",
    "SearchQuery",
    "SearchResult",
    "SearxngClient",
    "StrategyName",
    "UrlError",
    "build_queries",
    "canonicalize",
    "is_private_host",
    "is_safe_candidate",
    "load_retrieval_config",
    "merge_candidates",
    "retailer_domain",
]
