"""The per-row stage driver — `specs/run.md` §2, `04` §4.

**This module contains the only `except Exception` in `src/`.** `04` §4
forbids it everywhere without "re-raise or an explicit, logged, typed failure
record"; this is that sanctioned typed-failure-record site, and
`test_only_one_broad_except_exists_in_src` asserts it stays the only one.
"""

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from nimo.characteristics import from_entity, gate_only
from nimo.classify.model import ModuleClassifier
from nimo.contracts import (
    CandidateEvidence,
    CandidateURL,
    CharacteristicRule,
    CharacteristicValues,
    ModulePrediction,
    ProductQuery,
    RawRow,
    Reasoning,
    RegistryLookupResult,
    RowFailure,
    RunSummary,
    Selection,
)
from nimo.llm import LlmCounter
from nimo.match import ScoredCandidate
from nimo.normalize import normalize_row
from nimo.reason import ReasonConfig, compose
from nimo.registry import RegistryIndex, RegistryThresholds, lookup
from nimo.run.artifacts import (
    STAGE_SEQUENCE,
    clear_artifacts,
    completed_row_uids,
    config_hash,
    write_artifact,
)

MESSAGE_LIMIT = 500  # `03` §3: "str(exception), truncated by the runner"


@dataclass(frozen=True)
class RowArtifacts:
    """One row's complete output. Only ever constructed when every stage
    succeeded — there is no partially-populated form of this type, which is
    `04` §4's "never write a partial output row" expressed as a type rather
    than as a rule somebody has to remember."""

    row_uid: str
    query: ProductQuery
    registry: RegistryLookupResult
    candidates: list[CandidateURL]
    evidence: list[CandidateEvidence]
    selection: Selection
    module: ModulePrediction
    characteristics: CharacteristicValues
    reasoning: Reasoning
    wrote_back: bool


@dataclass(frozen=True)
class RunPaths:
    artifacts: Path
    trace: Path
    failures: Path
    config_dir: Path


@dataclass(frozen=True)
class Stages:
    """The stage implementations, injected rather than imported at the call
    site so a test can force one to raise and assert the attribution."""

    normalize: Callable[[RawRow], ProductQuery]
    registry: Callable[[ProductQuery], RegistryLookupResult]
    retrieve: Callable[[ProductQuery], list[CandidateURL]]
    fetch: Callable[[list[CandidateURL]], list[CandidateEvidence]]
    # Returns the Selection contract plus the best ScoredCandidate, which the
    # write-back decision needs and the trace records. Both come from
    # `nimo.match`; the runner is the orchestrator that joins them.
    match: Callable[
        [ProductQuery, list[CandidateEvidence]], tuple[Selection, ScoredCandidate | None]
    ]
    # `True` if the registry was written. Gated inside on a GTIN accept only
    # (`specs/match.md` §6); the runner never decides this itself. Runs AFTER
    # classify and characteristics so the entity carries both
    # (`specs/characteristics.md` §5).
    writeback: Callable[
        [ProductQuery, ScoredCandidate | None, str | None, CharacteristicValues | None], bool
    ]
    classify: Callable[[ProductQuery], ModulePrediction]
    # (query, module, the selected page's evidence or None) -> the 13 values
    characteristics: Callable[
        [ProductQuery, str | None, CandidateEvidence | None], CharacteristicValues
    ]
    # The REASONING cell, composed from the row's record (`specs/reason.md`).
    reason: Callable[
        [
            ProductQuery,
            RegistryLookupResult,
            Selection,
            ModulePrediction,
            CharacteristicValues,
            list[CandidateEvidence],
        ],
        Reasoning,
    ]


def offline_stages(
    index: RegistryIndex,
    thresholds: RegistryThresholds,
    classifier: ModuleClassifier,
    rules: list[CharacteristicRule],
    reason_config: ReasonConfig,
) -> Stages:
    """Stages with NO network: retrieval yields nothing, fetch and match are
    empty, characteristics is gate-only. Used by tests (`04` §6) and by a
    `--offline` run that exercises the resume path without spending search
    budget."""
    return Stages(
        normalize=normalize_row,
        registry=lambda query: lookup(query, index, thresholds),
        retrieve=lambda query: [],
        fetch=lambda candidates: [],
        match=lambda query, evidence: (_no_selection(), None),
        writeback=lambda query, best, module, values: False,
        classify=classifier.predict,
        characteristics=lambda query, module, evidence: gate_only(query.row_uid, module, rules),
        reason=lambda query, registry, selection, module, values, evidence: compose(
            query, registry, selection, module, values, evidence, reason_config
        ),
    )


