"""The Brave Search API backend (`src/nimo/retrieval/brave.py`): cache-first
over everything the free portfolio harvested, a paid call only on a true
miss, a cap per run, typed failures. Zero network — `httpx.MockTransport`."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from nimo.retrieval import (
    BraveApiClient,
    BraveApiConfig,
    SearchCache,
    SearchError,
    SearchQuery,
    SearchResult,
    load_brave_config,
    load_retrieval_config,
    search_backend,
)

CONFIG = load_retrieval_config()
BRAVE = BraveApiConfig(
    endpoint="https://api.search.brave.com/res/v1/web/search",
    country="GB",
    min_interval_s=0.0,
    max_calls_per_run=3,
    max_query_chars=400,
)
PAYLOAD = {
    "type": "search",
    "web": {
        "results": [
            {"url": "https://boots.com/aquafresh-pump-100ml", "title": "Aquafresh Pump 100ml"},
            {"url": "https://superdrug.com/aquafresh/p/1", "title": "Aquafresh | Superdrug"},
            {"title": "no url — skipped"},
        ]
    },
}


def client(tmp_path: Path, handler: httpx.MockTransport) -> BraveApiClient:
    return replace(
        BraveApiClient.create(
            "test-key", CONFIG, BRAVE, cache=SearchCache(tmp_path, 1e9, enabled=True)
        ),
        client=httpx.Client(transport=handler),
        clock=lambda: 1000.0,
        sleep=lambda _s: None,
    )


def test_a_harvested_answer_is_served_without_a_paid_call(tmp_path: Path) -> None:
    """The 412 qa rows were harvested on the free SearxNG engines; asking
    the same query through Brave must cost nothing and return the same
    candidates."""
    seen: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500)

    brave = client(tmp_path, httpx.MockTransport(refuse))
    harvested = [SearchResult("https://colgate.com/p", "google cse", 1, "Colgate")]
    assert brave.cache is not None
    brave.cache.put("colgate total 75ml", ("google cse",), harvested, now=999.0)
    assert brave.search(SearchQuery("S3", "colgate total 75ml"), 8) == harvested
    brave.cache.put("asked before, nothing found", ("duckduckgo",), [], now=999.0)
    assert brave.search(SearchQuery("S1", "asked before, nothing found"), 8) == []
    assert seen == [] and brave.calls == 0 and brave.served_from_cache == 2


def test_a_miss_calls_the_api_with_the_key_and_caches_the_answer(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=PAYLOAD)

    brave = client(tmp_path, httpx.MockTransport(handler))
    results = brave.search(SearchQuery("S3", "aquafresh pump 100ml"), 8)
    assert [r.url for r in results] == [
        "https://boots.com/aquafresh-pump-100ml",
        "https://superdrug.com/aquafresh/p/1",
    ]
    assert {r.engine for r in results} == {"brave_api"} and results[1].rank == 2
    request = seen[0]
    assert request.headers["X-Subscription-Token"] == "test-key"
    assert request.url.params["q"] == "aquafresh pump 100ml"
    assert request.url.params["country"] == "GB"
    # the second ask is free
    assert brave.search(SearchQuery("S3", "aquafresh pump 100ml"), 8) == results
    assert len(seen) == 1 and brave.calls == 1


def test_the_per_run_cap_stops_spending(tmp_path: Path) -> None:
    brave = client(tmp_path, httpx.MockTransport(lambda r: httpx.Response(200, json=PAYLOAD)))
    for n in range(3):
        brave.search(SearchQuery("S3", f"query {n}"), 8)
    with pytest.raises(SearchError, match="call cap reached"):
        brave.search(SearchQuery("S3", "one too many"), 8)


def test_a_refused_key_fails_loudly_and_is_not_retried(tmp_path: Path) -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(401, json={"error": "bad token"})

    brave = client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(SearchError, match="refused the key"):
        brave.search(SearchQuery("S3", "x"), 8)
    assert len(seen) == 1


def test_a_rate_limit_is_retried(tmp_path: Path) -> None:
    answers = iter([httpx.Response(429), httpx.Response(200, json=PAYLOAD)])
    brave = client(tmp_path, httpx.MockTransport(lambda r: next(answers)))
    assert len(brave.search(SearchQuery("S3", "y"), 8)) == 2


def test_no_web_block_is_an_empty_answer_not_an_error(tmp_path: Path) -> None:
    brave = client(tmp_path, httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    assert brave.search(SearchQuery("S1", '"0000000000000"'), 8) == []


def test_shipped_config_is_brave_when_a_key_is_present() -> None:
    assert search_backend() == "auto"
    shipped = load_brave_config()
    assert shipped.endpoint.startswith("https://api.search.brave.com/")
    assert shipped.max_calls_per_run > 0
