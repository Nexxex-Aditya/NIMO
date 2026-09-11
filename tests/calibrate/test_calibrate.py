"""P10 calibration tests — `specs/calibrate.md` §7. HARD-20% (`04` §13).

The PAV fit is checked against hand-worked cases, because a wrong isotonic
fit still produces monotone, plausible-looking probabilities — exactly the
failure a test has to be able to see.
"""

from pathlib import Path

import pytest

from nimo.calibrate import (
    CalibrationError,
    LabelledPair,
    build_report,
    fit_isotonic,
    format_report,
    read_pairs,
    write_pairs,
)

# --- pool-adjacent-violators, worked by hand ---------------------------------


def test_already_monotone_data_is_returned_as_is() -> None:
    """[0,0,1,1] in score order: no violations, four blocks, values 0,0,1,1."""
    curve = fit_isotonic([0.1, 0.2, 0.8, 0.9], [False, False, True, True], min_pairs=4)
    assert curve.values == (0.0, 0.0, 1.0, 1.0)
    assert curve.thresholds == (0.1, 0.2, 0.8, 0.9)


def test_a_single_violator_is_pooled_with_its_neighbour() -> None:
    """Labels in score order: 0, 1, 0, 1. The (1, 0) at positions 2-3 is a
    violation; PAV pools them to 0.5. Result: [0, 0.5, 0.5, 1] with the pooled
    block starting at the lower of its two scores."""
    curve = fit_isotonic([0.1, 0.4, 0.5, 0.9], [False, True, False, True], min_pairs=4)
    assert curve.values == (0.0, 0.5, 1.0)
    assert curve.thresholds == (0.1, 0.4, 0.9)


def test_a_cascade_of_violations_pools_backwards() -> None:
    """Labels 1, 0, 0 at rising scores: pooling (1,0) gives 0.5 which still
    violates against the next 0, so it pools again to 1/3. One block."""
    curve = fit_isotonic([0.2, 0.5, 0.8], [True, False, False], min_pairs=3)
    assert len(curve.values) == 1
    assert curve.values[0] == pytest.approx(1 / 3)


def test_prediction_is_a_monotone_step_function() -> None:
    curve = fit_isotonic(
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        [False, False, True, False, True, True],
        min_pairs=6,
    )
    probabilities = [curve.predict(score / 20) for score in range(0, 21)]
    assert probabilities == sorted(probabilities), "calibrated probability must never decrease"
    assert curve.predict(-1.0) == curve.values[0]  # below the lowest bin
    assert curve.predict(2.0) == curve.values[-1]  # above the highest


def test_prediction_at_a_threshold_uses_that_bin() -> None:
    curve = fit_isotonic([0.2, 0.8], [False, True], min_pairs=2)
    assert curve.predict(0.2) == 0.0
    assert curve.predict(0.79) == 0.0
    assert curve.predict(0.8) == 1.0


# --- refusing to fit ---------------------------------------------------------


def test_too_few_pairs_is_refused_not_fitted() -> None:
    """A curve on five points is a drawing. `specs/calibrate.md` §2 makes
    refusing it a design decision."""
    with pytest.raises(CalibrationError, match="below the minimum"):
        fit_isotonic([0.1, 0.9], [False, True], min_pairs=30)


def test_one_class_only_is_refused() -> None:
    with pytest.raises(CalibrationError, match="both outcomes"):
        fit_isotonic([0.1, 0.5, 0.9], [True, True, True], min_pairs=3)


def test_misaligned_input_is_refused() -> None:
    with pytest.raises(CalibrationError, match="aligned"):
        fit_isotonic([0.1, 0.2], [True], min_pairs=1)


# --- pairs persistence -------------------------------------------------------


def test_pairs_round_trip_in_stable_order(tmp_path: Path) -> None:
    pairs = [
        LabelledPair("qa:9", "https://b.test", 0.4, True),
        LabelledPair("qa:1", "https://a.test", 0.7, False),
    ]
    path = tmp_path / "pairs.jsonl"
    write_pairs(path, pairs)
    write_pairs(path, list(reversed(pairs)))  # order of input must not matter
    assert read_pairs(path) == sorted(pairs, key=lambda p: (p.row_uid, p.url))


def test_reading_a_missing_pairs_file_is_empty(tmp_path: Path) -> None:
    assert read_pairs(tmp_path / "none.jsonl") == []


# --- the report --------------------------------------------------------------


def test_report_states_n_bias_and_reliability() -> None:
    pairs = [
        LabelledPair(f"qa:{i}", f"https://{i}.test", score, correct)
        for i, (score, correct) in enumerate(
            [
                (0.1, False),
                (0.2, False),
                (0.3, False),
                (0.4, True),
                (0.5, False),
                (0.6, True),
                (0.7, True),
                (0.8, True),
                (0.9, True),
                (0.95, True),
            ]
        )
    ]
    curve = fit_isotonic([p.score for p in pairs], [p.correct for p in pairs], min_pairs=10)
    report = build_report(pairs, curve)
    text = format_report(report)

    assert report.n_pairs == 10 and report.n_positive == 6 and report.n_rows == 10
    assert "SELECTION BIAS" in text
    assert "labelled pairs: 10" in text
    assert 0.0 <= report.expected_calibration_error <= 1.0
    # abstention at tau=0 selects everything; at tau=0.9 it selects fewer
    assert report.abstention[0].selected == 10
    assert report.abstention[-1].selected <= 10
    # precision is non-decreasing as tau rises for a monotone curve
    precisions = [a.precision for a in report.abstention if a.selected]
    assert precisions == sorted(precisions)
