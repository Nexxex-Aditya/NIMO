"""P7 resilience tests — circuit breaker, cache, early exit.

These three are what make free search engines viable as the *primary* source
rather than a gamble, so they are tested as behaviour, not as plumbing.

Zero network (`04` §6): the breaker takes injected time, the cache takes a
temp directory, and the client is driven through `httpx.MockTransport`.
"""

from pathlib import Path

import httpx
import pytest

from nimo.retrieval import (
    EngineBreaker,
    RetrievalConfig,
    SearchCache,
    SearchError,
    SearchQuery,
    SearchResult,
    SearxngClient,
    cache_key,
    default_cache,
    load_retrieval_config,
    merge_candidates,
)

CONFIG = RetrievalConfig(
    max_candidates=20,
    per_strategy_limit=8,
    strategy_order=("S1", "S2", "S3", "S4", "S5"),
    engines=("brave", "startpage", "bing"),
    connect_timeout_s=1.0,
    read_timeout_s=1.0,
    max_retries=0,
    backoff_base_s=0.001,
    backoff_max_s=0.002,
    min_interval_s=0.001,
    early_exit_on_full_cap=True,
    engine_failure_threshold=3,
    engine_cooldown_s=900.0,
    cache_enabled=True,
    cache_ttl_days=14.0,
)


# --- circuit breaker ---------------------------------------------------------


def test_an_engine_opens_only_after_consecutive_failures() -> None:
    breaker = EngineBreaker(failure_threshold=3, cooldown_s=900.0)
    for _ in range(2):
        breaker.record_failure("brave", now=0.0)
    assert not breaker.is_open("brave", now=0.0)
    breaker.record_failure("brave", now=0.0)
    assert breaker.is_open("brave", now=0.0)


def test_a_success_clears_the_streak() -> None:
    """The threshold is *consecutive* failures. An engine that fails twice,
    answers, then fails twice more is flaky, not blocked."""
    breaker = EngineBreaker(failure_threshold=3, cooldown_s=900.0)
    breaker.record_failure("brave", now=0.0)
    breaker.record_failure("brave", now=0.0)
    breaker.record_success("brave")
    breaker.record_failure("brave", now=0.0)
    breaker.record_failure("brave", now=0.0)
    assert not breaker.is_open("brave", now=0.0)


def test_the_circuit_closes_again_after_the_cooldown() -> None:
    """A CAPTCHA means "come back later", not "never" — the block lapses."""
    breaker = EngineBreaker(failure_threshold=1, cooldown_s=900.0)
    breaker.record_failure("brave", now=1000.0)
    assert breaker.is_open("brave", now=1000.0)
    assert breaker.is_open("brave", now=1800.0)
    assert not breaker.is_open("brave", now=1900.0)


def test_a_recovered_engine_gets_a_fresh_streak() -> None:
    """Half-open: one failure straight after recovery must not immediately
    re-open a circuit whose threshold is 3."""
    breaker = EngineBreaker(failure_threshold=3, cooldown_s=100.0)
    for _ in range(3):
        breaker.record_failure("brave", now=0.0)
    assert not breaker.is_open("brave", now=200.0)  # cooldown elapsed
    breaker.record_failure("brave", now=200.0)
    assert not breaker.is_open("brave", now=200.0)


def test_the_portfolio_keeps_going_when_one_engine_drops() -> None:
    """**The measured scenario.** Brave began CAPTCHA-ing after ~6 live
    queries while Startpage and Bing kept answering; the run kept producing
    candidates. That behaviour is the whole reason for a portfolio."""
    breaker = EngineBreaker(failure_threshold=1, cooldown_s=900.0)
    breaker.record_failure("brave", now=0.0)
    assert breaker.available(CONFIG.engines, now=0.0) == ["startpage", "bing"]


def test_blocked_engines_are_counted_for_the_run_summary() -> None:
    """`05` §5 wants the systemic pattern visible, not just per-request logs —
    a run that quietly finished on one engine is the thing to catch."""
    breaker = EngineBreaker(failure_threshold=1, cooldown_s=900.0)
    breaker.record_failure("brave", now=0.0)
    breaker.record_failure("bing", now=0.0)
    assert breaker.blocked_engines == {"brave": 1, "bing": 1}


