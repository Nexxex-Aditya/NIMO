"""The network-backed stages — where P7, P8 and P9 meet the runner.

`nimo.run.runner` is deliberately ignorant of SearxNG, HTTP and the registry
store: it drives whatever `Stages` it is handed. This module builds the real
ones. It is the only place that composes retrieval, fetch, match and the
registry write path, so the three seams the phases left open are closed here
and nowhere else:

- **`CandidateEvidence.url` is the canonical candidate URL**, never the
  fetcher's post-redirect `final_url`. P9's first gate run reported 0/5 on
  exactly that mismatch (`www.`), and every downstream comparison — gold set,
  cache key, registry — keys on the canonical form.
- **Write-back fires on a GTIN accept only** (`specs/match.md` §6), and every
  write is audit-logged (`05` §4). The registry file is rewritten atomically
  per merge rather than once at the end, because a resumed run skips
  completed rows and would otherwise lose the merges they produced.
- **Fetch budget is capped per row** — `03` §4 stage 2's "cap hard; more costs
  fetch budget for no gain" applied at the fetch boundary, not just the
  candidate list. The number lives in `config/retrieval.yaml` because
  retrieval's early exit keys off it (`specs/retrieval.md` §5a.7).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from nimo.classify.model import ModuleClassifier
from nimo.contracts import CandidateEvidence, CandidateURL, CanonicalEntity, ProductQuery, Selection
from nimo.extract import extract_evidence
from nimo.fetch import Fetcher
from nimo.match import (
    MatchConfig,
    ScoredCandidate,
    audit_for,
    build_entity,
    decide,
    select,
)
from nimo.registry import (
    RegistryIndex,
    RegistryThresholds,
    append_audit,
    block_keys,
    entity_id,
    lookup,
    write_entities,
)
from nimo.retrieval import (
    RetrievalConfig,
    SearxngClient,
    build_queries,
    merge_candidates,
    retailer_domain,
)
from nimo.run.runner import CacheCounter, Stages


@dataclass
class RegistryWriter:
    """Holds the in-memory entity set and persists every merge immediately.

    Per-merge rewrites rather than one write at the end: the runner skips
    completed rows on resume, so a merge held only in memory when the run is
    killed is lost for good — the row that produced it will never run again.
    412 atomic rewrites of a small file is the cheap side of that trade.
    """

    entities_path: Path
    audit_path: Path
    run_id: str
    entities: dict[str, CanonicalEntity] = field(default_factory=dict)

    def write_back(
        self, query: ProductQuery, best: ScoredCandidate | None, module: str | None
    ) -> bool:
        decision = decide(best)
        if not decision.allowed or best is None:
            return False
        now = datetime.now(UTC)  # metadata on the entity, never read by logic (`04` §5)
        # A GTIN accept guarantees a GTIN block key; its stable id is what a
        # prior run would have stored this product under (`03` §3, `05` §4).
        gtin_key = next(key for key in block_keys(query) if key.method == "exact_gtin")
        existing = self.entities.get(entity_id(gtin_key))
        entity = build_entity(query, best, module, now, existing=existing)
        self.entities[entity.entity_id] = entity
        write_entities(
            self.entities_path, sorted(self.entities.values(), key=lambda e: e.entity_id)
        )
        append_audit(self.audit_path, audit_for(entity, self.run_id, now))
        return True


def live_stages(
    *,
    searx: SearxngClient,
    fetcher: Fetcher,
    retrieval_config: RetrievalConfig,
    match_config: MatchConfig,
    retailers_path: Path,
    index: RegistryIndex,
    thresholds: RegistryThresholds,
    classifier: ModuleClassifier,
    writer: RegistryWriter,
    cache_counter: CacheCounter,
) -> Stages:
    """Compose the real stages. Everything network-backed is injected."""
    from nimo.normalize import normalize_row

    def retrieve(query: ProductQuery) -> list[CandidateURL]:
        return merge_candidates(
            build_queries(query, retailers_path), searx.search, retrieval_config
        )

    def fetch(candidates: list[CandidateURL]) -> list[CandidateEvidence]:
        evidence: list[CandidateEvidence] = []
        for candidate in candidates[: retrieval_config.fetch_budget]:
            outcome = fetcher.fetch(candidate.url)
            if outcome.from_cache:
                cache_counter.hits += 1
            else:
                cache_counter.misses += 1
            evidence.append(
                extract_evidence(
                    candidate.url,  # canonical identity — NOT outcome.final_url
                    outcome.html,
                    datetime.now(UTC),
                    status=outcome.status,
                )
            )
        return evidence

    def match(
        query: ProductQuery, evidence: list[CandidateEvidence]
    ) -> tuple[Selection, ScoredCandidate | None]:
        selection, ranked = select(
            query, evidence, match_config, retailer_domain(query.retailer_raw, retailers_path)
        )
        usable = [item for item in ranked if not item.rejected]
        return selection, (usable[0] if usable else None)

    return Stages(
        normalize=normalize_row,
        registry=lambda query: lookup(query, index, thresholds),
        retrieve=retrieve,
        fetch=fetch,
        match=match,
        writeback=writer.write_back,
        classify=classifier.predict,
    )
