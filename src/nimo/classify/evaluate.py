"""Evaluation for the module baseline — `specs/classify.md` §7.

Two protocols, for two jobs. Both fully deterministic: no RNG anywhere, no
seed to reproduce, no shuffling (`04` §5).

**Leave-one-out** over all 412 `dev` rows is the reported number. Every row is
tested against a model that never saw it. At n=412 a held-out split big enough
to measure the 23-module tail is big enough to cripple training, so LOO is the
honest protocol, not a luxury.

**Deterministic module-stratified k-fold** is the regression guard: 5 fits
instead of 412, ~0.3s, affordable inside `make check` where LOO is not. It
reads slightly pessimistic (each fold trains on 80% of the data), which makes
it a safe floor rather than a flattering one.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass

from nimo.classify.config import ClassifyConfig
from nimo.classify.model import ModuleClassifier
from nimo.contracts import ModulePrediction, ProductQuery


class EvaluationError(Exception):
    """An evaluation was asked for that cannot be computed honestly."""


@dataclass(frozen=True)
class ModuleAccuracy:
    """Per-module accuracy. `total` is carried alongside `correct` because a
    0/1 module and a 0/133 module are not the same finding."""

    module: str
    correct: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total


@dataclass(frozen=True)
class ConfidenceBucket:
    """One decile of the confidence distribution, with its accuracy."""

    lowest: float
    highest: float
    rows: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.rows


@dataclass(frozen=True)
class ClassifierReport:
    """The measured result of one evaluation run.

    A frozen dataclass, not a `contracts.py` model, and deliberately: `03` §3
    is the *pipeline* contract authority, and this is an evaluation artifact
    that never crosses a pipeline stage boundary. It still satisfies `04` §3 —
    what leaves this module is a typed object, not a bare dict.
    """

    protocol: str
    rows: int
    correct: int
    per_module: list[ModuleAccuracy]
    confusions: list[tuple[str, str, int]]
    confidence_buckets: list[ConfidenceBucket]

    @property
    def overall_accuracy(self) -> float:
        return self.correct / self.rows

    @property
    def macro_accuracy(self) -> float:
        """Unweighted mean of per-module accuracy — **the headline number.**

        `01` §9: the top 4 modules are 77% of `dev`, so a classifier that
        nails them and ignores the other 23 module types scores 76.9% overall.
        Overall accuracy is reported too, never instead of this.
        """
        if not self.per_module:
            raise EvaluationError("no modules in report — macro accuracy is undefined")
        return sum(entry.accuracy for entry in self.per_module) / len(self.per_module)


def stratified_folds(labels: list[str], k: int) -> list[int]:
    """Assign each row a fold, module-stratified, with no randomness at all.

    Within each module, rows in source order are dealt round-robin into folds.
    No shuffle means no seed, which means no way for the assignment to drift
    between runs or machines (`04` §5).
    """
    if k < 2:
        raise EvaluationError(f"k must be at least 2 to hold anything out; got {k}")
    positions: dict[str, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        positions[label].append(index)
    folds = [0] * len(labels)
    for module in sorted(positions):
        for offset, index in enumerate(positions[module]):
            folds[index] = offset % k
    return folds


def _predict_held_out(
    queries: list[ProductQuery],
    labels: list[str],
    config: ClassifyConfig,
    train: list[int],
    test: list[int],
) -> list[ModulePrediction]:
    classifier = ModuleClassifier.fit(
        [queries[i] for i in train], [labels[i] for i in train], config
    )
    return [classifier.predict(queries[i]) for i in test]


def cross_validate(
    queries: list[ProductQuery],
    labels: list[str],
    config: ClassifyConfig,
    k: int,
) -> list[ModulePrediction]:
    """k-fold predictions, in the input row order."""
    if len(queries) != len(labels):
        raise EvaluationError(
            f"queries and labels must be positionally aligned; got {len(queries)} and {len(labels)}"
        )
    folds = stratified_folds(labels, k)
    predictions: dict[str, ModulePrediction] = {}
    for fold in range(k):
        train = [i for i, f in enumerate(folds) if f != fold]
        test = [i for i, f in enumerate(folds) if f == fold]
        if not test:
            continue
        for prediction in _predict_held_out(queries, labels, config, train, test):
            predictions[prediction.row_uid] = prediction
    return [predictions[query.row_uid] for query in queries]


def leave_one_out(
    queries: list[ProductQuery],
    labels: list[str],
    config: ClassifyConfig,
) -> list[ModulePrediction]:
    """One fit per row, each excluding that row. `len(queries)` fits — slow by
    construction, and the number `04` §1's P5 gate reports."""
    if len(queries) != len(labels):
        raise EvaluationError(
            f"queries and labels must be positionally aligned; got {len(queries)} and {len(labels)}"
        )
    indices = list(range(len(queries)))
    predictions: list[ModulePrediction] = []
    for held_out in indices:
        train = [i for i in indices if i != held_out]
        predictions.extend(_predict_held_out(queries, labels, config, train, [held_out]))
    return predictions


