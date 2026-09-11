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
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
import structlog

from nimo.retrieval.breaker import EngineBreaker
from nimo.retrieval.cache import SearchCache, now_seconds
from nimo.retrieval.config import RetrievalConfig
from nimo.retrieval.queries import SearchQuery
from nimo.retrieval.search import SearchResult

log = structlog.get_logger(__name__)

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class SearchError(Exception):
    """The search backend could not be reached or returned something unusable."""


class EnginesUnresponsive(SearchError):
    """Every engine queried in one request was reported unresponsive.

    Its own type so that rotation (`specs/retrieval.md` §5a.7) can move to the
    next engine on exactly this outcome and nothing else — a transport error
    or a malformed body is not something another engine will fix.
    """


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
    breaker: EngineBreaker
    cache: SearchCache | None = None
    # Injected so time-dependent behaviour — cooldowns, cache expiry — is
    # testable without sleeping, and so nothing in this class reads the wall
    # clock inside logic (`04` §5). The runner does the same with its clock.
    clock: Callable[[], float] = now_seconds
    # Injected for the same reason as the clock: waiting out a cooldown is
    # logic that has to be tested without actually sleeping.
    sleep: Callable[[float], None] = time.sleep
    _last_request: float = 0.0
    # Rotation cursor: index into `config.engines` of the engine the next
    # query starts on. `_cooldown_waits` counts consecutive waits for a
    # fully-broken portfolio with no successful query in between — bounded by
    # `max_cooldown_waits`.
    _cursor: int = 0
    _cooldown_waits: int = 0

    @classmethod
    def create(
        cls, base_url: str, config: RetrievalConfig, cache: SearchCache | None = None
    ) -> "SearxngClient":
        return cls(
            base_url=base_url.rstrip("/"),
            config=config,
            breaker=EngineBreaker(
                failure_threshold=config.engine_failure_threshold,
                cooldown_s=config.engine_cooldown_s,
            ),
            cache=cache,
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

        **Cache-first** (`04` §6): a hit issues no request, so it cannot be
        blocked or rate limited. That is most of what makes free engines
        viable as the primary source — a re-run costs nothing, and a run
        interrupted by a block resumes without redoing the half that worked.

        **Only engines whose circuit is closed are queried.** When one
        CAPTCHAs it drops out and the others carry the run; hammering a
        blocked engine wastes the request and extends the block. When *every*
        engine is open, `wait_for_cooldown` decides between raising at once
        and sleeping until the earliest reopens (`specs/retrieval.md` §5a.7).

        **`engine_mode: rotate`** sends the query to one engine, cycling, and
        moves to the next available engine on an unresponsive *or empty*
        answer — an empty index on one engine says nothing about the others,
        and it is the barcode strategies, the most valuable ones, that come
        back empty most often.

        Raising rather than returning an empty list is deliberate (`04` §4):
        empty is a legitimate answer meaning "no results", and collapsing a
        network failure into it would silently degrade recall with nothing to
        find later. The P6a runner turns this into a typed `RowFailure`.
        """
        while True:
            engines, now = self._engines_or_wait(self.clock())
            try:
                return self._search_once(query, engines, limit, now)
            except EnginesUnresponsive as error:
                # Everything asked was unresponsive. If that opened the last
                # circuit and waiting is on, go round: `_engines_or_wait`
                # sleeps until an engine reopens, or raises once the bound is
                # hit. Otherwise it is this row's failure — re-asking engines
                # the breaker still considers available would hammer them.
                if self.config.wait_for_cooldown and not self.breaker.available(
                    self.config.engines, self.clock()
                ):
                    continue
                raise SearchError(
                    f"every engine asked was unresponsive for {query.strategy}: {error}"
                ) from error

    def _search_once(
        self, query: SearchQuery, engines: tuple[str, ...], limit: int, now: float
    ) -> list[SearchResult]:
        """One pass over the available engines, cache-first."""
        if self.config.engine_mode == "portfolio":
            cached = self._cached(query, engines, now)
            if cached is not None:
                return cached[:limit]
            return self._request(query, engines, limit, now)

        # Rotation. Any single engine's cached answer for this query is a
        # hit; a cached EMPTY answer rules that engine out of the live
        # attempts without ruling out the others.
        cached_empty: set[str] = set()
        for engine in self.config.engines:
            hit = self._cached(query, (engine,), now)
            if hit:
                return hit[:limit]
            if hit is not None:
                cached_empty.add(engine)

        attempts = [
            engine
            for engine in self._rotation_order()
            if engine in engines and engine not in cached_empty
        ]
        last_error: EnginesUnresponsive | None = None
        answered = False
        for engine in attempts:
            try:
                results = self._request(query, (engine,), limit, now)
            except EnginesUnresponsive as error:
                last_error = error
                log.warning("searxng_rotate_next", strategy=query.strategy, unresponsive=engine)
                continue
            answered = True
            if results:
                self._cursor = (self.config.engines.index(engine) + 1) % len(self.config.engines)
                return results
            log.info("searxng_rotate_on_empty", strategy=query.strategy, engine=engine)
        if last_error is not None and not answered:
            # Live attempts were made and none of them answered — that is a
            # failure, not an empty result (`04` §4). Typed, so `search` can
            # decide whether to wait out the cooldown or fail the row.
            raise EnginesUnresponsive(
                f"every available engine was unresponsive: {last_error}"
            ) from last_error
        return []

    def _rotation_order(self) -> list[str]:
        """`config.engines` starting at the cursor, wrapping — so the
        assignment is deterministic given the same history."""
        engines = self.config.engines
        return [engines[(self._cursor + offset) % len(engines)] for offset in range(len(engines))]

    def _cached(
        self, query: SearchQuery, engines: tuple[str, ...], now: float
    ) -> list[SearchResult] | None:
        if self.cache is None:
            return None
        return self.cache.get(query.text, engines, now)

    def _engines_or_wait(self, now: float) -> tuple[tuple[str, ...], float]:
        """The available engines, sleeping out a fully-broken portfolio when
        configured to. Returns the (possibly advanced) clock reading too, so
        cache expiry and breaker bookkeeping see the time after the wait."""
        while True:
            engines = tuple(self.breaker.available(self.config.engines, now))
            if engines:
                return engines, now
            blocked = sorted(self.breaker.blocked_engines)
            if not self.config.wait_for_cooldown:
                raise SearchError(
                    f"every engine is circuit-broken: {blocked}. 'No engine answered' and 'no "
                    f"results exist' are different facts and only one is about the product, so "
                    f"this raises rather than returning empty. Wait out the "
                    f"{self.config.engine_cooldown_s:.0f}s cooldown, or add engines."
                )
            if self._cooldown_waits >= self.config.max_cooldown_waits:
                raise SearchError(
                    f"every engine is circuit-broken: {blocked}, and the portfolio produced no "
                    f"successful query across {self._cooldown_waits} consecutive cooldown waits "
                    f"(`max_cooldown_waits`). Stopping rather than waiting further: a portfolio "
                    f"silent for that long is a run to look at, not to keep waiting on."
                )
            reopens = self.breaker.reopens_at(self.config.engines)
            delay = 0.0 if reopens is None else max(0.0, reopens - now)
            self._cooldown_waits += 1
            log.warning(
                "searxng_waiting_for_cooldown",
                delay_s=round(delay, 1),
                wait_number=self._cooldown_waits,
                blocked=blocked,
            )
            self.sleep(delay)
            now = self.clock()

    def _request(
        self, query: SearchQuery, engines: tuple[str, ...], limit: int, now: float
    ) -> list[SearchResult]:
        """One query against one engine set, with retries; caches the answer."""
        params = {"q": query.text, "format": "json", "engines": ",".join(engines)}
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
                # between attempts, and retries only delay the real error.
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
                    results = self._handle_payload(response, engines, limit, now)
                    if self.cache is not None:
                        self.cache.put(query.text, engines, results, now)
                    return results

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

    def _handle_payload(
        self, response: httpx.Response, engines: tuple[str, ...], limit: int, now: float
    ) -> list[SearchResult]:
        """Parse, and feed each engine's outcome to the circuit breaker.

        Fed here rather than inside the parser because this is where the set
        of engines actually queried is known — an engine already cooling down
        must not be recorded as failing again while nobody is asking it.
        """
        payload = _payload_of(response)
        degraded = set(unresponsive_engines(payload))
        for engine in engines:
            if engine in degraded:
                self.breaker.record_failure(engine, now)
            else:
                self.breaker.record_success(engine)
                self._cooldown_waits = 0  # something answered: the wait budget resets

        if degraded and degraded >= set(engines):
            raise EnginesUnresponsive(
                f"every queried engine is unresponsive: {sorted(degraded)}. Results from a "
                f"fully CAPTCHA-blocked instance are not retrieval output and must not be "
                f"scored. Reduce request rate (`min_interval_s`) or wait out the block."
            )
        if degraded:
            log.warning(
                "searxng_engines_unresponsive",
                engines=sorted(degraded),
                still_answering=sorted(set(engines) - degraded),
            )

        results = _results_of(payload, limit)
        _assert_engines_honoured(results, engines)
        return results


def _payload_of(response: httpx.Response) -> Mapping[str, object]:
    """SearxNG's JSON body, or a loud error.

    A malformed payload raises rather than yielding an empty list — "no
    results" and "the backend broke" must stay distinguishable (`04` §4).
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
    return payload


def _results_of(payload: Mapping[str, object], limit: int) -> list[SearchResult]:
    """Rank-ordered results. A malformed entry is skipped, not fatal — one bad
    entry is a bad result, not a broken backend."""
    raw = payload.get("results")
    entries = raw if isinstance(raw, list) else []
    results: list[SearchResult] = []
    for rank, item in enumerate(entries[:limit], start=1):
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


def _assert_engines_honoured(results: list[SearchResult], requested: tuple[str, ...]) -> None:
    """Refuse results from engines that were not asked for.

    **Found the hard way.** `engines=startpage` was passed for days; there is
    no engine called `startpage` in this SearxNG build, and rather than
    erroring, SearxNG **silently fell back to its default engine set** — Bing
    included, which is why Bing's junk survived being "removed" from config.
    An engine probe then scored that fallback set at 91% relevance and
    recorded it as Startpage's. A phantom measurement, made possible by a
    parameter that is ignored without a word.

    Results are tagged with the engine that produced them, so the fallback
    is detectable after the fact. This raises rather than logs: a run whose
    engine set is not the configured one is not comparable to any other run,
    and its cache entries are keyed on an engine set that never answered.
    """
    stray = sorted({r.engine for r in results} - set(requested))
    if stray:
        raise SearchError(
            f"SearxNG returned results from {stray}, which were not requested "
            f"({sorted(requested)}). This means at least one requested engine name is unknown "
            f"to the instance and SearxNG fell back to its defaults. Check the names against "
            f"`GET /config` — engine names are exact, e.g. `google cse`, not `google`."
        )


def unresponsive_engines(payload: Mapping[str, object]) -> list[str]:
    """Engine names SearxNG reported as unresponsive for this query.

    Exposed because a measurement run must be able to refuse to report a
    number taken while engines were blocked — a recall figure measured through
    a CAPTCHA is worse than no figure, since it looks like a retrieval result.
    """
    raw = payload.get("unresponsive_engines")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for entry in raw:
        if isinstance(entry, list | tuple) and entry and isinstance(entry[0], str):
            names.append(entry[0])
        elif isinstance(entry, str):
            names.append(entry)
    return sorted(set(names))
