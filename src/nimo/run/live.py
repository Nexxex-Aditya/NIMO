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

import structlog

from nimo.calibrate import IsotonicCurve
from nimo.characteristics import CharacteristicExtractor, gate_only
from nimo.classify.model import ModuleClassifier
from nimo.contracts import (
    CandidateEvidence,
    CandidateURL,
    CanonicalEntity,
    CharacteristicRule,
    CharacteristicValues,
    ProductQuery,
    Selection,
)
from nimo.extract import extract_evidence
from nimo.fetch import Fetcher
from nimo.llm import LlmValidationError
from nimo.match import (
    AdjudicationError,
    Adjudicator,
    MatchConfig,
    ScoredCandidate,
    audit_for,
    build_entity,
    decide,
    select,
    should_adjudicate,
)
from nimo.reason import ReasonConfig, compose
from nimo.registry import (
    RegistryIndex,
    RegistryThresholds,
    append_audit,
    block_keys,
    entity_id,
    lookup,
    read_entities,
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

log = structlog.get_logger(__name__)


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
        self,
        query: ProductQuery,
        best: ScoredCandidate | None,
        module: str | None,
        values: CharacteristicValues | None,
    ) -> bool:
        decision = decide(best)
        if not decision.allowed or best is None:
            return False
        now = datetime.now(UTC)  # metadata on the entity, never read by logic (`04` §5)
        # A GTIN accept guarantees a GTIN block key; its stable id is what a
        # prior run would have stored this product under (`03` §3, `05` §4).
        gtin_key = next(key for key in block_keys(query) if key.method == "exact_gtin")
        existing = self.entities.get(entity_id(gtin_key))
        # Only values the model actually produced are stored; a gate-only
        # result (no model) keeps whatever the entity already holds.
        stored = (
            {name: value for name, value in values.values.items() if value is not None}
            if values is not None and values.source == "llm"
            else None
        )
        entity = build_entity(query, best, module, now, existing=existing, characteristics=stored)
        self._persist(entity, now)
        return True

    def refresh(
        self,
        query: ProductQuery,
        entity: CanonicalEntity,
        module: str | None,
        values: CharacteristicValues,
    ) -> bool:
        """Complete an entity a hit found incomplete: fill the module (never
        overwrite one) and model-sourced characteristics, add this row to
        its members. Audit-logged like any write (`05` §4). `False` when
        nothing would change — a gate-only run cannot complete an entity."""
        new_module = entity.module if entity.module is not None else module
        stored = (
            {name: value for name, value in values.values.items() if value is not None}
            if values.source == "llm"
            else dict(entity.characteristics)
        )
        members = sorted(set(entity.member_row_uids) | {query.row_uid})
        if (
            new_module == entity.module
            and stored == entity.characteristics
            and members == entity.member_row_uids
        ):
            return False
        now = datetime.now(UTC)  # metadata, never read by logic (`04` §5)
        updated = entity.model_copy(
            update={
                "module": new_module,
                "characteristics": stored,
                "member_row_uids": members,
                "updated_at": now,
            }
        )
        self._persist(updated, now)
        return True

    def _persist(self, entity: CanonicalEntity, now: datetime) -> None:
        """Write the entity set, merged over whatever is on disk NOW.

        Two live processes can share the registry — the UI open while a
        batch run harvests. Each holds its own in-memory set and rewrites
        the whole file per merge, so a naive write would clobber entities
        the other wrote since this process started. Re-reading and merging
        first (ours win on the same id — they are newer) makes concurrent
        writers additive. Entities are never deleted, so a union is right.
        """
        self.entities[entity.entity_id] = entity
        on_disk = {e.entity_id: e for e in read_entities(self.entities_path)}
        on_disk.update(self.entities)
        self.entities = on_disk
        write_entities(
            self.entities_path, sorted(self.entities.values(), key=lambda e: e.entity_id)
        )
        append_audit(self.audit_path, audit_for(entity, self.run_id, now))


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
    rules: list[CharacteristicRule],
    reason_config: ReasonConfig,
    adjudicator: Adjudicator | None = None,
    extractor: CharacteristicExtractor | None = None,
    curve: IsotonicCurve | None = None,
    tau_abstain: float = 0.0,
) -> Stages:
    """Compose the real stages. Everything network-backed is injected.

    With an `adjudicator`, the match stage runs Tier 3 when Layer A could not
    separate the top candidates (`specs/adjudicate.md` §1). A verdict the
    schema rejects — an index outside the pack, or an answer that will not
    validate twice — is logged and counted, and Layer A's selection stands:
    `05` §1's table says an injection attempt on the URL is "rejected at the
    validation gate, never reaches output", which is a validated state to
    continue from, not a reason to lose the row. A spent budget is not caught
    here; the runner aborts on it (`05` §3).
    """
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
            query,
            evidence,
            match_config,
            retailer_domain(query.retailer_raw, retailers_path),
            curve,
            tau_abstain,
        )
        usable = [item for item in ranked if not item.rejected]
        if adjudicator is not None and should_adjudicate(selection, ranked, match_config):
            try:
                selection = adjudicator.adjudicate(query, selection, ranked)
            except (AdjudicationError, LlmValidationError) as error:
                adjudicator.llm.counter.rejected_verdicts += 1
                log.warning(
                    "adjudication_rejected",
                    row_uid=query.row_uid,
                    error_type=type(error).__name__,
                    message=str(error)[:200],
                )
        # Write-back reads the HARD-RULE outcome only (`specs/match.md` §6):
        # `usable[0]` is Layer A's best, whatever the model said.
        return selection, (usable[0] if usable else None)

    def characteristics(
        query: ProductQuery, module: str | None, selected: CandidateEvidence | None
    ) -> CharacteristicValues:
        if extractor is None:
            return gate_only(query.row_uid, module, rules)
        return extractor.extract(query, module, selected)

    return Stages(
        normalize=normalize_row,
        registry=lambda query: lookup(query, index, thresholds),
        retrieve=retrieve,
        fetch=fetch,
        match=match,
        writeback=writer.write_back,
        classify=classifier.predict,
        characteristics=characteristics,
        extracts_values=extractor is not None,
        refresh=writer.refresh,
        reason=lambda query, registry, selection, module, values, evidence: compose(
            query, registry, selection, module, values, evidence, reason_config
        ),
    )
