"""The Brave Search API backend — `specs/retrieval.md` §5b.

Built for the one machine SearxNG cannot run on: the office laptop has no
hardware virtualisation, so no Docker, so no self-hosted meta-search. The
Brave Search API is a plain HTTPS endpoint with a subscription key, and it
does not CAPTCHA.

**Cache-first over everything already harvested.** Before calling the API,
the cache is consulted for this query under every SearxNG engine the free
portfolio used (`config.engines`) and under `brave_api` itself; any entry —
even an empty one — is served. So a row the home harvest resolved costs no
credit and gives byte-identical candidates, and only a query nobody has
asked before reaches the API. The credits are paid, so a per-run cap
(`max_calls_per_run`) turns a runaway into a typed failure instead of a bill.
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import structlog
import yaml

from nimo.retrieval.cache import SearchCache, now_seconds
from nimo.retrieval.client import SearchError
from nimo.retrieval.config import CONFIG_PATH, RetrievalConfig, RetrievalConfigError
from nimo.retrieval.queries import SearchQuery
from nimo.retrieval.search import SearchResult

log = structlog.get_logger(__name__)

ENGINE = "brave_api"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class BraveApiConfig:
    endpoint: str
    country: str
    min_interval_s: float
    max_calls_per_run: int
    max_query_chars: int


@lru_cache(maxsize=1)
def load_brave_config(path: Path = CONFIG_PATH) -> BraveApiConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    block = data.get("brave_api") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        raise RetrievalConfigError(f"{path}: `brave_api` must be a mapping.")
    try:
        config = BraveApiConfig(
            endpoint=str(block["endpoint"]),
            country=str(block["country"]),
            min_interval_s=float(block["min_interval_s"]),
            max_calls_per_run=int(block["max_calls_per_run"]),
            max_query_chars=int(block["max_query_chars"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RetrievalConfigError(f"{path}: `brave_api` is incomplete: {error}") from error
    if not config.endpoint.startswith("https://"):
        raise RetrievalConfigError(f"{path}: `brave_api.endpoint` must be https.")
    if config.max_calls_per_run < 0 or config.max_query_chars < 1:
        raise RetrievalConfigError(f"{path}: `brave_api` limits must be positive.")
    return config


def search_backend(path: Path = CONFIG_PATH) -> str:
    """`auto` | `brave_api` | `searxng` — `config/retrieval.yaml`."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    value = data.get("search_backend", "auto") if isinstance(data, dict) else "auto"
    if value not in ("auto", "brave_api", "searxng"):
        raise RetrievalConfigError(f"{path}: `search_backend` must be auto|brave_api|searxng.")
    return str(value)


