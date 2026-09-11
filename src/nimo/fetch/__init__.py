"""P8 fetch — `specs/fetch.md` §2-§4.

The only place in the project that fetches candidate pages. `05` §2's controls
live here because they need DNS and the redirect chain; `nimo.retrieval` owns
only the cheap front gate on IP literals.
"""

from nimo.fetch.cache import (
    CachedPage,
    PageCache,
    PageCacheError,
    default_page_cache,
    page_key,
)
from nimo.fetch.client import Fetcher, FetchOutcome
from nimo.fetch.config import CONFIG_PATH, FetchConfig, FetchConfigError, load_fetch_config
from nimo.fetch.guard import (
    ALLOWED_SCHEMES,
    UnsafeUrlError,
    assert_safe_url,
    is_forbidden_address,
)
from nimo.fetch.images import (
    ImageCache,
    ImageCacheError,
    ImageOutcome,
    default_image_cache,
    fetch_image,
    image_key,
    resolve_image_url,
)
from nimo.fetch.robots import RobotsCache

__all__ = [
    "ALLOWED_SCHEMES",
    "CONFIG_PATH",
    "CachedPage",
    "FetchConfig",
    "FetchConfigError",
    "FetchOutcome",
    "Fetcher",
    "ImageCache",
    "ImageCacheError",
    "ImageOutcome",
    "default_image_cache",
    "fetch_image",
    "image_key",
    "resolve_image_url",
    "PageCache",
    "PageCacheError",
    "RobotsCache",
    "UnsafeUrlError",
    "assert_safe_url",
    "default_page_cache",
    "is_forbidden_address",
    "load_fetch_config",
    "page_key",
]
