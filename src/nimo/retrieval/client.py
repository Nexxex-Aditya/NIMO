"""The SearxNG client — `specs/retrieval.md` §5, `04` §6.

**The only place in `retrieval/` that touches the network.** Everything else in
this package is pure, which is what makes `04` §6's "zero network calls in
tests" achievable rather than aspirational: tests inject a `SearchFn` and never
construct this class.

`03` §4 stage 2: self-hosted, pinned image tag, never a public instance —
public instances rate-limit and are not reproducible.
"""

import random
import time
from dataclasses import dataclass

import httpx
import structlog

from nimo.retrieval.config import RetrievalConfig
from nimo.retrieval.queries import SearchQuery
from nimo.retrieval.search import SearchResult

log = structlog.get_logger(__name__)

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class SearchError(Exception):
    """The search backend could not be reached or returned something unusable."""


@dataclass
class SearxngClient:
    """One HTTP wrapper, per `04` §6: timeouts always set on both halves,
    per-instance rate limiting, exponential backoff with jitter, max 3
    retries, 5xx/timeout only — never a 4xx, which will fail identically on
    every attempt.

    Not frozen: `_last_request` is mutable rate-limiting state. Everything a
    caller passes in is.
    """

    base_url: str
    config: RetrievalConfig
    client: httpx.Client
    _last_request: float = 0.0

    @classmethod
    def create(cls, base_url: str, config: RetrievalConfig) -> "SearxngClient":
        return cls(
            base_url=base_url.rstrip("/"),
            config=config,
            client=httpx.Client(
                timeout=httpx.Timeout(
                    connect=config.connect_timeout_s,
                    read=config.read_timeout_s,
                    write=config.read_timeout_s,
                    pool=config.connect_timeout_s,
                ),
                headers={"User-Agent": "nimo-product-truth-agent/0.1 (hackathon prototype)"},
            ),
        )

    def close(self) -> None:
        self.client.close()

    def _throttle(self) -> None:
        """Space requests out. Too fast and the local instance's upstream
        engines rate-limit it, which surfaces as a retrieval *quality* problem
        rather than a throttling one — the kind of misattribution that costs
        an afternoon."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.config.min_interval_s:
            time.sleep(self.config.min_interval_s - elapsed)
        self._last_request = time.monotonic()

    def _backoff(self, attempt: int) -> float:
        """Exponential with full jitter (`04` §6). Jitter matters even
        single-client: without it every retry after a shared upstream hiccup
        lands at the same instant."""
        ceiling = min(self.config.backoff_base_s * (2**attempt), self.config.backoff_max_s)
        return random.uniform(0, ceiling)  # noqa: S311 — backoff jitter, not cryptography

    def search(self, query: SearchQuery, limit: int) -> list[SearchResult]:
        """Issue one query. Raises `SearchError` after exhausting retries.

        Raising rather than returning `[]` is deliberate (`04` §4): an empty
        list is a legitimate answer meaning "no results", and collapsing a
        network failure into it would silently degrade recall with nothing to
        find later. The P6a runner turns this into a typed `RowFailure`.
        """
        params = {
            "q": query.text,
            "format": "json",
            "engines": ",".join(self.config.engines),
        }
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            self._throttle()
            try:
                response = self.client.get(f"{self.base_url}/search", params=params)
            except httpx.TimeoutException as error:
                last_error = error
            except httpx.HTTPError as error:
                # Transport-level failure (DNS, connection refused). Not
                # retried: a SearxNG that is not running will not start
                # between attempts, and 3 retries just delays the real error.
                raise SearchError(
                    f"cannot reach SearxNG at {self.base_url} — is the instance up? "
                    f"`docker compose up -d searxng`. ({type(error).__name__}: {error})"
                ) from error
            else:
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = SearchError(f"HTTP {response.status_code}")
                elif response.is_error:
                    raise SearchError(
                        f"SearxNG returned HTTP {response.status_code} for {query.strategy}; "
                        f"not retried — a 4xx fails identically on every attempt (`04` §6)."
                    )
                else:
                    return _parse_results(response, limit)

            if attempt < self.config.max_retries:
                delay = self._backoff(attempt)
                log.warning(
                    "searxng_retry", strategy=query.strategy, attempt=attempt + 1, delay_s=delay
                )
                time.sleep(delay)

        raise SearchError(
            f"SearxNG failed after {self.config.max_retries} retries for {query.strategy}: "
            f"{last_error}"
        )


def _parse_results(response: httpx.Response, limit: int) -> list[SearchResult]:
    """Parse SearxNG's JSON into `SearchResult`s, rank-ordered.

    A malformed payload raises rather than yielding an empty list — see
    `search`'s note on why "no results" and "the backend broke" must stay
    distinguishable.
    """
    try:
        payload = response.json()
    except ValueError as error:
        raise SearchError(f"SearxNG response was not JSON: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise SearchError(
            "SearxNG response has no `results` list — check that JSON format is enabled in "
            "`config/searxng/settings.yml` (`search.formats` must include `json`)."
        )

    results: list[SearchResult] = []
    for rank, item in enumerate(payload["results"][:limit], start=1):
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str):
            continue
        title = item.get("title")
        results.append(
            SearchResult(
                url=url,
                engine=str(item.get("engine", "unknown")),
                rank=rank,
                title=title if isinstance(title, str) else None,
            )
        )
    return results
