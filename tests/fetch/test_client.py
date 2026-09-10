"""P8 fetcher tests — `specs/fetch.md` §2–§4, §8; `05` §2, §6.

Zero network (`04` §6): every request goes through `httpx.MockTransport` and
DNS is stubbed. `05` §6 makes the SSRF and cache items Definition-of-Done for
a fetch module, so these are behaviour tests.
"""

import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from nimo.fetch import (
    FetchConfig,
    FetchConfigError,
    Fetcher,
    PageCache,
    RobotsCache,
    default_page_cache,
    load_fetch_config,
    page_key,
)
from nimo.fetch.cache import CachedPage

CONFIG = FetchConfig(
    user_agent="nimo-product-truth-agent/0.1 (test)",
    min_interval_s=0.001,
    max_concurrent_per_host=1,
    respect_robots=True,
    connect_timeout_s=1.0,
    read_timeout_s=1.0,
    max_response_bytes=1_000_000,
    max_redirects=3,
    max_retries=1,
    backoff_base_s=0.001,
    backoff_max_s=0.002,
    cache_enabled=False,
    cache_ttl_days=7.0,
    failure_cache_ttl_hours=12.0,
)

PAGE = "<html><head><title>Aquafresh 100ml</title></head><body>product</body></html>"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every host resolves public unless a test says otherwise. No network."""

    def fake(host: str, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        address = {"internal.test": "10.0.0.5", "meta.test": "169.254.169.254"}.get(
            host, "93.184.216.34"
        )
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    config: FetchConfig = CONFIG,
    robots_body: str | None = None,
    cache: PageCache | None = None,
) -> Fetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return Fetcher(
        config=config,
        client=client,
        robots=RobotsCache(fetch=lambda url: robots_body, user_agent=config.user_agent),
        cache=cache,
        clock=lambda: 1000.0,
    )


# --- happy path --------------------------------------------------------------


def test_a_normal_page_is_fetched() -> None:
    result = fetcher(lambda r: httpx.Response(200, text=PAGE)).fetch("https://boots.com/p")
    assert result.status == "ok"
    assert result.http_status == 200
    assert "Aquafresh" in result.html
    assert result.from_cache is False


# --- `05` §2: SSRF, and the per-hop rule ------------------------------------


def test_a_host_resolving_private_is_never_requested() -> None:
    """Refused before connecting — the request handler must never be called."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text=PAGE)

    result = fetcher(handler).fetch("https://internal.test/p")
    assert result.status == "blocked"
    assert calls == []
    assert "private or reserved" in (result.detail or "")


def test_a_redirect_to_an_internal_address_is_refused_at_that_hop() -> None:
    """**The control `05` §2 exists for.** The first URL is entirely
    legitimate; the 302 points at the cloud metadata endpoint. `httpx` would
    have followed it, which is why redirects are followed manually here."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boots.com":
            return httpx.Response(302, headers={"location": "http://meta.test/latest/meta-data/"})
        return httpx.Response(200, text="SECRET")  # must never be reached

    result = fetcher(handler).fetch("https://boots.com/p")
    assert result.status == "blocked"
    assert "redirect hop 1 refused" in (result.detail or "")
    assert "SECRET" not in result.html


def test_a_legitimate_redirect_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://boots.com/new"})
        return httpx.Response(200, text=PAGE)

    result = fetcher(handler).fetch("https://boots.com/old")
    assert result.status == "ok"
    assert result.final_url.endswith("/new")


def test_a_redirect_loop_terminates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://boots.com/loop"})

    result = fetcher(handler).fetch("https://boots.com/loop")
    assert result.status == "http_error"
    assert "more than 3 redirects" in (result.detail or "")


def test_a_non_http_scheme_is_refused() -> None:
    result = fetcher(lambda r: httpx.Response(200)).fetch("file:///etc/passwd")
    assert result.status == "blocked"
    assert "not http" in (result.detail or "")


def test_an_oversized_response_is_abandoned_mid_stream() -> None:
    """`05` §2 calls an unbounded response a resource-exhaustion vector, so
    the cap is applied while streaming rather than after."""
    small = FetchConfig(**{**CONFIG.__dict__, "max_response_bytes": 100})
    body = "x" * 100_000
    result = fetcher(lambda r: httpx.Response(200, text=body), config=small).fetch(
        "https://boots.com/big"
    )
    assert result.status == "ok"
    assert len(result.html) < 100_000


# --- robots.txt --------------------------------------------------------------


def test_a_disallowed_path_is_not_requested() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=PAGE)

    result = fetcher(handler, robots_body="User-agent: *\nDisallow: /private").fetch(
        "https://boots.com/private/p"
    )
    assert result.status == "blocked"
    assert "robots.txt" in (result.detail or "")
    assert calls == []


def test_an_allowed_path_proceeds() -> None:
    result = fetcher(
        lambda r: httpx.Response(200, text=PAGE),
        robots_body="User-agent: *\nDisallow: /private",
    ).fetch("https://boots.com/public/p")
    assert result.status == "ok"


def test_an_unreachable_robots_file_means_allowed() -> None:
    """RFC 9309, and what every mainstream crawler does. Treating it as a
    blanket disallow would silently drop every site with a transient error —
    the plausible-wrong-answer shape `05` §5 is about."""
    result = fetcher(lambda r: httpx.Response(200, text=PAGE), robots_body=None).fetch(
        "https://boots.com/p"
    )
    assert result.status == "ok"


def test_robots_is_fetched_once_per_host_not_per_url() -> None:
    """Twenty pages on one retailer must not fetch robots.txt twenty times —
    that would itself be the impolite behaviour robots exists to prevent."""
    fetches: list[str] = []

    def record(url: str) -> str:
        fetches.append(url)
        return "User-agent: *\nAllow: /"

    robots = RobotsCache(fetch=record, user_agent="nimo-test")
    for path in ("/a", "/b", "/c"):
        robots.allowed(f"https://boots.com{path}")
    robots.allowed("https://superdrug.com/x")
    assert len(fetches) == 2  # one per host


# --- retries -----------------------------------------------------------------


def test_a_403_is_blocked_and_never_retried() -> None:
    """A bot wall retried three times is three times the rudeness for the same
    answer. Measured, 4 of 10 real retailers return one."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(403, text="Pardon Our Interruption")

    result = fetcher(handler).fetch("https://tesco.com/p")
    assert result.status == "blocked"
    assert len(attempts) == 1
    assert "Pardon Our Interruption" in result.html


