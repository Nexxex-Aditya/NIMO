"""`nimo.fetch.images` — pack shots through the same controls as pages.

Zero network (`04` §6): `httpx.MockTransport` for every request, DNS stubbed
by the same autouse fixture the page tests use (imported here).
"""

import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from nimo.fetch import (
    Fetcher,
    ImageCache,
    RobotsCache,
    default_image_cache,
    fetch_image,
    image_key,
    resolve_image_url,
)
from tests.fetch.test_client import CONFIG, public_dns  # noqa: F401 — autouse DNS stub

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9"


def fetcher(handler: Callable[[httpx.Request], httpx.Response]) -> Fetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return Fetcher(
        config=CONFIG,
        client=client,
        robots=RobotsCache(fetch=lambda url: None, user_agent=CONFIG.user_agent),
        cache=None,
        clock=lambda: 1000.0,
    )


def jpeg_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})


def test_an_image_is_fetched_as_bytes_with_its_media_type() -> None:
    outcome = fetch_image(fetcher(jpeg_response), "https://cdn.boots.com/p.jpg", None)
    assert outcome.status == "ok"
    assert outcome.media_type == "image/jpeg"
    assert outcome.data == JPEG
    assert outcome.sha256 == hashlib.sha256(JPEG).hexdigest()
    assert outcome.from_cache is False


def test_a_non_image_content_type_is_refused_not_decoded() -> None:
    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"})

    outcome = fetch_image(fetcher(html), "https://cdn.boots.com/p.jpg", None)
    assert outcome.status == "not_an_image" and outcome.data == b""
    assert outcome.sha256 is None
    assert "text/html" in (outcome.detail or "")


def test_the_size_cap_is_enforced_while_streaming() -> None:
    def big(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff" * 20_000, headers={"content-type": "image/png"})

    outcome = fetch_image(fetcher(big), "https://cdn.boots.com/hero.png", None)
    assert outcome.status == "too_large" and outcome.data == b""


def test_a_private_address_is_refused_before_any_request() -> None:
    """`05` §2 applies to assets exactly as to pages."""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return jpeg_response(request)

    outcome = fetch_image(fetcher(handler), "https://internal.test/p.jpg", None)
    assert outcome.status == "blocked" and requests == []


def test_a_redirect_to_the_metadata_endpoint_is_refused_at_that_hop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.boots.com":
            return httpx.Response(302, headers={"location": "http://meta.test/latest/"})
        return jpeg_response(request)

    outcome = fetch_image(fetcher(handler), "https://cdn.boots.com/p.jpg", None)
    assert outcome.status == "blocked" and "hop 1" in (outcome.detail or "")


def test_a_legitimate_redirect_is_followed_and_the_final_url_kept() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old.jpg":
            return httpx.Response(301, headers={"location": "/new.jpg"})
        return jpeg_response(request)

    outcome = fetch_image(fetcher(handler), "https://cdn.boots.com/old.jpg", None)
    assert outcome.status == "ok" and outcome.final_url == "https://cdn.boots.com/new.jpg"


def test_a_403_is_blocked_and_a_500_is_http_error() -> None:
    forbidden = fetch_image(fetcher(lambda r: httpx.Response(403)), "https://cdn.x.com/a.jpg", None)
    broken = fetch_image(fetcher(lambda r: httpx.Response(500)), "https://cdn.x.com/b.jpg", None)
    assert (forbidden.status, forbidden.http_status) == ("blocked", 403)
    assert (broken.status, broken.http_status) == ("http_error", 500)


def test_a_cache_hit_issues_no_request_and_a_failure_is_cached_shorter(tmp_path: Path) -> None:
    cache = default_image_cache(tmp_path, ttl_days=7.0, failure_ttl_hours=12.0, enabled=True)
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return jpeg_response(request) if "ok" in request.url.path else httpx.Response(404)

    first = fetch_image(fetcher(handler), "https://cdn.boots.com/ok.jpg", cache)
    again = fetch_image(fetcher(handler), "https://cdn.boots.com/ok.jpg", cache)
    assert first.status == "ok" and again.status == "ok" and again.from_cache
    assert again.data == JPEG and requests == ["https://cdn.boots.com/ok.jpg"]

    missing = fetch_image(fetcher(handler), "https://cdn.boots.com/gone.jpg", cache)
    missing_again = fetch_image(fetcher(handler), "https://cdn.boots.com/gone.jpg", cache)
    assert missing.status == "http_error" and missing_again.from_cache
    assert requests.count("https://cdn.boots.com/gone.jpg") == 1

    # Past the failure TTL the failure is re-tried; the success is still served.
    later = ImageCache(tmp_path, ttl_s=7 * 86400.0, failure_ttl_s=12 * 3600.0)
    assert later.get("https://cdn.boots.com/gone.jpg", 1000.0 + 13 * 3600) is None
    assert later.get("https://cdn.boots.com/ok.jpg", 1000.0 + 13 * 3600) is not None


def test_the_cache_is_keyed_on_the_image_url_and_stores_bytes_beside_meta(tmp_path: Path) -> None:
    cache = default_image_cache(tmp_path, 7.0, 12.0, True)
    fetch_image(fetcher(jpeg_response), "https://cdn.boots.com/p.jpg", cache)
    key = image_key("https://cdn.boots.com/p.jpg")
    assert (tmp_path / key[:2] / f"{key}.bin").read_bytes() == JPEG
    assert '"media_type": "image/jpeg"' in (tmp_path / key[:2] / f"{key}.json").read_text()


@pytest.mark.parametrize(
    ("page", "src", "expected"),
    [
        ("https://boots.com/p/1", "/media/p.jpg", "https://boots.com/media/p.jpg"),
        ("https://boots.com/p/1", "https://cdn.x.com/p.jpg", "https://cdn.x.com/p.jpg"),
        ("https://boots.com/p/1", "//cdn.x.com/p.jpg", "https://cdn.x.com/p.jpg"),
    ],
)
def test_relative_image_urls_resolve_against_the_page(page: str, src: str, expected: str) -> None:
    assert resolve_image_url(page, src) == expected
