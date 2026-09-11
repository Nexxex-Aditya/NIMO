"""P7 candidate generation — `specs/retrieval.md`.

Public surface only.
"""

from nimo.retrieval.breaker import EngineBreaker
from nimo.retrieval.cache import (
    CacheError,
    SearchCache,
    cache_key,
    default_cache,
    now_seconds,
)
from nimo.retrieval.canonical import (
    ALLOWED_SCHEMES,
    UrlError,
    canonicalize,
    is_private_host,
    is_safe_candidate,
)
from nimo.retrieval.client import (
    EnginesUnresponsive,
    SearchError,
    SearxngClient,
    unresponsive_engines,
)
from nimo.retrieval.config import (
    CONFIG_PATH,
    EngineMode,
    RetrievalConfig,
    RetrievalConfigError,
    load_retrieval_config,
)
from nimo.retrieval.queries import SearchQuery, StrategyName, build_queries, retailer_domain
from nimo.retrieval.search import (
    SearchFn,
    SearchResult,
    brand_signal_rate,
    merge_candidates,
)

__all__ = [
    "brand_signal_rate",
    "now_seconds",
    "default_cache",
    "cache_key",
    "SearchCache",
    "EngineBreaker",
    "EngineMode",
    "EnginesUnresponsive",
    "CacheError",
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
    "unresponsive_engines",
]
