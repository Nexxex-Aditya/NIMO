"""The calibration report — `specs/calibrate.md` §5, `04` §1's P10 gate.

Reliability (predicted vs observed per bin), expected calibration error, and
the abstention trade-off. Pure over the pairs and the curve.
"""

from dataclasses import dataclass

from nimo.calibrate.harvest import LabelledPair
from nimo.calibrate.isotonic import CalibrationError, IsotonicCurve, fit_isotonic


@dataclass(frozen=True)
class ReliabilityBin:
    lower: float
    upper: float
    rows: int
    predicted: float  # mean calibrated probability in the bin
    observed: float  # fraction actually correct


@dataclass(frozen=True)
class AbstentionPoint:
    tau: float
    selected: int  # candidates with calibrated_prob >= tau
    abstained: int
    precision: float  # of the selected, fraction correct


@dataclass(frozen=True)
class CalibrationReport:
    n_pairs: int
    n_positive: int
    n_rows: int
    curve: IsotonicCurve
    reliability: list[ReliabilityBin]
    expected_calibration_error: float  # in-sample: 0 by construction for isotonic
    held_out_calibration_error: float | None  # row-grouped k-fold; the honest number
    abstention: list[AbstentionPoint]


def held_out_ece(
    pairs: list[LabelledPair], *, folds: int, min_pairs: int, bins: int = 10
) -> float | None:
    """Cross-validated expected calibration error, folds grouped by `row_uid`.

    In-sample ECE for an isotonic fit is zero by construction — every block's
    value IS its members' observed rate — so it measures nothing. Pairs from
    one row share a query and a candidate set, so they must not straddle
    folds; rows are dealt round-robin in `row_uid` order (no RNG, `04` §5).
    `None` when a fold cannot be fitted (too few pairs, or one class).
    """
    rows = sorted({pair.row_uid for pair in pairs})
    if len(rows) < folds:
        return None
    fold_of = {row: index % folds for index, row in enumerate(rows)}
    predicted: list[float] = []
    observed: list[bool] = []
    for fold in range(folds):
        train = [pair for pair in pairs if fold_of[pair.row_uid] != fold]
        test = [pair for pair in pairs if fold_of[pair.row_uid] == fold]
        try:
            curve = fit_isotonic(
                [p.score for p in train], [p.correct for p in train], min_pairs=min_pairs
            )
        except CalibrationError:
            return None
        predicted.extend(curve.predict(pair.score) for pair in test)
        observed.extend(pair.correct for pair in test)
    ece = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = [
            (p, o)
            for p, o in zip(predicted, observed, strict=True)
            if lower <= p < upper or (index == bins - 1 and p == 1.0)
        ]
        if members:
            mean_predicted = sum(p for p, _ in members) / len(members)
            rate = sum(1 for _, o in members if o) / len(members)
            ece += abs(mean_predicted - rate) * len(members) / len(predicted)
    return ece


def build_report(
    pairs: list[LabelledPair],
    curve: IsotonicCurve,
    *,
    bins: int = 10,
    folds: int = 5,
    min_pairs: int = 2,
) -> CalibrationReport:
    predicted = [curve.predict(pair.score) for pair in pairs]

    reliability: list[ReliabilityBin] = []
    ece = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = [
            (probability, pair.correct)
            for probability, pair in zip(predicted, pairs, strict=True)
            if lower <= probability < upper or (index == bins - 1 and probability == 1.0)
        ]
        if not members:
            continue
        mean_predicted = sum(p for p, _ in members) / len(members)
        observed = sum(1 for _, correct in members if correct) / len(members)
        reliability.append(ReliabilityBin(lower, upper, len(members), mean_predicted, observed))
        ece += abs(mean_predicted - observed) * len(members) / len(pairs)

    abstention: list[AbstentionPoint] = []
    for step in range(0, 10):
        tau = step / 10
        selected = [(p, pair) for p, pair in zip(predicted, pairs, strict=True) if p >= tau]
        precision = (
            sum(1 for _, pair in selected if pair.correct) / len(selected) if selected else 0.0
        )
        abstention.append(
            AbstentionPoint(tau, len(selected), len(pairs) - len(selected), precision)
        )

    return CalibrationReport(
        n_pairs=len(pairs),
        n_positive=sum(1 for pair in pairs if pair.correct),
        n_rows=len({pair.row_uid for pair in pairs}),
        curve=curve,
        reliability=reliability,
        expected_calibration_error=ece,
        held_out_calibration_error=held_out_ece(pairs, folds=folds, min_pairs=min_pairs, bins=bins),
        abstention=abstention,
    )


def format_report(report: CalibrationReport) -> str:
    lines = [
        f"labelled pairs: {report.n_pairs}  positive: {report.n_positive}  "
        f"negative: {report.n_pairs - report.n_positive}  from {report.n_rows} qa rows",
        "",
        "SELECTION BIAS (state it every time): pairs come only from pages that publish",
        "a GTIN - structured-data-rich retailers, not Amazon or bot walls. The curve is",
        "fitted on the well-behaved end of the web and applied to all of it.",
        "",
        "fitted step function (raw score >= threshold -> calibrated probability):",
    ]
    lines.extend(
        f"  {threshold:.3f} -> {value:.3f}"
        for threshold, value in zip(report.curve.thresholds, report.curve.values, strict=True)
    )
    held = report.held_out_calibration_error
    lines += [
        "",
        f"reliability — in-sample ECE = {report.expected_calibration_error:.3f} (zero by "
        f"construction for an isotonic fit; NOT a quality measure)",
        "  HELD-OUT ECE, 5-fold grouped by row = "
        + (f"{held:.3f}  <- the honest number" if held is not None else "n/a (too few rows)"),
    ]
    lines.extend(
        f"  [{b.lower:.1f},{b.upper:.1f})  n={b.rows:4d}  predicted={b.predicted:.2f}  "
        f"observed={b.observed:.2f}"
        for b in report.reliability
    )
    lines += ["", "abstention trade-off (tau applied to CALIBRATED probability):"]
    lines.extend(
        f"  tau={a.tau:.1f}  select={a.selected:4d}  abstain={a.abstained:4d}  "
        f"precision={a.precision:.2f}"
        for a in report.abstention
    )
    return "\n".join(lines)
