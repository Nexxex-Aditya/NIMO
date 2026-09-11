"""P6a runner tests — `specs/run.md` §7, §9.

The failing-row test is the phase: `04` §4's two hardest rules are that one
bad row does not abort the run and that a failed row never leaves partial
state behind.
"""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nimo.characteristics import CHARACTERISTIC_COLUMNS
from nimo.classify import load_classify_config
from nimo.classify.model import ModuleClassifier
from nimo.contracts import (
    CandidateEvidence,
    CandidateURL,
    CanonicalEntity,
    CharacteristicValues,
    ProductQuery,
    RawRow,
    RegistryLookupResult,
    RowFailure,
)
from nimo.loader import load_characteristic_rules, load_module_labels, load_rows
from nimo.match import ScoredCandidate
from nimo.normalize import normalize_rows
from nimo.reason import load_reason_config
from nimo.registry import build_index, fit_identity_idf, load_thresholds
from nimo.run import (
    STAGE_SEQUENCE,
    RunPaths,
    Stages,
    artifact_filename,
    artifact_path,
    config_hash,
    format_summary,
    is_row_complete,
    offline_stages,
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
    return offline_stages(index, load_thresholds(), classifier, rules, load_reason_config())


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
    """A `Stages` whose one named stage raises for `dev:3`.

    Built with `dataclasses.replace` over the base so adding a stage to
    `Stages` cannot silently leave this helper covering only the old ones —
    the parametrized test below names every stage in `STAGE_SEQUENCE`.
    """

    def blow_up_on_target(inner: Callable[..., object], target: str) -> Callable[..., object]:
        def wrapper(*args: object) -> object:
            first = args[0]
            uid = getattr(first, "row_uid", None)
            if uid is None and isinstance(first, list):
                # retrieve/fetch receive lists; the target is carried by the
                # query on the previous stage, so key on the second argument
                # (match) or fall through for candidate lists.
                uid = getattr(args[1], "row_uid", None) if len(args) > 1 else None
            if uid == target:
                raise RuntimeError("deliberate failure for the P6a gate")
            return inner(*args)

        return wrapper

    def blow_up_fetch(target: str) -> Callable[[list[object]], list[object]]:
        # fetch takes only the candidate list; the offline base returns [] so
        # this stage raises for EVERY row unless we key it by a marker. Use the
        # runner's own ordering: a fetch failure on the fourth row is dev:3.
        seen: list[int] = []

        def wrapper(candidates: list[object]) -> list[object]:
            seen.append(1)
            if len(seen) == 4:  # dev:3 is the fourth of dev_rows[:10]
                raise RuntimeError("deliberate failure for the P6a gate")
            return []

        return wrapper

    if stage == "fetch":
        return replace(base, fetch=blow_up_fetch("dev:3"))  # type: ignore[arg-type]
    if stage == "match":

        def match_wrapper(query: ProductQuery, evidence: list[object]) -> object:
            if query.row_uid == "dev:3":
                raise RuntimeError("deliberate failure for the P6a gate")
            return base.match(query, evidence)  # type: ignore[arg-type]

        return replace(base, match=match_wrapper)  # type: ignore[arg-type]
    return replace(base, **{stage: blow_up_on_target(getattr(base, stage), "dev:3")})  # type: ignore[arg-type]


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


@pytest.mark.parametrize("stage", list(STAGE_SEQUENCE))
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


# --- P12: the seventh stage, write-back after it, the registry hit path ------------


def test_write_back_receives_the_module_and_the_characteristics(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """`specs/characteristics.md` §5: write-back runs AFTER classify and
    characteristics so the entity can carry both. The stub records what it
    was handed."""
    received: list[tuple[str | None, str]] = []

    def recording(
        query: ProductQuery,
        best: ScoredCandidate | None,
        module: str | None,
        values: CharacteristicValues | None,
    ) -> bool:
        assert values is not None
        received.append((module, values.source))
        return False

    run(dev_rows[:3], replace(stages, writeback=recording), paths_in(tmp_path), "r", fixed_clock)
    assert len(received) == 3
    assert all(module is not None and source == "gate_only" for module, source in received)


def test_a_registry_hit_with_a_stored_module_skips_classify_and_extraction(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """`03` §4 stage 6, last paragraph: a Tier 0/1 hit carries the stored
    module and values; neither the classifier nor the extractor runs."""
    entity = CanonicalEntity(
        entity_id="gtin:test",
        barcode="5014697056627",
        brand="AQUAFRESH",
        size_ml_equiv=100.0,
        size_g_equiv=None,
        count=1,
        variant_terms=["whitening"],
        module="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
        resolved_url="https://boots.com/p",
        page_title="p",
        characteristics={"GLOBAL_IF_WITH_FLUORIDE": "WITH FLUORIDE"},
        confidence=1.0,
        member_row_uids=["qa:5"],
        resolution_tier="tier2_retrieval",
        created_at=FIXED_TS,
        updated_at=FIXED_TS,
    )
    hit = RegistryLookupResult(hit=True, tier="tier0_exact", entity=entity, similarity=None)
    classified: list[str] = []
    extracted: list[str] = []

    def classify(query: ProductQuery) -> object:
        classified.append(query.row_uid)
        return stages.classify(query)

    def characteristics(query: ProductQuery, module: str | None, evidence: object) -> object:
        extracted.append(query.row_uid)
        return stages.characteristics(query, module, None)

    hitting = replace(
        stages,
        registry=lambda query: hit,
        classify=classify,  # type: ignore[arg-type]
        characteristics=characteristics,  # type: ignore[arg-type]
    )
    rules = load_characteristic_rules(WORKBOOK)
    paths = paths_in(tmp_path)
    summary = run(dev_rows[:1], hitting, paths, "r", fixed_clock, rules=rules)
    assert summary.rows_succeeded == 1 and classified == [] and extracted == []
    module = artifact_path(paths.artifacts, "classify", "dev:0").read_text(encoding="utf-8")
    values = artifact_path(paths.artifacts, "characteristics", "dev:0").read_text(encoding="utf-8")
    assert '"source":"registry"' in module and '"source":"registry"' in values
    assert '"GLOBAL_IF_WITH_FLUORIDE":"WITH FLUORIDE"' in values


def test_a_registry_hit_without_a_stored_module_falls_through_to_the_classifier(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """Entities written before P12 carry `module=None`; they must not be
    served as an empty answer."""
    entity = CanonicalEntity(
        entity_id="gtin:old",
        barcode="5014697056627",
        brand="AQUAFRESH",
        size_ml_equiv=100.0,
        size_g_equiv=None,
        count=1,
        variant_terms=["whitening"],
        module=None,
        resolved_url="https://boots.com/p",
        page_title="p",
        characteristics={},
        confidence=1.0,
        member_row_uids=["qa:5"],
        resolution_tier="tier2_retrieval",
        created_at=FIXED_TS,
        updated_at=FIXED_TS,
    )
    hit = RegistryLookupResult(hit=True, tier="tier0_exact", entity=entity, similarity=None)
    paths = paths_in(tmp_path)
    fetched: list[list[str]] = []
    refreshed: list[tuple[str, str | None, str]] = []

    def fetch(candidates: list[CandidateURL]) -> list[CandidateEvidence]:
        fetched.append([c.url for c in candidates])
        return []

    def refresh(
        query: ProductQuery,
        found: CanonicalEntity,
        module: str | None,
        values: CharacteristicValues,
    ) -> bool:
        refreshed.append((found.entity_id, module, values.source))
        return True

    run(
        dev_rows[:1],
        replace(stages, registry=lambda query: hit, fetch=fetch, refresh=refresh),
        paths,
        "r",
        fixed_clock,
    )
    module = artifact_path(paths.artifacts, "classify", "dev:0").read_text(encoding="utf-8")
    assert '"source":"text_baseline"' in module
    # the entity's own page was fetched for evidence — one URL, no search —
    # and the classified module was offered back to the entity
    assert fetched == [["https://boots.com/p"]]
    assert len(refreshed) == 1 and refreshed[0][0] == "gtin:old"
    assert refreshed[0][1] is not None and refreshed[0][2] == "gate_only"
    trace = paths.trace.read_text(encoding="utf-8")
    assert '"wrote_back": true' in trace


def _valued(row_uid: str, module: str | None) -> CharacteristicValues:
    """What an extractor returns: one model-sourced value."""
    values: dict[str, str | None] = {name: None for name in CHARACTERISTIC_COLUMNS}
    values["GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS"] = "NOT STATED"
    return CharacteristicValues(
        row_uid=row_uid,
        module=module,
        values=values,
        applicable=["GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS"],
        rejected={},
        source="llm",
        prompt_hash="p",
        model="m",
    )


def test_a_hit_on_an_entity_without_values_extracts_and_refreshes_when_the_run_extracts(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """Measured 2026-09-12: the gate-only registry rebuild left every entity
    with a module and no values, and the office run served those 111 rows
    EMPTY. In a run that extracts values, such a hit is incomplete: fetch
    the entity's own page, extract, refresh the entity with the values."""
    entity = CanonicalEntity(
        entity_id="gtin:module-only",
        barcode="5014697056627",
        brand="AQUAFRESH",
        size_ml_equiv=100.0,
        size_g_equiv=None,
        count=1,
        variant_terms=["whitening"],
        module="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
        resolved_url="https://boots.com/p",
        page_title="p",
        characteristics={},
        confidence=1.0,
        member_row_uids=["qa:5"],
        resolution_tier="tier2_retrieval",
        created_at=FIXED_TS,
        updated_at=FIXED_TS,
    )
    hit = RegistryLookupResult(hit=True, tier="tier0_exact", entity=entity, similarity=None)
    touched: list[str] = []
    refreshed: list[CharacteristicValues] = []

    def refresh(
        query: ProductQuery,
        found: CanonicalEntity,
        module: str | None,
        values: CharacteristicValues,
    ) -> bool:
        refreshed.append(values)
        return True

    extracting = replace(
        stages,
        registry=lambda query: hit,
        fetch=lambda candidates: touched.append(candidates[0].url) or [],  # type: ignore[func-returns-value]
        characteristics=lambda query, module, evidence: _valued(query.row_uid, module),
        refresh=refresh,
        extracts_values=True,
    )
    paths = paths_in(tmp_path)
    summary = run(
        dev_rows[:1], extracting, paths, "r", fixed_clock, rules=load_characteristic_rules(WORKBOOK)
    )
    assert summary.rows_succeeded == 1
    assert touched == ["https://boots.com/p"]  # the entity's own page, one URL
    assert len(refreshed) == 1 and refreshed[0].source == "llm"
    written = artifact_path(paths.artifacts, "characteristics", "dev:0").read_text(encoding="utf-8")
    assert '"source":"llm"' in written and '"NOT STATED"' in written
    module = artifact_path(paths.artifacts, "classify", "dev:0").read_text(encoding="utf-8")
    assert '"source":"registry"' in module  # the stored module is still trusted


def test_a_hit_on_an_entity_with_values_is_served_even_when_the_run_extracts(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    entity = CanonicalEntity(
        entity_id="gtin:valued",
        barcode="5014697056627",
        brand="AQUAFRESH",
        size_ml_equiv=100.0,
        size_g_equiv=None,
        count=1,
        variant_terms=["whitening"],
        module="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
        resolved_url="https://boots.com/p",
        page_title="p",
        characteristics={"GLOBAL_IF_WITH_FLUORIDE": "WITH FLUORIDE"},
        confidence=1.0,
        member_row_uids=["qa:5"],
        resolution_tier="tier2_retrieval",
        created_at=FIXED_TS,
        updated_at=FIXED_TS,
    )
    hit = RegistryLookupResult(hit=True, tier="tier0_exact", entity=entity, similarity=None)
    touched: list[str] = []

    def extract(query: ProductQuery, module: str | None, evidence: object) -> CharacteristicValues:
        touched.append("extract")
        return _valued(query.row_uid, module)

    run(
        dev_rows[:1],
        replace(
            stages,
            registry=lambda query: hit,
            fetch=lambda candidates: touched.append("fetch") or [],  # type: ignore[func-returns-value]
            characteristics=extract,
            refresh=lambda query, found, module, values: touched.append("refresh") or True,  # type: ignore[func-returns-value]
            extracts_values=True,
        ),
        paths_in(tmp_path),
        "r",
        fixed_clock,
        rules=load_characteristic_rules(WORKBOOK),
    )
    assert touched == []


def test_a_complete_entity_hit_neither_fetches_nor_refreshes(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """A gate-only run (`extracts_values=False`) cannot complete an entity,
    so it does not try: no fetch, no refresh, values from the entity."""
    entity = CanonicalEntity(
        entity_id="gtin:done",
        barcode="5014697056627",
        brand="AQUAFRESH",
        size_ml_equiv=100.0,
        size_g_equiv=None,
        count=1,
        variant_terms=["whitening"],
        module="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
        resolved_url="https://boots.com/p",
        page_title="p",
        characteristics={},
        confidence=1.0,
        member_row_uids=["qa:5"],
        resolution_tier="tier2_retrieval",
        created_at=FIXED_TS,
        updated_at=FIXED_TS,
    )
    hit = RegistryLookupResult(hit=True, tier="tier0_exact", entity=entity, similarity=None)
    touched: list[str] = []
    run(
        dev_rows[:1],
        replace(
            stages,
            registry=lambda query: hit,
            fetch=lambda candidates: touched.append("fetch") or [],  # type: ignore[func-returns-value]
            refresh=lambda query, found, module, values: touched.append("refresh") or True,  # type: ignore[func-returns-value]
        ),
        paths_in(tmp_path),
        "r",
        fixed_clock,
        rules=load_characteristic_rules(WORKBOOK),
    )
    assert touched == []


def test_resume_re_runs_rows_whose_values_were_never_extracted(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """A tree written gate-only is complete for a gate-only run and STALE for
    a run that extracts values; an `llm`-sourced row is complete for both."""
    paths = paths_in(tmp_path)
    rows = dev_rows[:4]
    run(rows, stages, paths, "gate-only", fixed_clock)  # every row gate_only

    asked: list[str] = []

    def extracting(
        query: ProductQuery, module: str | None, evidence: object
    ) -> CharacteristicValues:
        asked.append(query.row_uid)
        return _valued(query.row_uid, module)

    with_model = replace(stages, characteristics=extracting, extracts_values=True)
    summary = run(rows, with_model, paths, "with-model", fixed_clock)
    assert summary.rows_succeeded == 4
    assert asked == [row.row_uid for row in rows]  # all four re-run

    asked.clear()
    run(rows, with_model, paths, "again", fixed_clock)
    assert asked == []  # now llm-sourced: complete, skipped

    # And a gate-only run over the llm-sourced tree skips them too — it
    # cannot improve on them (`extracts_values=False` parses nothing).
    counted: list[str] = []

    def counting(query: ProductQuery) -> RegistryLookupResult:
        counted.append(query.row_uid)
        return stages.registry(query)

    run(rows, replace(stages, registry=counting), paths, "gate-again", fixed_clock)
    assert counted == []


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

    counted = replace(stages, registry=counting)
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

    run(rows, replace(stages, registry=counting), paths, "run-2", fixed_clock)
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
    """Wired end to end (`04` §10); offline stages make no LLM call and hit
    no cache, and the summary says so rather than omitting the fields."""
    summary = run(dev_rows[:2], stages, paths_in(tmp_path), "r", fixed_clock)
    assert (summary.llm_calls, summary.llm_tokens) == (0, 0)
    assert (summary.cache_hits, summary.cache_misses) == (0, 0)
    assert "llm calls: 0" in format_summary(summary)


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
