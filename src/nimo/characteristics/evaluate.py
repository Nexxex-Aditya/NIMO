"""Evaluation — `specs/characteristics.md` §6, `03` §6 L2.

Two instruments, because a wrong module loses the value and the null pattern
together (`01` §6):

- **Applicability precision/recall** under a *predicted* module against the
  applicable set under the *true* module. Needs no model, so it is measured
  off-network — the ceiling P5's classifier imposes on this stage.
- **Per-characteristic accuracy** over the rows where the characteristic is
  applicable under the true module. Needs the model's values, so it runs
  on-network, over the runner's `characteristics/` artifacts.
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from nimo.characteristics.gate import CHARACTERISTIC_COLUMNS, applicable_rules
from nimo.characteristics.validate import normalise
from nimo.contracts import CharacteristicRule, CharacteristicValues
from nimo.loader import DatasetSchemaError


def load_characteristic_labels(workbook_path: Path, sheet: str) -> list[dict[str, str | None]]:
    """The 13 ground-truth columns per row, positionally aligned with
    `load_rows`. `dev` only in practice (`01` §6). Values are normalised the
    way predictions are, so equality means the same thing on both sides."""
    frame = pd.read_excel(workbook_path, sheet_name=sheet, dtype=str)
    missing = [name for name in CHARACTERISTIC_COLUMNS if name not in frame.columns]
    if missing:
        raise DatasetSchemaError(f"{sheet}: characteristic column(s) missing: {missing}")
    labels: list[dict[str, str | None]] = []
    for _, row in frame.iterrows():
        record: dict[str, str | None] = {}
        for name in CHARACTERISTIC_COLUMNS:
            raw = row[name]
            text = "" if not isinstance(raw, str) or raw == "nan" else raw
            record[name] = normalise(text) or None
        labels.append(record)
    return labels


@dataclass(frozen=True)
class ApplicabilityReport:
    rows: int
    true_positive: int  # applicable under both true and predicted module
    false_positive: int  # predicted applicable, truly not — a value where a blank belongs
    false_negative: int  # truly applicable, predicted not — a blank where a value belongs
    exact_pattern_rows: int  # rows whose whole null pattern is right

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 0.0


def applicability_report(
    rules: list[CharacteristicRule], true_modules: list[str], predicted_modules: list[str]
) -> ApplicabilityReport:
    if len(true_modules) != len(predicted_modules):
        raise ValueError("true and predicted modules must be positionally aligned")
    tp = fp = fn = exact = 0
    for true, predicted in zip(true_modules, predicted_modules, strict=True):
        truth = {rule.characteristic for rule in applicable_rules(rules, true)}
        guess = {rule.characteristic for rule in applicable_rules(rules, predicted)}
        tp += len(truth & guess)
        fp += len(guess - truth)
        fn += len(truth - guess)
        exact += truth == guess
    return ApplicabilityReport(len(true_modules), tp, fp, fn, exact)


@dataclass(frozen=True)
class CharacteristicAccuracy:
    characteristic: str
    applicable_rows: int  # under the TRUE module
    predicted_rows: int  # of those, rows the pipeline produced a value for
    exact: int  # normalised string equality
    component_set: int  # `&` components equal as a set — order-insensitive

    @property
    def accuracy(self) -> float:
        return self.exact / self.applicable_rows if self.applicable_rows else 0.0


def accuracy_report(
    rules: list[CharacteristicRule],
    true_modules: list[str],
    labels: list[dict[str, str | None]],
    predictions: list[CharacteristicValues | None],
) -> list[CharacteristicAccuracy]:
    """Per characteristic, over the rows where it applies under the true
    module. A missing prediction (row failed, or no artifact) counts as a
    wrong answer, not as excluded — the submission would be blank there."""
    if not len(true_modules) == len(labels) == len(predictions):
        raise ValueError("modules, labels and predictions must be positionally aligned")
    applicable_n: Counter[str] = Counter()
    predicted_n: Counter[str] = Counter()
    exact: Counter[str] = Counter()
    component: Counter[str] = Counter()
    for module, label, prediction in zip(true_modules, labels, predictions, strict=True):
        for rule in applicable_rules(rules, module):
            name = rule.characteristic
            applicable_n[name] += 1
            truth = label.get(name)
            guess = prediction.values.get(name) if prediction is not None else None
            if guess is not None:
                predicted_n[name] += 1
            if guess == truth:
                exact[name] += 1
            if guess is not None and truth is not None:
                if set(guess.split(" & ")) == set(truth.split(" & ")):
                    component[name] += 1
            elif guess is None and truth is None:
                component[name] += 1
    return [
        CharacteristicAccuracy(
            characteristic=name,
            applicable_rows=applicable_n[name],
            predicted_rows=predicted_n[name],
            exact=exact[name],
            component_set=component[name],
        )
        for name in CHARACTERISTIC_COLUMNS
        if applicable_n[name]
    ]


def format_applicability(report: ApplicabilityReport, *, source: str) -> str:
    return (
        f"applicability under {source} modules, {report.rows} rows:\n"
        f"  precision {report.precision:.3f}  recall {report.recall:.3f}  "
        f"(TP {report.true_positive}, FP {report.false_positive}, FN {report.false_negative})\n"
        f"  rows with the exact null pattern: {report.exact_pattern_rows}/{report.rows} "
        f"({report.exact_pattern_rows / report.rows:.1%})\n"
        f"  FP = a value where a blank belongs; FN = a blank where a value belongs. Both are\n"
        f"  wrong answers under the dataset guide, and both come from the MODULE alone."
    )


def format_accuracy(rows: list[CharacteristicAccuracy]) -> str:
    lines = ["per-characteristic accuracy over rows where it applies under the TRUE module:"]
    lines.append(f"  {'characteristic':52s} {'n':>4s} {'answered':>8s} {'exact':>6s} {'set':>6s}")
    for row in rows:
        lines.append(
            f"  {row.characteristic:52s} {row.applicable_rows:4d} {row.predicted_rows:8d} "
            f"{row.accuracy:6.1%} {row.component_set / row.applicable_rows:6.1%}"
        )
    total = sum(r.applicable_rows for r in rows)
    hits = sum(r.exact for r in rows)
    lines.append(
        f"  micro accuracy: {hits}/{total} = {hits / total:.1%}" if total else "  (no rows)"
    )
    return "\n".join(lines)
