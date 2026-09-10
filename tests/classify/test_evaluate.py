"""P5 evaluation tests — `specs/classify.md` §7, §10.

Includes the phase's regression guard against the real 412-row `dev` sheet.
No network, no LLM (`04` §6).
"""

from pathlib import Path

import pytest

from nimo.classify import (
    ClassifyConfig,
    EvaluationError,
    ModuleClassifier,
    build_report,
    cross_validate,
    format_report,
    load_classify_config,
    stratified_folds,
)
from nimo.contracts import ModulePrediction, ProductQuery
from nimo.loader import load_characteristic_rules, load_module_labels, load_rows
from nimo.normalize import normalize_rows

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
RETAILERS = REPO_ROOT / "config" / "retailers.yaml"

# --- The pinned regression figures -------------------------------------------
#
# Deterministic module-stratified 5-fold over all 412 real `dev` rows with the
# committed config. Treated like the loader's `EXPECTED_*` fingerprints: a
# change here is a real behavioral change to investigate, not a number to
# quietly update (`specs/classify.md` §9 criterion 4).
#
# Leave-one-out — the number `04` §1's P5 gate reports — is 331/412 = 80.3%
# overall and 49.7% macro. It is deliberately NOT asserted here: 412 fits take
# about a minute, which would make `make check` five times slower for every
# future phase. Reproduce it with `uv run python -m nimo.classify`.
EXPECTED_5FOLD_CORRECT = 323  # 78.4%
EXPECTED_5FOLD_MACRO_FLOOR = 0.47  # measured 48.1%
EXPECTED_DEV_MODULES = 27  # `01` §9 — of 59 defined


@pytest.fixture(scope="module")
def config() -> ClassifyConfig:
    return load_classify_config()


@pytest.fixture(scope="module")
def dev_data() -> tuple[list[ProductQuery], list[str]]:
    rules = load_characteristic_rules(WORKBOOK)
    queries = normalize_rows(load_rows(WORKBOOK, "dev", RETAILERS))
    return queries, load_module_labels(WORKBOOK, "dev", rules)


# --- loader ground truth -----------------------------------------------------


def test_module_labels_align_with_rows(dev_data: tuple[list[ProductQuery], list[str]]) -> None:
    queries, labels = dev_data
    assert len(labels) == len(queries) == 412


def test_module_labels_are_all_in_the_closed_set(
    dev_data: tuple[list[ProductQuery], list[str]],
) -> None:
    """`05` §5's silent-schema-drift guardrail, applied to the labels."""
    _, labels = dev_data
    known = {rule.module for rule in load_characteristic_rules(WORKBOOK)}
    assert set(labels) <= known
    assert len(set(labels)) == EXPECTED_DEV_MODULES


# --- fold assignment ---------------------------------------------------------


def test_folds_are_module_stratified_and_deterministic() -> None:
    labels = ["A"] * 10 + ["B"] * 5
    first = stratified_folds(labels, 5)
    assert first == stratified_folds(labels, 5)
    for module in ("A", "B"):
        assigned = [f for f, m in zip(first, labels, strict=True) if m == module]
        assert (
            max(assigned.count(fold) for fold in range(5))
            - min(assigned.count(fold) for fold in range(5))
            <= 1
        )


def test_folds_reject_k_below_two() -> None:
    with pytest.raises(EvaluationError, match="at least 2"):
        stratified_folds(["A", "B"], 1)


def test_a_single_row_module_lands_in_exactly_one_fold() -> None:
    """Four `dev` modules have one row. Under any held-out protocol that row
    trains on zero examples of its own class — structurally unpredictable, and
    reported as 0% rather than hidden (`specs/classify.md` §2)."""
    folds = stratified_folds(["A"] * 9 + ["SINGLETON"], 5)
    assert folds[-1] == 0


# --- report construction -----------------------------------------------------


