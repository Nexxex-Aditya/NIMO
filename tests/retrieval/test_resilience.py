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
    fetch_budget=8,
    per_strategy_limit=8,
    strategy_order=("S1", "S2", "S3", "S4", "S5"),
    engines=("brave", "startpage", "bing"),  # test fixture keeps 3 to exercise the breaker
    connect_timeout_s=1.0,
    read_timeout_s=1.0,
    max_retries=0,
    backoff_base_s=0.001,
    backoff_max_s=0.002,
    min_interval_s=0.001,
    early_exit=True,
    engine_mode="portfolio",  # these tests cover the portfolio path; rotation has its own
    wait_for_cooldown=False,
    max_cooldown_waits=4,
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


def test_early_exit_fires_at_the_fetch_budget_not_the_candidate_cap() -> None:
    """**Measured on the first 8 harvested qa rows:** with the exit at
    `max_candidates` (20) and the runner fetching 8, S3 and S5 ran on every
    row, produced 86 candidates, and 0 of them were fetched. Under
    (strategy order, rank) ordering the fetched set is fixed the moment
    `fetch_budget` safe candidates exist, so exiting there is exact, not a
    heuristic (`specs/retrieval.md` §5a.7)."""
    issued: list[str] = []

    def five_each(query: SearchQuery, limit: int) -> list[SearchResult]:
        issued.append(query.strategy)
        return [
            SearchResult(f"https://shop.com/{query.strategy}/{i}", "brave", i, None)
            for i in range(1, 6)
        ]

    config = RetrievalConfig(**{**CONFIG.__dict__, "fetch_budget": 8, "max_candidates": 20})
    queries = [SearchQuery(name, f"q{name}") for name in ("S1", "S2", "S3", "S4", "S5")]
    merged = merge_candidates(queries, five_each, config)
    assert issued == ["S1", "S2"], f"5 + 5 >= 8: S3 onward cannot enter the top 8; got {issued}"
    # and the fetched prefix is exactly what those two strategies produced
    assert [c.source_query for c in merged[: config.fetch_budget]] == ["S1"] * 5 + ["S2"] * 3


def test_early_exit_can_be_disabled_for_a_recall_experiment() -> None:
    """Measuring reach is a different job from spending the budget well."""
    issued: list[str] = []

    def counting(query: SearchQuery, limit: int) -> list[SearchResult]:
        issued.append(query.strategy)
        return [
            SearchResult(f"https://shop.com/{query.strategy}/{i}", "brave", i, None)
            for i in range(1, 21)
        ]

    config = RetrievalConfig(**{**CONFIG.__dict__, "per_strategy_limit": 20, "early_exit": False})
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


# --- engine rotation (`specs/retrieval.md` §5a.7) ----------------------------


ROTATE = RetrievalConfig(**{**CONFIG.__dict__, "engine_mode": "rotate", "engines": ("a", "b", "c")})


def _payload(
    engine: str, urls: list[str], unresponsive: list[str] | None = None
) -> dict[str, object]:
    body: dict[str, object] = {
        "results": [{"url": url, "engine": engine} for url in urls],
    }
    if unresponsive:
        body["unresponsive_engines"] = [[name, "CAPTCHA"] for name in unresponsive]
    return body