def build_report(
    protocol: str,
    predictions: list[ModulePrediction],
    labels: list[str],
    *,
    buckets: int = 10,
) -> ClassifierReport:
    """Score predictions against positionally aligned truth.

    Every module present in `labels` appears in `per_module`, including the
    four `dev` modules with a single row whose accuracy is structurally 0%
    under any held-out protocol. Dropping them would raise macro accuracy by
    hiding exactly the tail the metric exists to expose (`01` §9).
    """
    if len(predictions) != len(labels):
        raise EvaluationError(
            f"predictions and labels must be positionally aligned; got {len(predictions)} "
            f"and {len(labels)}"
        )
    if not predictions:
        raise EvaluationError("cannot build a report from zero predictions")

    tally: dict[str, list[int]] = {label: [0, 0] for label in labels}
    confusions: Counter[tuple[str, str]] = Counter()
    for prediction, truth in zip(predictions, labels, strict=True):
        tally[truth][1] += 1
        if prediction.module == truth:
            tally[truth][0] += 1
        else:
            confusions[(truth, prediction.module)] += 1

    per_module = sorted(
        (ModuleAccuracy(module, correct, total) for module, (correct, total) in tally.items()),
        key=lambda entry: (-entry.total, entry.module),
    )

    ordered = sorted(
        range(len(predictions)),
        key=lambda i: (predictions[i].confidence, predictions[i].row_uid),
    )
    confidence_buckets: list[ConfidenceBucket] = []
    for bucket in range(buckets):
        low = bucket * len(ordered) // buckets
        high = (bucket + 1) * len(ordered) // buckets
        chunk = ordered[low:high]
        if not chunk:
            continue
        confidence_buckets.append(
            ConfidenceBucket(
                lowest=predictions[chunk[0]].confidence,
                highest=predictions[chunk[-1]].confidence,
                rows=len(chunk),
                correct=sum(1 for i in chunk if predictions[i].module == labels[i]),
            )
        )

    return ClassifierReport(
        protocol=protocol,
        rows=len(predictions),
        correct=sum(1 for p, t in zip(predictions, labels, strict=True) if p.module == t),
        per_module=per_module,
        confusions=[
            (truth, predicted, count)
            for (truth, predicted), count in sorted(
                confusions.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        confidence_buckets=confidence_buckets,
    )


def format_report(report: ClassifierReport, *, max_confusions: int = 15) -> str:
    """Human-readable report. Macro first — it is the headline (`01` §9)."""
    lines = [
        f"protocol: {report.protocol}   rows: {report.rows}",
        f"macro (per-module) accuracy: {report.macro_accuracy:.1%}   <- headline",
        f"overall accuracy:            {report.overall_accuracy:.1%} "
        f"({report.correct}/{report.rows})",
        "",
        f"per-module accuracy, all {len(report.per_module)} modules, by row count:",
    ]
    lines.extend(
        f"  {entry.correct:3d}/{entry.total:3d}  {entry.accuracy:6.1%}  {entry.module}"
        for entry in report.per_module
    )
    if report.confusions:
        lines += ["", f"most frequent confusions (top {max_confusions}):"]
        lines.extend(
            f"  {count:3d}  {truth}  ->  {predicted}"
            for truth, predicted, count in report.confusions[:max_confusions]
        )
    if report.confidence_buckets:
        lines += ["", "accuracy by confidence decile:"]
        lines.extend(
            f"  {index}: {bucket.lowest:.3f}-{bucket.highest:.3f}  "
            f"n={bucket.rows:3d}  acc={bucket.accuracy:6.1%}"
            for index, bucket in enumerate(report.confidence_buckets)
        )
    return "\n".join(lines)
