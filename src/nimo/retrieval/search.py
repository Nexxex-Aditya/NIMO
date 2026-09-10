"""Strategy orchestration, merge and cap — `specs/retrieval.md` §6.

Pure given a `SearchFn`: the network lives behind the injected callable, which
is what lets every merge rule here be tested with zero network (`04` §6).
"""

from collections.abc import Callable
from dataclasses import dataclass

from nimo.contracts import CandidateURL
from nimo.retrieval.canonical import UrlError, canonicalize, is_safe_candidate
from nimo.retrieval.config import RetrievalConfig
from nimo.retrieval.queries import SearchQuery


@dataclass(frozen=True)
class SearchResult:
    """One raw result from the search backend, before canonicalization."""

    url: str
    engine: str
    rank: int
    title: str | None


# Injected so the merge logic is testable without a live index, and so P8's
# cache can wrap it later without this module changing.
SearchFn = Callable[[SearchQuery, int], list[SearchResult]]


def merge_candidates(
    queries: list[SearchQuery],
    search: SearchFn,
    config: RetrievalConfig,
) -> list[CandidateURL]:
    """Run every strategy, merge, dedup by canonical URL, cap.

    **First strategy to produce a URL owns its provenance.** A URL found by
    both S1 and S5 is recorded as S1's, because that is the stronger signal
    and the one worth knowing about when the candidate turns out to be right —
    `source_query` is what makes a weak strategy visible later (`03` §3).

    Ordering is (strategy order, rank within strategy), so a barcode-exact hit
    outranks a verbatim-text hit regardless of what the engine thought.
    """
    order = {name: position for position, name in enumerate(config.strategy_order)}
    seen: dict[str, CandidateURL] = {}
    ranked: list[tuple[int, int, str]] = []

    for query in sorted(queries, key=lambda item: order.get(item.strategy, len(order))):
        for result in search(query, config.per_strategy_limit)[: config.per_strategy_limit]:
            if not is_safe_candidate(result.url):
                continue
            try:
                url = canonicalize(result.url)
            except UrlError:
                continue
            if url in seen:
                continue
            seen[url] = CandidateURL(
                url=url,
                source_query=query.strategy,
                engine=result.engine,
                rank=result.rank,
                title_snippet=result.title,
            )
            ranked.append((order.get(query.strategy, len(order)), result.rank, url))

    ranked.sort()
    return [seen[url] for _, _, url in ranked[: config.max_candidates]]