@dataclass
class BraveApiClient:
    """Same `search(query, limit)` shape as `SearxngClient`, so the merge,
    early exit, about-page rule and cap in `search.py` are untouched."""

    api_key: str
    config: RetrievalConfig
    brave: BraveApiConfig
    client: httpx.Client
    cache: SearchCache | None = None
    clock: Callable[[], float] = now_seconds
    sleep: Callable[[float], None] = time.sleep
    calls: int = 0
    served_from_cache: int = 0
    _last_request: float = 0.0

    @classmethod
    def create(
        cls,
        api_key: str,
        config: RetrievalConfig,
        brave: BraveApiConfig,
        cache: SearchCache | None = None,
    ) -> "BraveApiClient":
        return cls(
            api_key=api_key,
            config=config,
            brave=brave,
            cache=cache,
            client=httpx.Client(
                timeout=httpx.Timeout(
                    connect=config.connect_timeout_s,
                    read=config.read_timeout_s,
                    write=config.read_timeout_s,
                    pool=config.connect_timeout_s,
                )
            ),
        )

    def close(self) -> None:
        self.client.close()

    def status_line(self) -> str:
        return (
            f"search backend: Brave Search API — {self.calls} paid call(s) this run, "
            f"{self.served_from_cache} answered from the harvested cache "
            f"(cap {self.brave.max_calls_per_run}/run)"
        )

    def _cached(self, text: str, now: float) -> list[SearchResult] | None:
        """Any harvested answer to this exact query: a non-empty one first,
        else an empty one (asked before, nothing found — not worth a credit)."""
        if self.cache is None:
            return None
        empty_seen = False
        for engine in (ENGINE, *self.config.engines):
            hit = self.cache.get(text, (engine,), now)
            if hit:
                return hit
            if hit is not None:
                empty_seen = True
        return [] if empty_seen else None

    def search(self, query: SearchQuery, limit: int) -> list[SearchResult]:
        now = self.clock()
        cached = self._cached(query.text, now)
        if cached is not None:
            self.served_from_cache += 1
            return cached[:limit]
        if self.calls >= self.brave.max_calls_per_run:
            raise SearchError(
                f"Brave API call cap reached ({self.brave.max_calls_per_run} this run; "
                f"`brave_api.max_calls_per_run` in config/retrieval.yaml). The credits are "
                f"paid, so this stops rather than spending more."
            )
        results = self._request(query, limit)
        if self.cache is not None:
            self.cache.put(query.text, (ENGINE,), results, now)
        return results

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.brave.min_interval_s:
            self.sleep(self.brave.min_interval_s - elapsed)
        self._last_request = time.monotonic()

    def _request(self, query: SearchQuery, limit: int) -> list[SearchResult]:
        params = {
            "q": query.text[: self.brave.max_query_chars],
            "count": str(min(limit, 20)),
            "country": self.brave.country,
        }
        headers = {"Accept": "application/json", "X-Subscription-Token": self.api_key}
        last_error: str = ""
        for attempt in range(self.config.max_retries + 1):
            self._throttle()
            self.calls += 1
            try:
                response = self.client.get(self.brave.endpoint, params=params, headers=headers)
            except httpx.TimeoutException as error:
                last_error = f"timeout: {error}"
            except httpx.HTTPError as error:
                raise SearchError(
                    f"cannot reach the Brave Search API ({type(error).__name__}: {error}). "
                    f"Behind a corporate proxy, try NIMO_SYSTEM_CERTS=1 in .env; check with "
                    f"`uv run python -m nimo.retrieval --ping`."
                ) from error
            else:
                if response.status_code == 200:
                    return _results_of(response, limit)
                if response.status_code in (401, 403):
                    raise SearchError(
                        f"Brave API refused the key (HTTP {response.status_code}) — check "
                        f"BRAVE_API_KEY in .env."
                    )
                if response.status_code == 402:
                    raise SearchError("Brave API: no credit left on this key (HTTP 402).")
                if response.status_code not in _RETRYABLE_STATUS:
                    raise SearchError(
                        f"Brave API HTTP {response.status_code} for {query.strategy}: "
                        f"{response.text[:200]}"
                    )
                last_error = f"HTTP {response.status_code}"
            if attempt < self.config.max_retries:
                ceiling = min(self.config.backoff_base_s * (2**attempt), self.config.backoff_max_s)
                delay = random.uniform(0, ceiling)  # noqa: S311 — jitter, not cryptography
                log.warning("brave_retry", strategy=query.strategy, attempt=attempt + 1)
                self.sleep(delay)
        raise SearchError(
            f"Brave API failed after {self.config.max_retries} retries for "
            f"{query.strategy}: {last_error}"
        )


def _results_of(response: httpx.Response, limit: int) -> list[SearchResult]:
    try:
        payload = response.json()
    except ValueError as error:
        raise SearchError(f"Brave API returned non-JSON: {error}") from error
    web = payload.get("web") if isinstance(payload, dict) else None
    items = web.get("results", []) if isinstance(web, dict) else []
    results: list[SearchResult] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        title = item.get("title")
        results.append(
            SearchResult(
                url=item["url"],
                engine=ENGINE,
                rank=len(results) + 1,
                title=title if isinstance(title, str) else None,
            )
        )
        if len(results) >= limit:
            break
    return results
