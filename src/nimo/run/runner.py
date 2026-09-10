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

from nimo.classify.model import ModuleClassifier
from nimo.contracts import (
    ModulePrediction,
    ProductQuery,
    RawRow,
    RegistryLookupResult,
    RowFailure,
    RunSummary,
)
from nimo.normalize import normalize_row
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
    module: ModulePrediction


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
    classify: Callable[[ProductQuery], ModulePrediction]


def default_stages(
    index: RegistryIndex, thresholds: RegistryThresholds, classifier: ModuleClassifier
) -> Stages:
    return Stages(
        normalize=normalize_row,
        registry=lambda query: lookup(query, index, thresholds),
        classify=classifier.predict,
    )


def process_row(
    row: RawRow, stages: Stages, clock: Callable[[], datetime]
) -> RowArtifacts | RowFailure:
    """Drive one row through every stage. Never raises for a per-row problem.

    The `stage` cursor advances as the row moves, so a `RowFailure` names the
    stage that actually raised rather than the last one anybody remembers —
    `04` §4 requires the stage on the record, and a wrong stage is worse than
    no stage because it sends the next person to the wrong module.
    """
    # Typed as the Literal rather than `str`, so mypy checks every
    # assignment to the cursor against the stage names `RowFailure`
    # accepts — a typo here would otherwise reach the record as data.
    stage: Literal["normalize", "registry", "classify"] = "normalize"
    try:
        query = stages.normalize(row)
        stage = "registry"
        registry_result = stages.registry(query)
        stage = "classify"
        prediction = stages.classify(query)
    except Exception as error:  # noqa: BLE001 — `04` §4's one sanctioned site
        return RowFailure(
            row_uid=row.row_uid,
            stage=stage,
            error_type=type(error).__name__,
            message=str(error)[:MESSAGE_LIMIT],
            occurred_at=clock(),
        )
    return RowArtifacts(
        row_uid=row.row_uid, query=query, registry=registry_result, module=prediction
    )


def _persist(paths: RunPaths, artifacts: RowArtifacts) -> None:
    write_artifact(paths.artifacts, "normalize", artifacts.row_uid, artifacts.query)
    write_artifact(paths.artifacts, "registry", artifacts.row_uid, artifacts.registry)
    write_artifact(paths.artifacts, "classify", artifacts.row_uid, artifacts.module)


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
    }
    return json.dumps(record, sort_keys=True)


def _tier_of(result: RegistryLookupResult) -> str:
    """The tier that resolved this row. A registry miss means the row would
    fall through to retrieval — `tier2_retrieval` — which on a cold registry
    is every row, and that is the honest cold-start number for `03` §1a's
    efficiency claim rather than an embarrassing one."""
    return result.tier if result.hit else "tier2_retrieval"


def run(
    rows: list[RawRow],
    stages: Stages,
    paths: RunPaths,
    run_id: str,
    clock: Callable[[], datetime] | None = None,
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

    paths.trace.parent.mkdir(parents=True, exist_ok=True)
    trace_lines: list[str] = []

    for row in rows:
        if row.row_uid in already_done:
            succeeded += 1
            continue

        outcome = process_row(row, stages, tick)
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
        # Structurally zero at P6a — no LLM client, no fetch cache. Reported
        # rather than omitted so the fields are wired end to end before the
        # phases that populate them arrive (`04` §10, `specs/run.md` §6).
        llm_calls=0,
        llm_tokens=0,
        cache_hits=0,
        cache_misses=0,
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
        f"cache hit/miss: {summary.cache_hits}/{summary.cache_misses}  "
        f"(all structurally zero until P8/P11)"
    )
    lines.append(f"wall time: {summary.wall_time_s:.1f}s")
    lines.append(f"stages driven: {' -> '.join(STAGE_SEQUENCE)}")
    return "\n".join(lines)
