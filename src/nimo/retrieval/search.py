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

    **Strategies stop once the cap is full** when `early_exit_on_full_cap` is
    set. That is the single largest lever on query budget: without it, qa
    costs 1904 queries and gets rate-limited; with it, ~412 and does not.
    """
    order = {name: position for position, name in enumerate(config.strategy_order)}
    seen: dict[str, CandidateURL] = {}
    ranked: list[tuple[int, int, str]] = []

    for query in sorted(queries, key=lambda item: order.get(item.strategy, len(order))):
        # Early exit: the cap is already met, so every further strategy spends
        # a query on candidates that would be discarded anyway. Measured, one
        # strategy against the configured engine portfolio returns 7-30 unique
        # candidates, so this usually stops after the first — taking qa's
        # budget from ~1904 queries to ~412 (`config/retrieval.yaml`).
        if config.early_exit_on_full_cap and len(seen) >= config.max_candidates:
            break

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


def brand_signal_rate(candidates: list[CandidateURL], brand: str) -> float:
    """Fraction of candidates whose URL or title mentions the brand.

    **A cheap quality signal, added because counting candidates hid a real
    failure.** A run was reported as healthy on "20.0 candidates per row — the
    cap filled on every row", while the candidates were MIT AI news, bilibili
    videos and `akinator.com`: Bing was returning results for an entirely
    different query while reporting no error. Quantity looked perfect
    throughout.

    This does not establish that a candidate is the right *product* — that
    needs the page itself (P8) and the matcher (P9). It establishes something
    weaker and still worth having: that retrieval is returning pages about
    roughly the right *thing*. `support.microsoft.com/fix-bluetooth-problems`
    scores 0 for an `AQUAFRESH` row and no threshold tuning can rescue it.

    `05` §5 wants the systemic pattern surfaced in the run summary rather than
    inferred row by row; this is the retrieval-side number for that.
    """
    if not candidates:
        return 0.0
    token = brand.split()[0].lower().strip() if brand.strip() else ""
    if not token:
        return 0.0
    hits = sum(
        1
        for candidate in candidates
        if token in candidate.url.lower()
        or (candidate.title_snippet or "").lower().find(token) >= 0
    )
    return hits / len(candidates)
