"""P6a runner tests — `specs/run.md` §7, §9.

The failing-row test is the phase: `04` §4's two hardest rules are that one
bad row does not abort the run and that a failed row never leaves partial
state behind.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nimo.classify import load_classify_config
from nimo.classify.model import ModuleClassifier
from nimo.contracts import ProductQuery, RawRow, RegistryLookupResult, RowFailure
from nimo.loader import load_characteristic_rules, load_module_labels, load_rows
from nimo.normalize import normalize_row, normalize_rows
from nimo.registry import build_index, fit_identity_idf, load_thresholds, lookup
from nimo.run import (
    STAGE_SEQUENCE,
    RunPaths,
    Stages,
    artifact_filename,
    artifact_path,
    config_hash,
    format_summary,
    is_row_complete,
    process_row,
    run,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
CONFIG_DIR = REPO_ROOT / "config"
RETAILERS = CONFIG_DIR / "retailers.yaml"

FIXED_TS = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


def fixed_clock() -> datetime:
    return FIXED_TS


@pytest.fixture(scope="module")
def dev_rows() -> list[RawRow]:
    return load_rows(WORKBOOK, "dev", RETAILERS)


@pytest.fixture(scope="module")
def stages(dev_rows: list[RawRow]) -> Stages:
    queries = normalize_rows(dev_rows)
    rules = load_characteristic_rules(WORKBOOK)
    classifier = ModuleClassifier.fit(
        queries, load_module_labels(WORKBOOK, "dev", rules), load_classify_config()
    )
    index = build_index([], fit_identity_idf(queries))
    thresholds = load_thresholds()
    return Stages(
        normalize=normalize_row,
        registry=lambda query: lookup(query, index, thresholds),
        classify=classifier.predict,
    )


def paths_in(tmp_path: Path) -> RunPaths:
    return RunPaths(
        artifacts=tmp_path / "artifacts",
        trace=tmp_path / "trace.jsonl",
        failures=tmp_path / "failures.jsonl",
        config_dir=CONFIG_DIR,
    )


# --- filenames ---------------------------------------------------------------


def test_row_uid_is_sanitized_for_the_filename_only() -> None:
    """`:` is not a legal filename character on Windows. Unsanitized it is a
    mid-run crash rather than a design discussion (`specs/run.md` §3)."""
    assert artifact_filename("dev:0") == "dev-0.json"
    assert ":" not in str(artifact_path(Path("/tmp"), "normalize", "dev:0").name)


def test_row_uid_survives_the_filename_round_trip(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    paths = paths_in(tmp_path)
    run(dev_rows[:1], stages, paths, "run-1", fixed_clock)
    written = artifact_path(paths.artifacts, "normalize", "dev:0")
    assert written.name == "dev-0.json"
    assert '"row_uid":"dev:0"' in written.read_text(encoding="utf-8")


# --- the failing row ---------------------------------------------------------


def exploding(stage: str, base: Stages) -> Stages:
    """A `Stages` whose one named stage raises for `dev:3`."""

    def blow_up_on_target(inner: Callable[..., object], target: str) -> Callable[..., object]:
        def wrapper(value: RawRow | ProductQuery) -> object:
            if value.row_uid == target:
                raise RuntimeError("deliberate failure for the P6a gate")
            return inner(value)

        return wrapper

    replacements = {
        "normalize": lambda: Stages(
            normalize=blow_up_on_target(base.normalize, "dev:3"),  # type: ignore[arg-type]
            registry=base.registry,
            classify=base.classify,
        ),
        "registry": lambda: Stages(
            normalize=base.normalize,
            registry=blow_up_on_target(base.registry, "dev:3"),  # type: ignore[arg-type]
            classify=base.classify,
        ),
        "classify": lambda: Stages(
            normalize=base.normalize,
            registry=base.registry,
            classify=blow_up_on_target(base.classify, "dev:3"),  # type: ignore[arg-type]
        ),
    }
    return replacements[stage]()


def test_a_failing_row_is_typed_does_not_abort_and_leaves_nothing_behind(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """**This test is the phase.** `04` §4's two hardest rules at once."""
    paths = paths_in(tmp_path)
    rows = dev_rows[:10]
    summary = run(rows, exploding("classify", stages), paths, "run-1", fixed_clock)

    assert summary.rows_failed == 1
    assert summary.rows_succeeded == 9
    assert summary.failures_by_stage == {"classify": 1}

    # ...and the failed row left no artifacts at all, not a partial set.
    for stage in STAGE_SEQUENCE:
        assert not artifact_path(paths.artifacts, stage, "dev:3").exists()
    assert not is_row_complete(paths.artifacts, "dev:3")

    # ...while every other row completed.
    for row in rows:
        if row.row_uid != "dev:3":
            assert is_row_complete(paths.artifacts, row.row_uid)

    recorded = paths.failures.read_text(encoding="utf-8").strip().splitlines()
    assert len(recorded) == 1
    failure = RowFailure.model_validate_json(recorded[0])
    assert failure.row_uid == "dev:3"
    assert failure.stage == "classify"
    assert failure.error_type == "RuntimeError"
    assert "deliberate failure" in failure.message


