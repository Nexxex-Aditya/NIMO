"""Isotonic regression via pool-adjacent-violators — `specs/calibrate.md` §2.

Pure. Hand-written for the same reason P5's classifier is: it fits on one
screen, it is unit-tested against hand-worked cases, and the scikit-learn
dependency would need an untyped-import override (`04` §3) to buy it.

Isotonic over Platt because it makes no shape assumption. The raw score has a
hard-rule floor and multiplicative demotion penalties in it (`specs/match.md`
§2), so the relationship to correctness is not sigmoid and must not be forced
into one.
"""

from dataclasses import dataclass


class CalibrationError(Exception):
    """A calibration was requested that cannot honestly be produced."""


@dataclass(frozen=True)
class IsotonicCurve:
    """A fitted monotone step function.

    `thresholds[i]` is the lowest raw score in bin `i`; `values[i]` is the
    calibrated probability for scores in `[thresholds[i], thresholds[i+1])`.
    Scores below `thresholds[0]` get `values[0]`. Monotone non-decreasing by
    construction, so a higher raw score never yields a lower probability.
    """

    thresholds: tuple[float, ...]
    values: tuple[float, ...]
    n_pairs: int
    n_positive: int

    def predict(self, score: float) -> float:
        """Calibrated probability for one raw score."""
        result = self.values[0]
        for threshold, value in zip(self.thresholds, self.values, strict=True):
            if score >= threshold:
                result = value
            else:
                break
        return result


def fit_isotonic(scores: list[float], labels: list[bool], *, min_pairs: int) -> IsotonicCurve:
    """Pool-adjacent-violators over `(score, label)` pairs.

    Sorts by score, starts with one block per point (value = label), and
    repeatedly merges any adjacent pair of blocks whose values decrease
    left-to-right into one block at their weighted mean. Terminates when the
    block values are non-decreasing — which is the isotonic fit.

    `min_pairs` is enforced here, not by the caller: a curve on too few points
    is a drawing, and `specs/calibrate.md` §2 makes refusing one a design
    decision rather than a courtesy.
    """
    if len(scores) != len(labels):
        raise CalibrationError(
            f"scores and labels must be aligned; got {len(scores)} and {len(labels)}"
        )
    if len(scores) < min_pairs:
        raise CalibrationError(
            f"{len(scores)} labelled pairs is below the minimum of {min_pairs} "
            f"(`config/thresholds.yaml`). A curve fitted on this few points would look like "
            f"a probability and not be one; `calibrated_prob` keeps mirroring `raw_score`."
        )
    positives = sum(1 for label in labels if label)
    if positives == 0 or positives == len(labels):
        raise CalibrationError(
            f"all {len(labels)} labels are {'positive' if positives else 'negative'}; "
            f"a fit needs both outcomes to say anything."
        )

    order = sorted(range(len(scores)), key=lambda i: (scores[i], i))
    # Each block: [start_score, sum_of_labels, count]. **Tied scores are
    # pooled into one weighted block before PAV** — standard isotonic
    # regression, and the property the reliability report depends on: two
    # pairs at 0.45 labelled [0, 1] must fit to 0.5 at 0.45, not to two
    # blocks (0.45 -> 0.0, 0.45 -> 1.0) that PAV leaves alone because they
    # do not decrease and that `predict` then resolves by whichever is last.
    # Found on the first full harvest: a bin predicted 0.61 and observed
    # 0.42, which a within-block fit cannot do unless ties were split.
    blocks: list[list[float]] = []
    for i in order:
        label = 1.0 if labels[i] else 0.0
        if blocks and blocks[-1][0] == scores[i]:
            blocks[-1][1] += label
            blocks[-1][2] += 1.0
        else:
            blocks.append([scores[i], label, 1.0])

    merged = True
    while merged:
        merged = False
        i = 0
        while i < len(blocks) - 1:
            left, right = blocks[i], blocks[i + 1]
            if left[1] / left[2] > right[1] / right[2]:
                blocks[i] = [left[0], left[1] + right[1], left[2] + right[2]]
                del blocks[i + 1]
                merged = True
                # Re-check against the new left neighbour: a merge can create
                # a fresh violation one step back.
                i = max(i - 1, 0)
            else:
                i += 1

    return IsotonicCurve(
        thresholds=tuple(block[0] for block in blocks),
        values=tuple(block[1] / block[2] for block in blocks),
        n_pairs=len(scores),
        n_positive=positives,
    )