def _no_selection() -> Selection:
    """The abstained Selection — `03` §3: `url is None` means abstained."""
    return Selection(
        url=None,
        page_title=None,
        confidence=0.0,
        runner_up_gap=0.0,
        features=None,
        adjudicated_by_llm=False,
        resolution_tier="tier2_retrieval",
        adjudication=None,
    )


def _module_from_hit(row_uid: str, result: RegistryLookupResult) -> ModulePrediction | None:
    """The stored module of a Tier 0/1 hit, or `None` when the entity has
    none — entities written before P12 carry `module=None` and fall through
    to the classifier rather than being served as an empty answer."""
    entity = result.entity
    if entity is None or entity.module is None:
        return None
    return ModulePrediction(
        row_uid=row_uid,
        module=entity.module,
        confidence=entity.confidence,
        runner_up=None,
        runner_up_gap=0.0,
        nearest_example_row_uid=None,
        nearest_example_similarity=0.0,
        source="registry",
    )


def _selection_from_hit(result: RegistryLookupResult) -> Selection:
    """A registry hit resolves identity without stages 2-4 (`03` §2).

    `features is None` — `03` §3: "None when resolved via registry hit".
    Confidence carries over from the stored entity, discounted for a Tier-1
    hit by whatever `03` §4 stage 1 step 3 asks for; at present the entity's
    own confidence is used, with the tier recorded so the discount can be
    applied downstream once calibration exists.
    """
    entity = result.entity
    assert entity is not None  # a hit always carries its entity
    tier = result.tier
    assert tier != "miss"
    return Selection(
        url=entity.resolved_url,
        page_title=entity.page_title,
        confidence=entity.confidence,
        runner_up_gap=0.0,
        features=None,
        adjudicated_by_llm=False,
        resolution_tier=tier,
        adjudication=None,
    )


def process_row(
    row: RawRow,
    stages: Stages,
    clock: Callable[[], datetime],
    abort_on: tuple[type[BaseException], ...] = (),
    rules: list[CharacteristicRule] | None = None,
) -> RowArtifacts | RowFailure:
    """Drive one row through every stage. Never raises for a per-row problem.

    The `stage` cursor advances as the row moves, so a `RowFailure` names the
    stage that actually raised rather than the last one anybody remembers —
    `04` §4 requires the stage on the record, and a wrong stage is worse than
    no stage because it sends the next person to the wrong module.

    **A registry hit skips retrieve, fetch and match** — `03` §2: "A registry
    hit at stage 1 skips stages 2–4 entirely; that skip is the whole point of
    §1a." The artifacts for those stages are written empty so the resume
    check still sees a complete row.
    """
    # Typed as the Literal rather than `str`, so mypy checks every
    # assignment to the cursor against the stage names `RowFailure`
    # accepts — a typo here would otherwise reach the record as data.
    stage: Literal[
        "normalize",
        "registry",
        "retrieve",
        "fetch",
        "match",
        "classify",
        "characteristics",
        "reason",
    ] = "normalize"
    candidates: list[CandidateURL] = []
    evidence: list[CandidateEvidence] = []
    best: ScoredCandidate | None = None
    wrote_back = False
    try:
        query = stages.normalize(row)
        stage = "registry"
        registry_result = stages.registry(query)
        if registry_result.hit:
            selection = _selection_from_hit(registry_result)
        else:
            stage = "retrieve"
            candidates = stages.retrieve(query)
            stage = "fetch"
            evidence = stages.fetch(candidates)
            stage = "match"
            selection, best = stages.match(query, evidence)
        stage = "classify"
        stored = _module_from_hit(row.row_uid, registry_result)
        prediction = stored if stored is not None else stages.classify(query)
        stage = "characteristics"
        entity = registry_result.entity
        if stored is not None and entity is not None and rules is not None:
            # `03` §4 stage 6, last paragraph: a registry hit carries the
            # stored values; the gate was applied when they were written.
            values = from_entity(row.row_uid, entity, rules)
        else:
            selected = next((item for item in evidence if item.url == selection.url), None)
            values = stages.characteristics(query, prediction.module, selected)
        if not registry_result.hit:
            # After classify + characteristics, so the entity carries both
            # (`specs/characteristics.md` §5). Still GTIN-accept only inside.
            wrote_back = stages.writeback(query, best, prediction.module, values)
        stage = "reason"
        reasoning = stages.reason(query, registry_result, selection, prediction, values, evidence)
    except Exception as error:  # noqa: BLE001 — `04` §4's one sanctioned site
        if isinstance(error, abort_on):
            # `05` §3: a spent LLM budget aborts the RUN with a clear failure.
            # Recording it as one more RowFailure and continuing would fail
            # every remaining row identically — a throttle in disguise.
            raise
        return RowFailure(
            row_uid=row.row_uid,
            stage=stage,
            error_type=type(error).__name__,
            message=str(error)[:MESSAGE_LIMIT],
            occurred_at=clock(),
        )
    return RowArtifacts(
        row_uid=row.row_uid,
        query=query,
        registry=registry_result,
        candidates=candidates,
        evidence=evidence,
        selection=selection,
        module=prediction,
        characteristics=values,
        reasoning=reasoning,
        wrote_back=wrote_back,
    )


