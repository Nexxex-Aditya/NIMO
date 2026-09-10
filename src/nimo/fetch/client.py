"""The fetcher — `03` §4 stage 3, `05` §2, `04` §6.

**Redirects are followed manually, one hop at a time.** `httpx` would follow
them for us, but `05` §2 requires re-validating after *every* hop — "a page
can return a 302 to an internal address; checking only the candidate URL and
trusting the redirect chain defeats the whole control" — and an automatic
follow gives no place to run that check. The extra code is the control.

**The size cap is enforced while streaming**, for the same reason: `05` §2
calls an unbounded or slow-drip response a resource-exhaustion vector, and a
cap applied after download has already paid the cost it exists to avoid.
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
import structlog

from nimo.extract.page import FetchStatus
from nimo.fetch.cache import CachedPage, PageCache
from nimo.fetch.config import FetchConfig
from nimo.fetch.guard import UnsafeUrlError, assert_safe_url
from nimo.fetch.robots import RobotsCache

log = structlog.get_logger(__name__)

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class FetchOutcome:
    """What one fetch produced. Raw — turning this into `CandidateEvidence` is
    `nimo.extract`'s job, which keeps parsing testable without a network layer
    and the network testable without a parser."""

    url: str
    final_url: str
    status: FetchStatus
    http_status: int | None
    html: str
    from_cache: bool
    detail: str | None = None


@dataclass
class Fetcher:
    """One HTTP wrapper for page fetching (`04` §6).

    Not frozen: per-host timing and the per-domain outcome counters are
    mutable state. Everything injected is not.
    """

    config: FetchConfig
    client: httpx.Client
    robots: RobotsCache
    cache: PageCache | None = None
    clock: Callable[[], float] = time.time
    _last_request: dict[str, float] = field(default_factory=dict)
    _domain_outcomes: dict[str, dict[str, int]] = field(default_factory=dict)
    # Where `_attempt` leaves a redirect target for `_fetch_with_redirects`.
    # A field rather than a bare class attribute so each Fetcher owns its own.
    _pending_redirect: str | None = None

    @classmethod
    def create(cls, config: FetchConfig, cache: PageCache | None = None) -> "Fetcher":
        client = httpx.Client(
            timeout=httpx.Timeout(
                connect=config.connect_timeout_s,
                read=config.read_timeout_s,
                write=config.read_timeout_s,
                pool=config.connect_timeout_s,
            ),
            headers={"User-Agent": config.user_agent},
            follow_redirects=False,  # `05` §2 — see the module docstring
        )
        return cls(
            config=config,
            client=client,
            robots=RobotsCache(
                fetch=lambda url: _fetch_robots(client, url),
                user_agent=config.user_agent,
            ),
            cache=cache,
        )

    def close(self) -> None:
        self.client.close()

    # --- politeness ---------------------------------------------------------

    def _throttle(self, url: str) -> None:
        """Space requests per HOST, not globally. A global limiter would make
        a crawl across twenty domains twenty times slower than politeness to
        any one of them requires."""
        host = urlsplit(url).netloc
        interval = self.config.min_interval_s
        asked = self.robots.crawl_delay(url)
        if asked is not None and asked > interval:
            # A site asking for more space gets it. A site asking for less
            # does not speed us up — `min_interval_s` is our floor, not a target.
            interval = asked
        elapsed = self.clock() - self._last_request.get(host, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request[host] = self.clock()

    def _record(self, url: str, status: FetchStatus) -> None:
        """Per-domain outcome counts.

        `05` §5's aggregate domain block: "each fetch fails loud individually,
        but the systemic pattern — 'Boots recall just dropped to 0%' — is
        invisible without looking across rows." Measured, 4 of 10 retailers
        are bot walls, so this is the number that says which.
        """
        host = urlsplit(url).netloc
        counts = self._domain_outcomes.setdefault(host, {})
        counts[status] = counts.get(status, 0) + 1

    @property
    def domain_outcomes(self) -> dict[str, dict[str, int]]:
        return {host: dict(counts) for host, counts in self._domain_outcomes.items()}

    # --- fetching -----------------------------------------------------------

    def fetch(self, url: str) -> FetchOutcome:
        """Fetch one candidate URL. Never raises for a per-page problem.

        Every failure mode becomes a `FetchOutcome` with a `status`, because
        `03` §4 stage 3 is explicit that a page which fails "gets
        `fetch_status` set and stays in the record. Do not drop it — a
        systematic block on one retailer is a finding, not noise."
        """
        now = self.clock()

        if self.cache is not None:
            cached = self.cache.get(url, now)
            if cached is not None:
                return FetchOutcome(
                    url=url,
                    final_url=cached.final_url,
                    status=cached.status,
                    http_status=cached.http_status,
                    html=cached.html,
                    from_cache=True,
                )

        try:
            assert_safe_url(url)
        except UnsafeUrlError as error:
            return self._finish(url, url, "blocked", None, "", now, detail=str(error))

        if self.config.respect_robots and not self.robots.allowed(url):
            return self._finish(
                url, url, "blocked", None, "", now, detail="disallowed by robots.txt"
            )

        return self._fetch_with_redirects(url, now)

    def _fetch_with_redirects(self, url: str, now: float) -> FetchOutcome:
        current = url
        for hop in range(self.config.max_redirects + 1):
            outcome = self._attempt(url, current, now)
            if outcome is not None:
                return outcome

            # `_attempt` returns None only for a redirect, having stashed the
            # target on `self._pending_redirect`.
            target = self._pending_redirect
            if target is None:  # pragma: no cover — defensive
                return self._finish(url, current, "http_error", None, "", now, "empty redirect")
            try:
                assert_safe_url(target)  # `05` §2: EVERY hop, not just the first
            except UnsafeUrlError as error:
                return self._finish(
                    url,
                    target,
                    "blocked",
                    None,
                    "",
                    now,
                    detail=f"redirect hop {hop + 1} refused: {error}",
                )
            current = target

        return self._finish(
            url,
            current,
            "http_error",
            None,
            "",
            now,
            detail=f"more than {self.config.max_redirects} redirects",
        )

    def _attempt(self, original: str, url: str, now: float) -> FetchOutcome | None:
        """One request, with retries. `None` means "this was a redirect"."""
        last_detail = ""
        for attempt in range(self.config.max_retries + 1):
            self._throttle(url)
            try:
                with self.client.stream("GET", url) as response:
                    if response.status_code in _REDIRECT_STATUS:
                        location = response.headers.get("location")
                        self._pending_redirect = urljoin(url, location) if location else None
                        return None

                    if response.status_code in _RETRYABLE_STATUS:
                        last_detail = f"HTTP {response.status_code}"
                    elif response.is_error:
                        # 404/403 are never retried — they fail identically
                        # every time, and retrying a bot wall three times is
                        # three times the rudeness for the same answer.
                        body = self._read_capped(response)
                        status: FetchStatus = (
                            "blocked" if response.status_code in (401, 403, 429) else "http_error"
                        )
                        return self._finish(
                            original,
                            str(response.url),
                            status,
                            response.status_code,
                            body,
                            now,
                            detail=f"HTTP {response.status_code}, not retried",
                        )
                    else:
                        body = self._read_capped(response)
                        return self._finish(
                            original, str(response.url), "ok", response.status_code, body, now
                        )
            except httpx.TimeoutException as error:
                last_detail = f"timeout: {error}"
            except httpx.HTTPError as error:
                return self._finish(
                    original,
                    url,
                    "http_error",
                    None,
                    "",
                    now,
                    detail=f"{type(error).__name__}: {error}",
                )

            if attempt < self.config.max_retries:
                delay = self._backoff(attempt)
                log.warning("fetch_retry", url=url, attempt=attempt + 1, delay_s=delay)
                time.sleep(delay)

        failure: FetchStatus = "timeout" if "timeout" in last_detail else "http_error"
        return self._finish(original, url, failure, None, "", now, detail=last_detail)

    def _read_capped(self, response: httpx.Response) -> str:
        """Read the body, abandoning it if it exceeds the cap.

        Streamed, so an oversized or slow-drip response costs the cap rather
        than its full length (`05` §2).
        """
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.config.max_response_bytes:
                log.warning(
                    "fetch_size_cap", url=str(response.url), cap=self.config.max_response_bytes
                )
                break
            chunks.append(chunk)
        return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")

    def _backoff(self, attempt: int) -> float:
        ceiling = min(self.config.backoff_base_s * (2**attempt), self.config.backoff_max_s)
        return random.uniform(0, ceiling)  # noqa: S311 — backoff jitter, not cryptography

    def _finish(
        self,
        url: str,
        final_url: str,
        status: FetchStatus,
        http_status: int | None,
        html: str,
        now: float,
        detail: str | None = None,
    ) -> FetchOutcome:
        self._record(url, status)
        if self.cache is not None:
            self.cache.put(
                CachedPage(
                    url=url,
                    final_url=final_url,
                    status=status,
                    http_status=http_status,
                    html=html,
                    fetched_at=now,
                )
            )
        return FetchOutcome(
            url=url,
            final_url=final_url,
            status=status,
            http_status=http_status,
            html=html,
            from_cache=False,
            detail=detail,
        )


def _fetch_robots(client: httpx.Client, url: str) -> str | None:
    """Fetch one robots.txt. `None` means "no rules published", which RFC 9309
    treats as allow — see `RobotsCache`."""
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return None
    if response.is_error:
        return None
    return response.text