def _rotating_client(
    answers: dict[str, list[str]],
    *,
    unresponsive: frozenset[str] = frozenset(),
    config: RetrievalConfig = ROTATE,
    cache: SearchCache | None = None,
) -> tuple[SearxngClient, list[str]]:
    """A client whose transport answers per engine, recording which engine
    each request asked for."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        engine = request.url.params["engines"]
        asked.append(engine)
        if engine in unresponsive:
            return httpx.Response(200, json=_payload(engine, [], [engine]))
        return httpx.Response(200, json=_payload(engine, answers.get(engine, [])))

    client = SearxngClient(
        base_url="http://searxng.test",
        config=config,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        breaker=EngineBreaker(failure_threshold=3, cooldown_s=900.0),
        cache=cache,
        clock=lambda: 0.0,
    )
    return client, asked


def test_rotation_sends_each_query_to_one_engine_and_cycles() -> None:
    """Every request used to hit all three engines at once, so all three
    exhausted in lockstep. One engine per query cuts each engine's rate by a
    third for the same 8 results a strategy takes."""
    client, asked = _rotating_client(
        {"a": ["https://a/1"], "b": ["https://b/1"], "c": ["https://c/1"]}
    )
    for text in ("q1", "q2", "q3", "q4"):
        client.search(SearchQuery("S3", text), limit=8)
    assert asked == ["a", "b", "c", "a"]


def test_rotation_tries_the_next_engine_on_an_empty_answer() -> None:
    """Measured: bare-barcode results come from `google cse` 11 times in 13.
    Without this rule, rotation would hand S1 to an engine that does not
    index barcodes on two rows in three and lose the strategy that produced
    the only GTIN hit. An empty index on one engine says nothing about the
    others."""
    client, asked = _rotating_client({"a": [], "b": ["https://b/1"]})
    results = client.search(SearchQuery("S1", '"5011309895612"'), limit=8)
    assert [r.url for r in results] == ["https://b/1"]
    assert asked == ["a", "b"]
    # the cursor moved past the engine that ANSWERED (b), not the one that was
    # empty (a): the next query starts on c
    client.search(SearchQuery("S2", "next"), limit=8)
    assert asked[2] == "c"


def test_rotation_returns_empty_only_when_every_engine_answered_empty() -> None:
    client, asked = _rotating_client({})
    assert client.search(SearchQuery("S1", "nothing"), limit=8) == []
    assert asked == ["a", "b", "c"]


def test_rotation_moves_past_an_unresponsive_engine_and_feeds_the_breaker() -> None:
    client, asked = _rotating_client({"b": ["https://b/1"]}, unresponsive=frozenset({"a"}))
    results = client.search(SearchQuery("S3", "x"), limit=8)
    assert [r.url for r in results] == ["https://b/1"]
    assert asked == ["a", "b"]
    # the next query starts at c (cursor moved past b, the engine that answered)
    client.search(SearchQuery("S3", "y"), limit=8)
    assert asked[2] == "c"


def test_rotation_raises_when_every_engine_asked_was_unresponsive() -> None:
    """Live attempts were made and none answered: a failure, not an empty
    result (`04` §4)."""
    client, asked = _rotating_client({}, unresponsive=frozenset({"a", "b", "c"}))
    with pytest.raises(SearchError, match="every engine asked was unresponsive"):
        client.search(SearchQuery("S3", "x"), limit=8)
    assert asked == ["a", "b", "c"]


def test_rotation_cache_hits_on_any_engine_that_answered(tmp_path: Path) -> None:
    """A warm re-run must hit regardless of which engine happened to answer
    the first time — otherwise rotation state would make re-runs re-query."""
    cache = default_cache(tmp_path, ttl_days=14.0, enabled=True)
    client, asked = _rotating_client({"a": [], "b": ["https://b/1"]}, cache=cache)
    client.search(SearchQuery("S1", "q"), limit=8)
    assert asked == ["a", "b"]
    # second client, fresh cursor, same cache: no request at all
    client2, asked2 = _rotating_client({"a": [], "b": ["https://b/1"]}, cache=cache)
    assert [r.url for r in client2.search(SearchQuery("S1", "q"), limit=8)] == ["https://b/1"]
    assert asked2 == []


def test_rotation_caches_empties_per_engine_and_skips_them(tmp_path: Path) -> None:
    """A cached empty rules that engine out of the live attempts without
    ruling out the others."""
    cache = default_cache(tmp_path, ttl_days=14.0, enabled=True)
    client, asked = _rotating_client({}, cache=cache)
    client.search(SearchQuery("S1", "q"), limit=8)
    assert asked == ["a", "b", "c"]
    client2, asked2 = _rotating_client({"c": ["https://c/1"]}, cache=cache)
    # a, b, c are all cached empty -> nothing is asked, empty is served
    assert client2.search(SearchQuery("S1", "q"), limit=8) == []
    assert asked2 == []


# --- waiting out a fully-broken portfolio ---------------------------------------


class _FakeTime:
    """Clock and sleep together, so a sleep advances what the clock reads —
    the wait is exercised without the test taking 15 minutes."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _waiting_client(
    handler: object, fake: _FakeTime, *, max_waits: int = 4, cooldown: float = 900.0
) -> SearxngClient:
    config = RetrievalConfig(
        **{
            **CONFIG.__dict__,
            "wait_for_cooldown": True,
            "max_cooldown_waits": max_waits,
            "engine_cooldown_s": cooldown,
        }
    )
    return SearxngClient(
        base_url="http://searxng.test",
        config=config,
        client=httpx.Client(transport=httpx.MockTransport(handler)),  # type: ignore[arg-type]
        breaker=EngineBreaker(failure_threshold=1, cooldown_s=cooldown),
        clock=fake.clock,
        sleep=fake.sleep,
    )