def test_all_engines_down_raises_rather_than_returning_empty() -> None:
    """'No engine answered' and 'no results exist' are different facts and
    only one of them is about the product (`04` §4)."""
    client = SearxngClient(
        base_url="http://searxng.test",
        config=CONFIG,
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        breaker=EngineBreaker(failure_threshold=1, cooldown_s=900.0),
        clock=lambda: 0.0,
    )
    for engine in CONFIG.engines:
        client.breaker.record_failure(engine, now=0.0)
    with pytest.raises(SearchError, match="every engine is circuit-broken"):
        client.search(SearchQuery("S3", "x"), limit=8)


def test_a_captcha_response_feeds_the_breaker() -> None:
    """End to end: the payload SearxNG actually returns while blocked must
    move the breaker, not just log."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://boots.com/a", "engine": "bing"}],
                "unresponsive_engines": [["brave", "CAPTCHA"]],
            },
        )

    client = SearxngClient(
        base_url="http://searxng.test",
        config=CONFIG,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        breaker=EngineBreaker(failure_threshold=2, cooldown_s=900.0),
        clock=lambda: 0.0,
    )
    client.search(SearchQuery("S3", "x"), limit=8)
    client.search(SearchQuery("S3", "y"), limit=8)
    assert client.breaker.is_open("brave", now=0.0)
    assert "startpage" in client.breaker.available(CONFIG.engines, now=0.0)


# --- cache -------------------------------------------------------------------


def test_cache_round_trips(tmp_path: Path) -> None:
    cache = default_cache(tmp_path, ttl_days=14.0, enabled=True)
    results = [SearchResult("https://boots.com/a", "brave", 1, "A")]
    cache.put("q", ("brave",), results, now=1000.0)
    assert cache.get("q", ("brave",), now=1000.0) == results


def test_a_cache_hit_is_scoped_to_the_engine_set(tmp_path: Path) -> None:
    """The same query against different engines is a different question.
    Serving one for the other would make a degraded run look like a healthy
    cached one."""
    cache = default_cache(tmp_path, ttl_days=14.0, enabled=True)
    cache.put("q", ("brave",), [SearchResult("https://a.com", "brave", 1, None)], now=0.0)
    assert cache.get("q", ("bing",), now=0.0) is None
    assert cache_key("q", ("brave",)) != cache_key("q", ("bing",))


def test_engine_order_does_not_change_the_key(tmp_path: Path) -> None:
    assert cache_key("q", ("brave", "bing")) == cache_key("q", ("bing", "brave"))


def test_an_expired_entry_is_not_served(tmp_path: Path) -> None:
    """`05` §5 forbids an infinite TTL — "serves stale content forever, no
    error" is the failure mode."""
    cache = default_cache(tmp_path, ttl_days=1.0, enabled=True)
    cache.put("q", ("brave",), [SearchResult("https://a.com", "brave", 1, None)], now=0.0)
    assert cache.get("q", ("brave",), now=86400.0 - 1) is not None
    assert cache.get("q", ("brave",), now=86400.0 + 1) is None


def test_a_disabled_cache_stores_and_returns_nothing(tmp_path: Path) -> None:
    cache = default_cache(tmp_path, ttl_days=14.0, enabled=False)
    cache.put("q", ("brave",), [SearchResult("https://a.com", "brave", 1, None)], now=0.0)
    assert cache.get("q", ("brave",), now=0.0) is None


