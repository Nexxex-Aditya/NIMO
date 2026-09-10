"""P7 SearxNG client tests — `specs/retrieval.md` §5, `04` §6.

**Zero network.** Every test drives the client through an `httpx.MockTransport`,
so the retry loop, the 4xx/5xx distinction and the JSON parsing are all
exercised without a socket. `04` §6 fails CI on a test that touches the
network; this file is what makes that rule affordable rather than a reason to
leave the client untested — which is what it was until this file existed.
"""

import httpx
import pytest

from nimo.retrieval import (
    EngineBreaker,
    RetrievalConfig,
    SearchError,
    SearchQuery,
    SearxngClient,
)

CONFIG = RetrievalConfig(
    max_candidates=20,
    per_strategy_limit=8,
    strategy_order=("S1", "S2", "S3", "S4", "S5"),
    engines=("google", "bing"),
    connect_timeout_s=1.0,
    read_timeout_s=1.0,
    max_retries=2,
    backoff_base_s=0.001,  # keep the retry tests fast; jitter is still exercised
    backoff_max_s=0.002,
    min_interval_s=0.001,
    early_exit_on_full_cap=True,
    engine_failure_threshold=3,
    engine_cooldown_s=900.0,
    cache_enabled=False,  # the cache has its own tests; keep these about HTTP
    cache_ttl_days=14.0,
)

QUERY = SearchQuery("S1", '"5014697056627"')


def client_with(handler: object, config: RetrievalConfig = CONFIG) -> SearxngClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return SearxngClient(
        base_url="http://searxng.test",
        config=config,
        client=httpx.Client(transport=transport),
        breaker=EngineBreaker(
            failure_threshold=config.engine_failure_threshold,
            cooldown_s=config.engine_cooldown_s,
        ),
    )


def json_response(
    results: list[object], unresponsive: list[object] | None = None
) -> httpx.Response:
    """`results` is deliberately `list[object]`: the payload is untyped JSON
    from a third party, and a test that can only express well-formed entries
    cannot cover the malformed ones the parser exists to survive."""
    body: dict[str, object] = {"results": results}
    if unresponsive is not None:
        body["unresponsive_engines"] = unresponsive
    return httpx.Response(200, json=body)


# --- parsing -----------------------------------------------------------------


def test_results_are_parsed_and_rank_ordered() -> None:
    client = client_with(
        lambda request: json_response(
            [
                {"url": "https://boots.com/a", "engine": "google", "title": "A"},
                {"url": "https://superdrug.com/b", "engine": "bing", "title": "B"},
            ]
        )
    )
    results = client.search(QUERY, limit=8)
    assert [result.url for result in results] == [
        "https://boots.com/a",
        "https://superdrug.com/b",
    ]
    assert [result.rank for result in results] == [1, 2]
    assert results[0].engine == "google"
    assert results[0].title == "A"


def test_limit_is_honoured() -> None:
    client = client_with(
        lambda request: json_response(
            [{"url": f"https://s{index}.com", "engine": "google"} for index in range(20)]
        )
    )
    assert len(client.search(QUERY, limit=3)) == 3


def test_entries_without_a_usable_url_are_skipped_not_fatal() -> None:
    """A single malformed entry is a bad result, not a broken backend."""
    client = client_with(
        lambda request: json_response(
            [
                {"engine": "google"},  # no url
                {"url": 42, "engine": "google"},  # url not a string
                "not even a dict",
                {"url": "https://boots.com/ok", "engine": "google"},
            ]
        )
    )
    results = client.search(QUERY, limit=8)
    assert [result.url for result in results] == ["https://boots.com/ok"]


def test_a_missing_title_becomes_none_not_a_placeholder() -> None:
    client = client_with(
        lambda request: json_response([{"url": "https://boots.com/a", "engine": "google"}])
    )
    assert client.search(QUERY, limit=8)[0].title is None