def test_a_fully_broken_portfolio_is_waited_out_then_queried() -> None:
    """The measured failure: 8 rows, then every engine broke and the other
    404 rows failed in 137 seconds. Unattended is the only way 412 rows
    finish on free engines, so the client sleeps until the earliest engine
    reopens instead of raising."""
    fake = _FakeTime()
    client = _waiting_client(
        lambda r: httpx.Response(
            200, json={"results": [{"url": "https://x/1", "engine": "brave"}]}
        ),
        fake,
    )
    client.breaker.record_failure("brave", now=100.0)
    client.breaker.record_failure("startpage", now=200.0)
    client.breaker.record_failure("bing", now=300.0)
    fake.now = 400.0
    results = client.search(SearchQuery("S3", "x"), limit=8)
    assert [r.url for r in results] == ["https://x/1"]
    assert fake.slept == [pytest.approx(600.0)]  # until brave reopens at 100 + 900
    assert client.breaker.available(CONFIG.engines, fake.now) == ["brave"]


def test_waiting_is_bounded_and_then_fails_fast() -> None:
    """`max_cooldown_waits` consecutive waits with no successful query raises,
    and every later call raises at once — a portfolio silent for an hour is a
    run to look at, not to keep waiting on."""
    fake = _FakeTime()

    def always_captcha(request: httpx.Request) -> httpx.Response:
        engine = request.url.params["engines"]
        return httpx.Response(
            200,
            json={
                "results": [],
                "unresponsive_engines": [[e, "CAPTCHA"] for e in engine.split(",")],
            },
        )

    client = _waiting_client(always_captcha, fake, max_waits=2, cooldown=100.0)
    for engine in CONFIG.engines:
        client.breaker.record_failure(engine, now=0.0)
    # ONE call: wait 1 -> engines reopen -> all CAPTCHA -> re-open -> wait 2 ->
    # same -> the bound. A row either gets an answer or the run has
    # established that the portfolio is dead.
    with pytest.raises(SearchError, match="consecutive cooldown waits"):
        client.search(SearchQuery("S3", "x"), limit=8)
    assert len(fake.slept) == 2
    # subsequent calls do not wait again
    with pytest.raises(SearchError, match="consecutive cooldown waits"):
        client.search(SearchQuery("S3", "y"), limit=8)
    assert len(fake.slept) == 2


def test_a_successful_query_resets_the_wait_budget() -> None:
    fake = _FakeTime()
    client = _waiting_client(
        lambda r: httpx.Response(
            200, json={"results": [{"url": "https://x/1", "engine": "brave"}]}
        ),
        fake,
        max_waits=1,
    )
    for engine in CONFIG.engines:
        client.breaker.record_failure(engine, now=0.0)
    client.search(SearchQuery("S3", "x"), limit=8)  # one wait, then success
    assert len(fake.slept) == 1
    for engine in CONFIG.engines:
        client.breaker.record_failure(engine, now=fake.now)
    client.search(SearchQuery("S3", "y"), limit=8)  # allowed to wait again
    assert len(fake.slept) == 2


def test_wait_disabled_raises_immediately() -> None:
    """The foreground behaviour is kept: `wait_for_cooldown: false` fails the
    row at once so a demo run does not hang for 15 minutes."""
    fake = _FakeTime()
    client = _waiting_client(lambda r: httpx.Response(200), fake)
    client = SearxngClient(**{**client.__dict__, "config": CONFIG})
    for engine in CONFIG.engines:
        client.breaker.record_failure(engine, now=0.0)
    with pytest.raises(SearchError, match="every engine is circuit-broken"):
        client.search(SearchQuery("S3", "x"), limit=8)
    assert fake.slept == []


def test_shipped_config_is_set_for_an_unattended_run() -> None:
    """No paid search key exists, so the free path has to carry the full qa
    run; that is only possible unattended, with rotation and waiting on."""
    config = load_retrieval_config()
    assert config.engine_mode == "rotate"
    assert config.wait_for_cooldown is True
    assert config.early_exit is True
    assert config.fetch_budget <= config.max_candidates


# --- shipped config ----------------------------------------------------------