def test_a_cache_hit_issues_no_request(tmp_path: Path) -> None:
    """`04` §6: "A cache hit must not issue a request." This is what makes a
    re-run free and therefore unblockable."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            200, json={"results": [{"url": "https://boots.com/a", "engine": "brave"}]}
        )

    cache = default_cache(tmp_path, ttl_days=14.0, enabled=True)
    client = SearxngClient(
        base_url="http://searxng.test",
        config=CONFIG,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        breaker=EngineBreaker(failure_threshold=3, cooldown_s=900.0),
        cache=cache,
    )
    query = SearchQuery("S3", "aquafresh whitening 100ml")
    first = client.search(query, limit=8)
    second = client.search(query, limit=8)
    assert first == second
    assert len(calls) == 1, "second search hit the network despite a warm cache"


def test_a_corrupt_cache_entry_raises_rather_than_being_ignored(tmp_path: Path) -> None:
    """A cache that quietly drops entries looks identical to one that works."""
    from nimo.retrieval import CacheError

    cache = SearchCache(directory=tmp_path, ttl_s=1000.0, enabled=True)
    key = cache_key("q", ("brave",))
    path = tmp_path / key[:2] / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CacheError, match="not readable as a cache entry"):
        cache.get("q", ("brave",), now=0.0)


# --- early exit --------------------------------------------------------------


def fake_search(per_query: int) -> object:
    def search(query: SearchQuery, limit: int) -> list[SearchResult]:
        return [
            SearchResult(f"https://shop.com/{query.strategy}/{index}", "brave", index, None)
            for index in range(1, per_query + 1)
        ]

    return search


def test_early_exit_stops_once_the_cap_is_full() -> None:
    """**The single largest lever on query budget.** Measured, one strategy
    against the engine portfolio returns 7-30 unique candidates, so the cap is
    usually met by the first — taking qa from ~1904 queries to ~412."""
    issued: list[str] = []

    def counting(query: SearchQuery, limit: int) -> list[SearchResult]:
        issued.append(query.strategy)
        return [
            SearchResult(f"https://shop.com/{query.strategy}/{i}", "brave", i, None)
            for i in range(1, 21)
        ]

    config = RetrievalConfig(**{**CONFIG.__dict__, "per_strategy_limit": 20})
    queries = [SearchQuery(name, f"q{name}") for name in ("S1", "S2", "S3", "S4", "S5")]
    merge_candidates(queries, counting, config)
    assert issued == ["S1"], f"expected early exit after S1, issued {issued}"


def test_early_exit_can_be_disabled_for_a_recall_experiment() -> None:
    """Measuring reach is a different job from spending the budget well."""
    issued: list[str] = []

    def counting(query: SearchQuery, limit: int) -> list[SearchResult]:
        issued.append(query.strategy)
        return [
            SearchResult(f"https://shop.com/{query.strategy}/{i}", "brave", i, None)
            for i in range(1, 21)
        ]

    config = RetrievalConfig(
        **{**CONFIG.__dict__, "per_strategy_limit": 20, "early_exit_on_full_cap": False}
    )
    merge_candidates(
        [SearchQuery(name, f"q{name}") for name in ("S1", "S2", "S3")], counting, config
    )
    assert issued == ["S1", "S2", "S3"]


def test_early_exit_does_not_stop_before_the_cap_is_reached() -> None:
    issued: list[str] = []

    def counting(query: SearchQuery, limit: int) -> list[SearchResult]:
        issued.append(query.strategy)
        return [SearchResult(f"https://shop.com/{query.strategy}/1", "brave", 1, None)]

    merge_candidates(
        [SearchQuery(name, f"q{name}") for name in ("S1", "S2", "S3")], counting, CONFIG
    )
    assert issued == ["S1", "S2", "S3"]


# --- shipped config ----------------------------------------------------------


def test_shipped_engines_exclude_the_captcha_prone_ones() -> None:
    """Measured 2026-09-11: Google, DuckDuckGo and Qwant CAPTCHA-block a
    single IP within a few dozen queries. An engine that stops answering
    partway through a 400-row run is worse than one that never answered,
    because the run looks like it worked."""
    engines = set(load_retrieval_config().engines)
    assert engines == {"brave", "startpage", "bing"}
    assert not engines & {"google", "duckduckgo", "qwant"}


def test_shipped_pacing_is_not_the_rate_that_got_us_blocked() -> None:
    """0.25s (4 queries/sec) is what triggered the CAPTCHAs, and the symptom
    was plausible-looking junk rather than an error."""
    assert load_retrieval_config().min_interval_s >= 1.0