def test_a_404_is_an_http_error_and_never_retried() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(404, text="not found")

    result = fetcher(handler).fetch("https://boots.com/gone")
    assert result.status == "http_error"
    assert len(attempts) == 1


def test_a_5xx_is_retried_then_reported() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503)

    result = fetcher(handler).fetch("https://boots.com/p")
    assert result.status == "http_error"
    assert len(attempts) == CONFIG.max_retries + 1


def test_a_timeout_is_retried_then_reported() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    result = fetcher(handler).fetch("https://boots.com/p")
    assert result.status == "timeout"
    assert len(attempts) == CONFIG.max_retries + 1


# --- cache -------------------------------------------------------------------


def test_a_cache_hit_issues_no_request(tmp_path: Path) -> None:
    """`03` §4 stage 3 calls this non-negotiable: "Re-runs must never
    re-crawl.\""""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text=PAGE)

    cache = default_page_cache(tmp_path, 7.0, 12.0, enabled=True)
    config = FetchConfig(**{**CONFIG.__dict__, "cache_enabled": True})
    first = fetcher(handler, config=config, cache=cache).fetch("https://boots.com/p")
    second = fetcher(handler, config=config, cache=cache).fetch("https://boots.com/p")

    assert len(calls) == 1
    assert second.from_cache is True
    assert second.html == first.html


def test_failures_are_cached_too_but_expire_sooner(tmp_path: Path) -> None:
    """Re-requesting a known bot wall every run is rudeness for an answer we
    already have — but a block may lift, so it expires sooner than a page."""
    cache = default_page_cache(tmp_path, ttl_days=7.0, failure_ttl_hours=12.0, enabled=True)
    cache.put(
        CachedPage(
            url="https://tesco.com/p",
            final_url="https://tesco.com/p",
            status="blocked",
            http_status=403,
            html="wall",
            fetched_at=0.0,
        )
    )
    assert cache.get("https://tesco.com/p", now=11 * 3600) is not None
    assert cache.get("https://tesco.com/p", now=13 * 3600) is None


def test_a_successful_page_uses_the_longer_ttl(tmp_path: Path) -> None:
    cache = default_page_cache(tmp_path, ttl_days=7.0, failure_ttl_hours=12.0, enabled=True)
    cache.put(
        CachedPage(
            url="https://boots.com/p",
            final_url="https://boots.com/p",
            status="ok",
            http_status=200,
            html=PAGE,
            fetched_at=0.0,
        )
    )
    assert cache.get("https://boots.com/p", now=6 * 86400) is not None
    assert cache.get("https://boots.com/p", now=8 * 86400) is None


def test_the_cache_is_keyed_on_the_url() -> None:
    assert page_key("https://boots.com/a") != page_key("https://boots.com/b")
    assert page_key("https://boots.com/a") == page_key("https://boots.com/a")


# --- `05` §5 aggregate domain block -----------------------------------------


def test_per_domain_outcomes_are_counted() -> None:
    """`05` §5: "each fetch fails loud individually, but the systemic pattern
    — 'Boots recall just dropped to 0%' — is invisible without looking across
    rows." Measured, 4 of 10 retailers are bot walls, so this says which."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tesco.com":
            return httpx.Response(403)
        return httpx.Response(200, text=PAGE)

    instance = fetcher(handler)
    instance.fetch("https://tesco.com/a")
    instance.fetch("https://tesco.com/b")
    instance.fetch("https://boots.com/c")

    assert instance.domain_outcomes["tesco.com"] == {"blocked": 2}
    assert instance.domain_outcomes["boots.com"] == {"ok": 1}


# --- config ------------------------------------------------------------------


def test_shipped_config_loads() -> None:
    config = load_fetch_config()
    assert config.respect_robots is True
    assert config.min_interval_s >= 1.0
    assert config.max_response_bytes > 1_000_000


def test_a_disguised_user_agent_is_refused(tmp_path: Path) -> None:
    """`04` §6 requires an identifying UA. A browser-impersonation string
    would disguise exactly the blocking `05` §5 asks us to measure."""
    import yaml

    from nimo.fetch.config import CONFIG_PATH

    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    data["user_agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    path = tmp_path / "fetch.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(FetchConfigError, match="must identify this project"):
        load_fetch_config(path)