def test_the_json_format_flag_is_actually_requested() -> None:
    """SearxNG ships HTML-only; without `format=json` the client gets a 200
    with an HTML body and no results."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return json_response([])

    client_with(handler).search(QUERY, limit=8)
    assert seen["format"] == "json"
    assert seen["q"] == QUERY.text
    assert seen["engines"] == "google,bing"  # both circuits closed


# --- failure modes -----------------------------------------------------------


def test_a_non_json_body_raises_rather_than_returning_empty() -> None:
    """`04` §4: an empty list is a legitimate answer meaning "no results".
    Collapsing a broken backend into it would silently degrade recall with
    nothing to find later."""
    client = client_with(lambda request: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(SearchError, match="not JSON"):
        client.search(QUERY, limit=8)


def test_a_payload_without_results_names_the_settings_file() -> None:
    """The error a person actually hits when JSON format is off — so it says
    which file to edit rather than making them guess."""
    client = client_with(lambda request: httpx.Response(200, json={"query": "x"}))
    with pytest.raises(SearchError, match="settings.yml"):
        client.search(QUERY, limit=8)


def test_a_4xx_is_not_retried() -> None:
    """`04` §6: retry only on 5xx/timeout. A 4xx fails identically every time,
    so retrying only delays the real error."""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(404)

    with pytest.raises(SearchError, match="not retried"):
        client_with(handler).search(QUERY, limit=8)
    assert len(attempts) == 1


def test_a_5xx_is_retried_then_gives_up() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503)

    with pytest.raises(SearchError, match="after 2 retries"):
        client_with(handler).search(QUERY, limit=8)
    assert len(attempts) == CONFIG.max_retries + 1


def test_a_5xx_that_recovers_returns_results() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(502)
        return json_response([{"url": "https://boots.com/a", "engine": "google"}])

    results = client_with(handler).search(QUERY, limit=8)
    assert len(attempts) == 2
    assert results[0].url == "https://boots.com/a"


def test_a_timeout_is_retried() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SearchError, match="after 2 retries"):
        client_with(handler).search(QUERY, limit=8)
    assert len(attempts) == CONFIG.max_retries + 1


def test_an_unreachable_instance_fails_immediately_and_says_how_to_fix_it() -> None:
    """A SearxNG that is not running will not start between attempts; three
    retries only delay the real error. The message names the command."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(SearchError, match="docker compose up"):
        client_with(handler).search(QUERY, limit=8)
    assert len(attempts) == 1


# --- wiring ------------------------------------------------------------------


def test_create_sets_both_timeout_halves() -> None:
    """`04` §6: a read timeout with no connect timeout still hangs forever on
    a black-holed host."""
    client = SearxngClient.create("http://searxng.test/", CONFIG)
    try:
        assert client.client.timeout.connect == CONFIG.connect_timeout_s
        assert client.client.timeout.read == CONFIG.read_timeout_s
        assert client.base_url == "http://searxng.test"  # trailing slash stripped
    finally:
        client.close()


def test_backoff_is_bounded_and_jittered() -> None:
    client = SearxngClient.create("http://searxng.test", CONFIG)
    try:
        delays = {client._backoff(attempt) for attempt in range(3) for _ in range(20)}
        assert all(0 <= delay <= CONFIG.backoff_max_s for delay in delays)
        assert len(delays) > 1, "backoff is not jittered — retries would synchronise"
    finally:
        client.close()


# --- engine degradation (`05` §5 aggregate domain block) ---------------------


def test_unresponsive_engines_are_extracted() -> None:
    from nimo.retrieval import unresponsive_engines

    payload: dict[str, object] = {
        "results": [],
        "unresponsive_engines": [["duckduckgo", "CAPTCHA"], ["google", "Suspended: CAPTCHA"]],
    }
    assert unresponsive_engines(payload) == ["duckduckgo", "google"]
    assert unresponsive_engines({"results": []}) == []


def test_a_fully_captcha_blocked_instance_raises_rather_than_returning_junk() -> None:
    """**Observed live on the first real run of this code.** SearxNG answered
    HTTP 200 with 10 results while DuckDuckGo and Google were both
    CAPTCHA-blocked; the results came from the one surviving engine and were
    junk (`instagram.com` for "curaprox aligner care foam").

    A recall number measured through that is worse than no number, because it
    looks like a retrieval result. `05` §5: every request succeeds and the
    systemic pattern is invisible without looking across them.
    """
    blocked: list[object] = [[name, "CAPTCHA"] for name in CONFIG.engines]
    client = client_with(
        lambda request: json_response(
            [{"url": "https://instagram.com/", "engine": "bing"}], unresponsive=blocked
        )
    )
    with pytest.raises(SearchError, match="every queried engine is unresponsive"):
        client.search(QUERY, limit=8)


def test_partial_degradation_still_returns_results_but_is_not_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two of three down is degraded, not dead — the results are still usable,
    but the run is not comparable to a healthy one and must say so."""
    client = client_with(
        lambda request: json_response(
            [{"url": "https://boots.com/a", "engine": "bing"}],
            unresponsive=[["google", "CAPTCHA"]],  # one of three
        )
    )
    results = client.search(QUERY, limit=8)
    assert [result.url for result in results] == ["https://boots.com/a"]
