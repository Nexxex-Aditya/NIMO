"""Content-addressed search-result cache — `04` §6, `05` §5.

`04` §6: "Cache-first. A cache hit must not issue a request. Cache is
content-addressed and inspectable."

This is what makes free engines viable as the primary source rather than a
gamble. A cache hit costs no query, so it cannot be blocked, cannot be rate
limited, and cannot fail partway. Concretely it buys three things:

- **Iteration is free.** Tuning the matcher over the same 412 rows does not
  re-issue 412 queries per attempt.
- **A blocked run is resumable.** When Brave opens its circuit halfway
  through, the rows already fetched stay fetched; restarting later only
  queries the remainder.
- **The demo is reproducible.** `04` §5 requires a re-run to be
  byte-identical, which is impossible against a live index that reranks.

`05` §5 forbids an infinite TTL ("serves stale content forever, no error"), so
entries expire and are re-fetched.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from nimo.retrieval.search import SearchResult


class CacheError(Exception):
    """A cache entry exists but cannot be read as one."""


def cache_key(query_text: str, engines: tuple[str, ...]) -> str:
    """Content address for one query against one engine set.

    The engine set is part of the key deliberately: the same query against
    `[brave, startpage]` and against `[bing]` are different questions, and
    silently serving one for the other would make a degraded run look like a
    healthy cached one.
    """
    material = json.dumps(
        {"q": query_text, "engines": sorted(engines)}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class SearchCache:
    """Disk cache of search results, one JSON file per query.

    Inspectable by design (`04` §6): a human can open any entry and see the
    query that produced it alongside the results, which is what makes a
    surprising candidate list debuggable rather than mysterious.
    """

    directory: Path
    ttl_s: float
    enabled: bool = True

    def _path(self, key: str) -> Path:
        # Two-level fan-out: 412+ files in one directory is fine, but this
        # stays cheap if the cache is ever pointed at a much larger catalog.
        return self.directory / key[:2] / f"{key}.json"

    def get(
        self, query_text: str, engines: tuple[str, ...], now: float
    ) -> list[SearchResult] | None:
        """Cached results, or `None` on a miss or an expired entry."""
        if not self.enabled:
            return None
        path = self._path(cache_key(query_text, engines))
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise CacheError(
                f"{path} is not readable as a cache entry: {error}. Delete it to re-fetch; "
                f"it is not silently ignored because a cache that quietly drops entries looks "
                f"identical to one that is working (`04` §4)."
            ) from error

        if now - float(payload.get("fetched_at", 0.0)) > self.ttl_s:
            return None  # `05` §5: expired, not served

        return [
            SearchResult(
                url=str(item["url"]),
                engine=str(item["engine"]),
                rank=int(item["rank"]),
                title=item["title"] if isinstance(item.get("title"), str) else None,
            )
            for item in payload.get("results", [])
        ]

    def put(
        self,
        query_text: str,
        engines: tuple[str, ...],
        results: list[SearchResult],
        now: float,
    ) -> None:
        """Store results. Writes the query alongside them for inspectability."""
        if not self.enabled:
            return
        path = self._path(cache_key(query_text, engines))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "query": query_text,
                    "engines": sorted(engines),
                    "fetched_at": now,
                    "results": [
                        {
                            "url": result.url,
                            "engine": result.engine,
                            "rank": result.rank,
                            "title": result.title,
                        }
                        for result in results
                    ],
                },
                indent=1,
                sort_keys=True,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def default_cache(directory: Path, ttl_days: float, enabled: bool) -> SearchCache:
    return SearchCache(directory=directory, ttl_s=ttl_days * 86400.0, enabled=enabled)


def now_seconds() -> float:
    """Wall clock, isolated here so callers can inject a fixed value in tests
    and nothing in the cache logic reads the clock directly (`04` §5)."""
    return time.time()