def _prediction(row_uid: str, module: str, confidence: float) -> ModulePrediction:
    return ModulePrediction(
        row_uid=row_uid,
        module=module,
        confidence=confidence,
        runner_up=None,
        runner_up_gap=0.0,
        nearest_example_row_uid=None,
        nearest_example_similarity=0.0,
        source="text_baseline",
    )


def test_report_counts_and_macro_are_correct() -> None:
    predictions = [
        _prediction("dev:0", "BIG", 0.9),
        _prediction("dev:1", "BIG", 0.8),
        _prediction("dev:2", "BIG", 0.7),
        _prediction("dev:3", "BIG", 0.6),
    ]
    labels = ["BIG", "BIG", "BIG", "SMALL"]
    report = build_report("toy", predictions, labels)
    assert report.overall_accuracy == pytest.approx(0.75)
    # BIG 3/3, SMALL 0/1 -> macro 50%, which is the whole point of macro:
    # 75% overall hides a module the classifier never gets right.
    assert report.macro_accuracy == pytest.approx(0.5)
    assert report.confusions == [("SMALL", "BIG", 1)]


def test_report_includes_every_module_including_zero_scoring_ones() -> None:
    report = build_report(
        "toy",
        [_prediction("dev:0", "A", 0.5), _prediction("dev:1", "A", 0.4)],
        ["A", "B"],
    )
    assert {entry.module for entry in report.per_module} == {"A", "B"}
    assert [entry for entry in report.per_module if entry.module == "B"][0].accuracy == 0.0


def test_report_rejects_misaligned_input() -> None:
    with pytest.raises(EvaluationError, match="positionally aligned"):
        build_report("toy", [_prediction("dev:0", "A", 0.5)], ["A", "B"])


def test_report_rejects_zero_predictions() -> None:
    with pytest.raises(EvaluationError, match="zero predictions"):
        build_report("toy", [], [])


# --- the real-data regression guard ------------------------------------------


def test_five_fold_reproduces_its_pinned_figures(
    dev_data: tuple[list[ProductQuery], list[str]], config: ClassifyConfig
) -> None:
    """The P5 gate's fast guard. Exact, not a floor: this is deterministic —
    no RNG, no shuffle, no seed — so any movement is a real change.

    If this fails, do not edit the constant to match. Find out what changed:
    the normalizer, the config, the workbook, or the model.
    """
    queries, labels = dev_data
    report = build_report("5-fold", cross_validate(queries, labels, config, 5), labels)
    assert report.correct == EXPECTED_5FOLD_CORRECT
    assert report.macro_accuracy >= EXPECTED_5FOLD_MACRO_FLOOR
    assert len(report.per_module) == EXPECTED_DEV_MODULES


def test_five_fold_is_reproducible_across_runs(
    dev_data: tuple[list[ProductQuery], list[str]], config: ClassifyConfig
) -> None:
    queries, labels = dev_data
    first = cross_validate(queries, labels, config, 5)
    second = cross_validate(queries, labels, config, 5)
    assert first == second


def test_every_prediction_cites_a_real_training_row(
    dev_data: tuple[list[ProductQuery], list[str]], config: ClassifyConfig
) -> None:
    queries, labels = dev_data
    classifier = ModuleClassifier.fit(queries[:100], labels[:100], config)
    known = {query.row_uid for query in queries[:100]}
    for query in queries[100:120]:
        prediction = classifier.predict(query)
        assert prediction.nearest_example_row_uid in known
        assert prediction.module in classifier.modules


def test_formatted_report_leads_with_macro_and_lists_the_tail(
    dev_data: tuple[list[ProductQuery], list[str]], config: ClassifyConfig
) -> None:
    """`01` §9: the top 4 modules are 77% of dev. A report whose headline is
    overall accuracy makes the other 23 module types invisible."""
    queries, labels = dev_data
    text = format_report(build_report("5-fold", cross_validate(queries, labels, config, 5), labels))
    assert "headline" in text.split("\n")[1]
    assert "macro" in text.split("\n")[1]
    assert "TOOTH STAIN REMOVERS - STRIPS/TRAYS/WIPES" in text  # a 1-row module