@pytest.mark.parametrize("stage", ["normalize", "registry", "classify"])
def test_failure_is_attributed_to_the_stage_that_actually_raised(
    stage: str, dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """A wrong stage on the record is worse than no stage — it sends the next
    person to the wrong module."""
    summary = run(dev_rows[:5], exploding(stage, stages), paths_in(tmp_path), "r", fixed_clock)
    assert summary.failures_by_stage == {stage: 1}


def test_process_row_never_raises_for_a_per_row_problem(
    dev_rows: list[RawRow], stages: Stages
) -> None:
    broken = exploding("registry", stages)
    outcome = process_row(dev_rows[3], broken, fixed_clock)
    assert isinstance(outcome, RowFailure)
    assert outcome.occurred_at == FIXED_TS


# --- resume ------------------------------------------------------------------


def test_resume_skips_completed_rows_without_re_running_them(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """Counts work, not wall time (`specs/run.md` §9)."""
    paths = paths_in(tmp_path)
    rows = dev_rows[:8]
    run(rows, stages, paths, "run-1", fixed_clock)

    calls: list[str] = []

    def counting(query: ProductQuery) -> RegistryLookupResult:
        calls.append(query.row_uid)
        return stages.registry(query)

    counted = Stages(normalize=stages.normalize, registry=counting, classify=stages.classify)
    summary = run(rows, counted, paths, "run-2", fixed_clock)

    assert calls == []
    assert summary.rows_succeeded == 8
    assert summary.rows_failed == 0


def test_a_partially_written_row_is_re_run_not_trusted(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """Partial state is never trusted — the run that produced it was
    interrupted for a reason nobody recorded."""
    paths = paths_in(tmp_path)
    rows = dev_rows[:4]
    run(rows, stages, paths, "run-1", fixed_clock)
    artifact_path(paths.artifacts, "classify", "dev:2").unlink()
    assert not is_row_complete(paths.artifacts, "dev:2")

    calls: list[str] = []

    def counting(query: ProductQuery) -> RegistryLookupResult:
        calls.append(query.row_uid)
        return stages.registry(query)

    run(rows, Stages(stages.normalize, counting, stages.classify), paths, "run-2", fixed_clock)
    assert calls == ["dev:2"]
    assert is_row_complete(paths.artifacts, "dev:2")


def test_a_second_full_run_does_no_work_and_changes_no_bytes(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """`04` §5: a re-run with no change produces byte-identical output."""
    paths = paths_in(tmp_path)
    rows = dev_rows[:6]
    run(rows, stages, paths, "run-1", fixed_clock)
    before = {path.name: path.read_bytes() for path in sorted(paths.artifacts.rglob("*.json"))}
    run(rows, stages, paths, "run-2", fixed_clock)
    after = {path.name: path.read_bytes() for path in sorted(paths.artifacts.rglob("*.json"))}
    assert before == after


# --- summary and config hash -------------------------------------------------


def test_summary_numbers_add_up(dev_rows: list[RawRow], stages: Stages, tmp_path: Path) -> None:
    summary = run(
        dev_rows[:10], exploding("registry", stages), paths_in(tmp_path), "r", fixed_clock
    )
    assert summary.rows_succeeded + summary.rows_failed == summary.rows_total == 10
    assert sum(summary.failures_by_stage.values()) == summary.rows_failed
    assert sum(summary.tier_counts.values()) == summary.rows_succeeded


def test_a_cold_registry_reports_every_row_as_tier2(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """The honest cold-start number for `03` §1a's efficiency claim."""
    summary = run(dev_rows[:10], stages, paths_in(tmp_path), "r", fixed_clock)
    assert summary.tier_counts == {"tier2_retrieval": 10}


def test_llm_and_cache_counters_are_reported_as_zero_not_omitted(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """Wired end to end before the phases that populate them (`04` §10)."""
    summary = run(dev_rows[:2], stages, paths_in(tmp_path), "r", fixed_clock)
    assert (summary.llm_calls, summary.llm_tokens) == (0, 0)
    assert (summary.cache_hits, summary.cache_misses) == (0, 0)
    assert "structurally zero" in format_summary(summary)


def test_config_hash_is_stable_and_content_addressed(tmp_path: Path) -> None:
    """`05` §5. Hashes contents, not mtimes — a checkout changes mtimes
    without changing behavior, and a hash that moves for no reason teaches
    people to ignore it."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "a.yaml").write_text("x: 1\n", encoding="utf-8")
    first = config_hash(config)
    assert first == config_hash(config)

    (config / "a.yaml").write_text("x: 2\n", encoding="utf-8")
    assert config_hash(config) != first


def test_the_real_config_directory_hashes() -> None:
    assert config_hash(CONFIG_DIR).startswith("sha256:")


# --- `04` §4's one-broad-except rule -----------------------------------------


def test_only_one_broad_except_exists_in_src() -> None:
    """`04` §4 forbids `except Exception` without a typed failure record, and
    `04` §12 lists it as a forbidden pattern. The runner is the single
    sanctioned site; this fails if a second one appears anywhere."""
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src").rglob("*.py")
        if re.search(r"except\s+(Exception|BaseException)?\s*:", path.read_text(encoding="utf-8"))
        or "except Exception as" in path.read_text(encoding="utf-8")
    ]
    assert offenders == ["src/nimo/run/runner.py"], (
        f"`04` §4 allows exactly one broad except, in the runner, paired with a typed "
        f"RowFailure. Found: {offenders}"
    )