def _persist(paths: RunPaths, artifacts: RowArtifacts) -> None:
    write_artifact(paths.artifacts, "normalize", artifacts.row_uid, artifacts.query)
    write_artifact(paths.artifacts, "registry", artifacts.row_uid, artifacts.registry)
    write_artifact(paths.artifacts, "retrieve", artifacts.row_uid, list(artifacts.candidates))
    write_artifact(paths.artifacts, "fetch", artifacts.row_uid, list(artifacts.evidence))
    write_artifact(paths.artifacts, "match", artifacts.row_uid, artifacts.selection)
    write_artifact(paths.artifacts, "classify", artifacts.row_uid, artifacts.module)
    write_artifact(paths.artifacts, "characteristics", artifacts.row_uid, artifacts.characteristics)
    write_artifact(paths.artifacts, "reason", artifacts.row_uid, artifacts.reasoning)


def _trace_record(artifacts: RowArtifacts, run_id: str, config_fingerprint: str) -> str:
    """One trace record per row — `04` §10, `03` §4 stage 8.

    Built as a dict and serialized, not by splicing text onto a serialized
    model. The earlier version did `model_dump_json()[:-1] + ',"run_id":...}'`,
    which works only while the model happens to serialize to something ending
    in `}` — a silent dependency on pydantic's output shape, in the one
    artifact downstream debugging actually reads.

    Deliberately carries no timestamp: `04` §5 requires a re-run to be
    byte-identical. `sort_keys` for the same reason.
    """
    record = {
        "row_uid": artifacts.row_uid,
        "run_id": run_id,
        "config_hash": config_fingerprint,
        "resolution_tier": _tier_of(artifacts.registry),
        "module": artifacts.module.module,
        "module_confidence": artifacts.module.confidence,
        "module_runner_up": artifacts.module.runner_up,
        "module_runner_up_gap": artifacts.module.runner_up_gap,
        "nearest_example_row_uid": artifacts.module.nearest_example_row_uid,
        "nearest_example_similarity": artifacts.module.nearest_example_similarity,
        "registry_hit": artifacts.registry.hit,
        "registry_similarity": artifacts.registry.similarity,
        "candidates": len(artifacts.candidates),
        "evidence_statuses": dict(Counter(item.fetch_status for item in artifacts.evidence)),
        "selected_url": artifacts.selection.url,
        "selected_confidence": artifacts.selection.confidence,
        "selected_runner_up_gap": artifacts.selection.runner_up_gap,
        "selected_calibrated_prob": (
            artifacts.selection.features.calibrated_prob
            if artifacts.selection.features is not None
            else None
        ),
        "selected_gtin_exact": (
            artifacts.selection.features.barcode_exact
            if artifacts.selection.features is not None
            else None
        ),
        "wrote_back": artifacts.wrote_back,
        "adjudicated_by_llm": artifacts.selection.adjudicated_by_llm,
        "module_source": artifacts.module.source,
        "characteristics_source": artifacts.characteristics.source,
        "characteristics_applicable": len(artifacts.characteristics.applicable),
        "characteristics_filled": sum(
            1 for value in artifacts.characteristics.values.values() if value is not None
        ),
        "characteristics_rejected": len(artifacts.characteristics.rejected),
        "reasoning_chars": len(artifacts.reasoning.text),
        "reasoning_claims": list(artifacts.reasoning.claims),
    }
    return json.dumps(record, sort_keys=True)


