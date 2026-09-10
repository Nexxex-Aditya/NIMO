"""Content-addressed page cache — `03` §4 stage 3, `05` §5.

`03` §4 stage 3: "Content-addressed disk cache. Key: canonical URL. Re-runs
must never re-crawl. **This is non-negotiable** — it makes stages 4–8 iterable
in seconds."

Same shape as P7's search cache and for the same reasons, with one addition
that phase did not need: **failures are cached too, with a shorter TTL.**
Re-requesting a known 403 bot wall on every run is pure rudeness for an answer
we already have — and 4 of 10 measured retailers are bot walls, so this is the
common path, not an optimisation. A block may lift, hence the shorter expiry.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from nimo.extract.page import FetchStatus


class PageCacheError(Exception):
    """A cache entry exists but cannot be read as one."""


@dataclass(frozen=True)
class CachedPage:
    url: str
    final_url: str
    status: FetchStatus
    http_status: int | None
    html: str
    fetched_at: float


def page_key(canonical_url: str) -> str:
    """Content address for one page. Keyed on the CANONICAL url (`03` §4
    stage 3), so two spellings of one page share an entry rather than being
    crawled twice."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class PageCache:
    directory: Path
    ttl_s: float
    failure_ttl_s: float
    enabled: bool = True

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def _ttl_for(self, status: FetchStatus) -> float:
        return self.ttl_s if status == "ok" else self.failure_ttl_s

    def get(self, canonical_url: str, now: float) -> CachedPage | None:
        """A cached page, or `None` on a miss or an expired entry."""
        if not self.enabled:
            return None
        path = self._path(page_key(canonical_url))
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise PageCacheError(
                f"{path} is not readable as a cache entry: {error}. Delete it to re-fetch; it is "
                f"not silently ignored, because a cache that quietly drops entries is "
                f"indistinguishable from one that is working (`04` §4)."
            ) from error

        cached = CachedPage(
            url=str(payload["url"]),
            final_url=str(payload.get("final_url", payload["url"])),
            status=payload["status"],
            http_status=payload.get("http_status"),
            html=str(payload.get("html", "")),
            fetched_at=float(payload.get("fetched_at", 0.0)),
        )
        if now - cached.fetched_at > self._ttl_for(cached.status):
            return None  # `05` §5: expired, not served
        return cached

    def put(self, page: CachedPage) -> None:
        if not self.enabled:
            return
        path = self._path(page_key(page.url))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "url": page.url,
                    "final_url": page.final_url,
                    "status": page.status,
                    "http_status": page.http_status,
                    "fetched_at": page.fetched_at,
                    "html": page.html,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def default_page_cache(
    directory: Path, ttl_days: float, failure_ttl_hours: float, enabled: bool
) -> PageCache:
    return PageCache(
        directory=directory,
        ttl_s=ttl_days * 86400.0,
        failure_ttl_s=failure_ttl_hours * 3600.0,
        enabled=enabled,
    )
