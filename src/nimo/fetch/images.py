"""Pack-shot fetching — `03` §4 stage 6 step 5, `05` §2/§3.

The same wrapper discipline as page fetching (`client.py`): the SSRF guard
on the URL and on EVERY redirect hop, robots.txt, per-host pacing, a size
cap enforced while streaming — plus two things a page fetch does not need:
the response must declare an image media type from a fixed allowlist, and
the bytes are kept as bytes (a page is decoded; an image is not).

Cached separately from pages (`data/cache/images/`), content-addressed by
the image URL, with the page cache's TTLs. Measured 2026-09-12: the office
network cannot fetch retailer assets, so every image the office run needs
must already be here — the home machine harvests them and the cache travels.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

import httpx
import structlog

from nimo.fetch.client import Fetcher
from nimo.fetch.guard import UnsafeUrlError, assert_safe_url

log = structlog.get_logger(__name__)

ImageStatus = Literal["ok", "http_error", "timeout", "blocked", "not_an_image", "too_large"]

_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


class ImageCacheError(Exception):
    """A cache entry exists but cannot be read as one."""


@dataclass(frozen=True)
class ImageOutcome:
    url: str
    final_url: str
    status: ImageStatus
    http_status: int | None
    media_type: str | None
    data: bytes  # empty unless status == "ok"
    from_cache: bool
    detail: str | None = None

    @property
    def sha256(self) -> str | None:
        return hashlib.sha256(self.data).hexdigest() if self.status == "ok" else None


def image_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ImageCache:
    """One `.bin` (the bytes) and one `.json` (everything else) per image.
    A failure is cached too, bytes-less, on the shorter TTL — an asset host
    that refused us once will refuse us again for a while."""

    directory: Path
    ttl_s: float
    failure_ttl_s: float
    enabled: bool = True

    def _paths(self, key: str) -> tuple[Path, Path]:
        base = self.directory / key[:2] / key
        return base.with_suffix(".json"), base.with_suffix(".bin")

    def get(self, url: str, now: float) -> ImageOutcome | None:
        if not self.enabled:
            return None
        meta_path, data_path = self._paths(image_key(url))
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            status: ImageStatus = meta["status"]
            fetched_at = float(meta["fetched_at"])
            data = data_path.read_bytes() if status == "ok" else b""
        except (OSError, ValueError, KeyError) as error:
            raise ImageCacheError(
                f"{meta_path} is not readable as an image cache entry: {error}. Delete it to "
                f"re-fetch; a cache that quietly drops entries looks identical to one that works."
            ) from error
        ttl = self.ttl_s if status == "ok" else self.failure_ttl_s
        if now - fetched_at > ttl:
            return None
        return ImageOutcome(
            url=url,
            final_url=str(meta["final_url"]),
            status=status,
            http_status=meta.get("http_status"),
            media_type=meta.get("media_type"),
            data=data,
            from_cache=True,
            detail=meta.get("detail"),
        )

    def put(self, outcome: ImageOutcome, now: float) -> None:
        if not self.enabled:
            return
        meta_path, data_path = self._paths(image_key(outcome.url))
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        if outcome.status == "ok":
            data_path.write_bytes(outcome.data)
        meta_path.write_text(
            json.dumps(
                {
                    "url": outcome.url,
                    "final_url": outcome.final_url,
                    "status": outcome.status,
                    "http_status": outcome.http_status,
                    "media_type": outcome.media_type,
                    "detail": outcome.detail,
                    "fetched_at": now,
                    "bytes": len(outcome.data),
                },
                indent=1,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def default_image_cache(
    directory: Path, ttl_days: float, failure_ttl_hours: float, enabled: bool
) -> ImageCache:
    return ImageCache(
        directory=directory,
        ttl_s=ttl_days * 86400.0,
        failure_ttl_s=failure_ttl_hours * 3600.0,
        enabled=enabled,
    )


def resolve_image_url(page_url: str, image_url: str) -> str:
    """`<img src>` is often page-relative; `og:image` is not. One rule."""
    return urljoin(page_url, image_url.strip())


def fetch_image(fetcher: Fetcher, url: str, cache: ImageCache | None) -> ImageOutcome:
    """Fetch one image through the page fetcher's client and controls.

    Never raises for a per-image problem: every failure is an `ImageOutcome`
    with a status, so a missing pack shot is a recorded absence, not a
    crashed row (`04` §4 is about the *runner* catching, not about this
    layer hiding — the status says exactly what happened).
    """
    now = fetcher.clock()
    if cache is not None:
        cached = cache.get(url, now)
        if cached is not None:
            return cached

    def finish(
        status: ImageStatus,
        http_status: int | None,
        final_url: str,
        media_type: str | None = None,
        data: bytes = b"",
        detail: str | None = None,
    ) -> ImageOutcome:
        outcome = ImageOutcome(url, final_url, status, http_status, media_type, data, False, detail)
        if cache is not None:
            cache.put(outcome, now)
        return outcome

    try:
        assert_safe_url(url)
    except UnsafeUrlError as error:
        return finish("blocked", None, url, detail=str(error))
    if fetcher.config.respect_robots and not fetcher.robots.allowed(url):
        return finish("blocked", None, url, detail="disallowed by robots.txt")

    current = url
    for hop in range(fetcher.config.max_redirects + 1):
        fetcher.throttle(current)
        try:
            with fetcher.client.stream("GET", current) as response:
                if response.status_code in _REDIRECT_STATUS:
                    location = response.headers.get("location")
                    if not location:
                        return finish(
                            "http_error", response.status_code, current, detail="empty redirect"
                        )
                    target = urljoin(current, location)
                    try:
                        assert_safe_url(target)  # `05` §2: every hop
                    except UnsafeUrlError as error:
                        return finish(
                            "blocked",
                            None,
                            target,
                            detail=f"redirect hop {hop + 1} refused: {error}",
                        )
                    current = target
                    continue
                if response.is_error:
                    status: ImageStatus = (
                        "blocked" if response.status_code in (401, 403, 429) else "http_error"
                    )
                    return finish(
                        status, response.status_code, current, detail=f"HTTP {response.status_code}"
                    )
                media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if media_type not in fetcher.config.image_types:
                    return finish(
                        "not_an_image",
                        response.status_code,
                        current,
                        media_type=media_type or None,
                        detail=f"content-type {media_type or '(none)'} is not an allowed image",
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > fetcher.config.image_max_bytes:
                        return finish(
                            "too_large",
                            response.status_code,
                            current,
                            media_type=media_type,
                            detail=f"exceeds image_max_bytes ({fetcher.config.image_max_bytes})",
                        )
                    chunks.append(chunk)
                return finish("ok", response.status_code, current, media_type, b"".join(chunks))
        except httpx.TimeoutException as error:
            return finish("timeout", None, current, detail=f"timeout: {error}")
        except httpx.HTTPError as error:
            return finish("http_error", None, current, detail=f"{type(error).__name__}: {error}")
    return finish(
        "http_error", None, current, detail=f"more than {fetcher.config.max_redirects} redirects"
    )