def _tier_of(result: RegistryLookupResult) -> str:
    """The tier that resolved this row. A registry miss means the row would
    fall through to retrieval — `tier2_retrieval` — which on a cold registry
    is every row, and that is the honest cold-start number for `03` §1a's
    efficiency claim rather than an embarrassing one."""
    return result.tier if result.hit else "tier2_retrieval"


@dataclass
class CacheCounter:
    """Hit/miss tally the network-backed stages update as they go, so
    `RunSummary` reports real numbers (`04` §10) rather than zeros."""

    hits: int = 0
    misses: int = 0


def run(
    rows: list[RawRow],
    stages: Stages,
    paths: RunPaths,
    run_id: str,
    clock: Callable[[], datetime] | None = None,
    cache_counter: CacheCounter | None = None,
    llm_counter: LlmCounter | None = None,
    abort_on: tuple[type[BaseException], ...] = (),
    rules: list[CharacteristicRule] | None = None,
) -> RunSummary:
    """Drive every row, skipping completed ones. Returns the run summary.

    A per-row failure never aborts this loop — 411 good rows are worth more
    than a clean traceback (`specs/run.md` §2). A *batch*-level failure (the
    workbook missing, the config invalid) is not caught here at all, because
    retrying it 412 times would print the same error 412 times.
    """
    tick = clock if clock is not None else lambda: datetime.now(UTC)
    started = time.monotonic()
    fingerprint = config_hash(paths.config_dir)

    already_done = completed_row_uids(paths.artifacts, [row.row_uid for row in rows])
    failures: list[RowFailure] = []
    tier_counts: Counter[str] = Counter()
    succeeded = 0
    writebacks = 0

    paths.trace.parent.mkdir(parents=True, exist_ok=True)
    trace_lines: list[str] = []

    for row in rows:
        if row.row_uid in already_done:
            succeeded += 1
            continue

        outcome = process_row(row, stages, tick, abort_on, rules)
        if isinstance(outcome, RowFailure):
            # `04` §4: a failed row writes NO artifacts. Not a partial set —
            # a later stage reading a half-populated one is how a plausible
            # wrong answer gets built.
            clear_artifacts(paths.artifacts, row.row_uid)
            failures.append(outcome)
            continue

        _persist(paths, outcome)
        trace_lines.append(_trace_record(outcome, run_id, fingerprint))
        tier_counts[_tier_of(outcome.registry)] += 1
        writebacks += int(outcome.wrote_back)
        succeeded += 1

    if trace_lines:
        with paths.trace.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(trace_lines) + "\n")
    if failures:
        paths.failures.parent.mkdir(parents=True, exist_ok=True)
        with paths.failures.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(failure.model_dump_json() for failure in failures) + "\n")

    return RunSummary(
        run_id=run_id,
        rows_total=len(rows),
        rows_succeeded=succeeded,
        rows_failed=len(failures),
        failures_by_stage=dict(Counter(failure.stage for failure in failures)),
        tier_counts=dict(tier_counts),
        # LLM counters are structurally zero until P11. Cache counters come
        # from the stage implementations via `cache_counter` when the caller
        # provides one; the offline stages have no cache to count.
        llm_calls=llm_counter.calls if llm_counter is not None else 0,
        llm_tokens=llm_counter.tokens if llm_counter is not None else 0,
        cache_hits=cache_counter.hits if cache_counter is not None else 0,
        cache_misses=cache_counter.misses if cache_counter is not None else 0,
        wall_time_s=time.monotonic() - started,
        config_hash=fingerprint,
    )


def format_summary(summary: RunSummary) -> str:
    """`04` §10: every run prints a summary."""
    lines = [
        f"run {summary.run_id}   config {summary.config_hash}",
        f"rows: {summary.rows_total}  succeeded: {summary.rows_succeeded}  "
        f"failed: {summary.rows_failed}",
    ]
    if summary.failures_by_stage:
        lines.append("failures by stage:")
        lines.extend(
            f"  {stage}: {count}" for stage, count in sorted(summary.failures_by_stage.items())
        )
    lines.append("resolution tiers:")
    lines.extend(f"  {tier}: {count}" for tier, count in sorted(summary.tier_counts.items()))
    lines.append(
        f"llm calls: {summary.llm_calls}  tokens: {summary.llm_tokens}  "
        f"(zero unless --adjudicate)   "
        f"page-cache hit/miss: {summary.cache_hits}/{summary.cache_misses}"
    )
    lines.append(f"wall time: {summary.wall_time_s:.1f}s")
    lines.append(f"stages driven: {' -> '.join(STAGE_SEQUENCE)}")
    return "\n".join(lines)