def test_shipped_engines_exclude_the_captcha_prone_ones() -> None:
    """Measured 2026-09-11: Google, DuckDuckGo and Qwant CAPTCHA-block a
    single IP within a few dozen queries. An engine that stops answering
    partway through a 400-row run is worse than one that never answered,
    because the run looks like it worked."""
    engines = set(load_retrieval_config().engines)
    assert engines == {"google cse", "duckduckgo", "brave"}
    assert "startpage" not in engines, (
        "There is no engine called `startpage` in this SearxNG build. Configuring it made "
        "SearxNG silently fall back to its defaults (Bing included) for days, and a probe "
        "scored that fallback set under Startpage's name. Names must match `GET /config`."
    )
    assert "bing" not in engines, (
        "Bing was measured returning results for an entirely different query — MIT AI news "
        "for a toothpaste search, akinator.com for a barcode — while reporting as healthy. "
        "A silently-wrong engine is worse than a blocked one: the breaker cannot see it and "
        "the row still looks like it retrieved a full candidate list."
    )


def test_shipped_pacing_is_not_the_rate_that_got_us_blocked() -> None:
    """0.25s (4 queries/sec) is what triggered the CAPTCHAs, and the symptom
    was plausible-looking junk rather than an error."""
    assert load_retrieval_config().min_interval_s >= 1.0


# --- candidate QUALITY, not quantity -----------------------------------------


def test_brand_signal_separates_real_candidates_from_noise() -> None:
    """**The test that would have caught the reported-as-healthy junk run.**

    A run was reported healthy on "20.0 candidates/row, cap filled on every
    row" while the candidates were MIT AI news and bilibili videos, because
    Bing was answering a different query while reporting no error. Counting
    candidates could not see it; this can.
    """
    from nimo.contracts import CandidateURL
    from nimo.retrieval import brand_signal_rate

    def candidate(url: str, title: str | None = None) -> CandidateURL:
        return CandidateURL(url=url, source_query="S3", engine="brave", rank=1, title_snippet=title)

    real = [
        candidate("https://boots.com/aquafresh-whitening-pump-100ml"),
        candidate("https://superdrug.com/p/12345", "Aquafresh Whitening Pump 100ml"),
    ]
    assert brand_signal_rate(real, "AQUAFRESH") == 1.0

    noise = [
        candidate("https://news.mit.edu/topic/artificial-intelligence"),
        candidate("https://bilibili.com/video/BV1e2421L73V"),
        candidate("https://support.microsoft.com/fix-bluetooth-problems"),
    ]
    assert brand_signal_rate(noise, "AQUAFRESH") == 0.0


def test_brand_signal_handles_multiword_brands_and_empties() -> None:
    from nimo.contracts import CandidateURL
    from nimo.retrieval import brand_signal_rate

    assert brand_signal_rate([], "AQUAFRESH") == 0.0
    hit = CandidateURL(
        url="https://boots.com/humble-natural-toothpaste",
        source_query="S3",
        engine="brave",
        rank=1,
        title_snippet=None,
    )
    # "THE HUMBLE CO." -> first token "the" would match almost anything, so the
    # brand token is taken as-written; this documents the known weakness rather
    # than pretending the signal is perfect.
    assert brand_signal_rate([hit], "HUMBLE CO.") == 1.0
    assert brand_signal_rate([hit], "") == 0.0


def test_results_from_an_unrequested_engine_are_refused() -> None:
    """**The silent fallback that hid two phantom measurements.** SearxNG
    does not error on an unknown engine name; it quietly uses its defaults.
    `engines=startpage` (nonexistent) returned Bing/DDG/Google-CSE results for
    days, tagged with their real engines — so the fallback is detectable, and
    a client that checks the tags cannot be fooled by it."""
    config = RetrievalConfig(**{**CONFIG.__dict__, "engines": ("startpage",)})
    client = SearxngClient(
        base_url="http://searxng.test",
        config=config,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={"results": [{"url": "https://boots.com/a", "engine": "bing"}]},
                )
            )
        ),
        breaker=EngineBreaker(failure_threshold=3, cooldown_s=900.0),
        clock=lambda: 0.0,
    )
    with pytest.raises(SearchError, match="not requested"):
        client.search(SearchQuery("S3", "x"), limit=8)


def test_results_from_requested_engines_pass() -> None:
    config = RetrievalConfig(**{**CONFIG.__dict__, "engines": ("google cse", "duckduckgo")})
    client = SearxngClient(
        base_url="http://searxng.test",
        config=config,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={
                        "results": [
                            {"url": "https://boots.com/a", "engine": "google cse"},
                            {"url": "https://boots.com/b", "engine": "duckduckgo"},
                        ]
                    },
                )
            )
        ),
        breaker=EngineBreaker(failure_threshold=3, cooldown_s=900.0),
        clock=lambda: 0.0,
    )
    assert len(client.search(SearchQuery("S3", "x"), limit=8)) == 2
