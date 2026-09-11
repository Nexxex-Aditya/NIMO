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
    """Two denominators, both printed, neither instead of the other.

    `applicable_rows` is the SUBMISSION view: every row where the
    characteristic applies under the true module, a missing row counted
    wrong because the sheet would be blank there. `ran_rows` is the MODEL
    view: only rows the pipeline produced an artifact for. On a complete
    run they coincide; on a partial run (92/412 rows, office 2026-09-12)
    the first read 14.7% and the second 76% — and only the second says
    anything about the extractor.
    """

    characteristic: str
    applicable_rows: int  # under the TRUE module
    ran_rows: int  # of those, rows with a characteristics artifact at all
    predicted_rows: int  # of those, rows the pipeline produced a value for
    exact: int  # normalised string equality, over applicable_rows
    component_set: int  # `&` components equal as a set — order-insensitive
    exact_ran: int  # the same two counts, over ran_rows only
    component_set_ran: int

    @property
    def accuracy(self) -> float:
        return self.exact / self.applicable_rows if self.applicable_rows else 0.0

    @property
    def accuracy_ran(self) -> float:
        return self.exact_ran / self.ran_rows if self.ran_rows else 0.0


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
    ran_n: Counter[str] = Counter()
    predicted_n: Counter[str] = Counter()
    exact: Counter[str] = Counter()
    component: Counter[str] = Counter()
    exact_ran: Counter[str] = Counter()
    component_ran: Counter[str] = Counter()
    for module, label, prediction in zip(true_modules, labels, predictions, strict=True):
        for rule in applicable_rules(rules, module):
            name = rule.characteristic
            applicable_n[name] += 1
            ran = prediction is not None
            ran_n[name] += ran
            truth = label.get(name)
            guess = prediction.values.get(name) if prediction is not None else None
            if guess is not None:
                predicted_n[name] += 1
            is_exact = guess == truth
            if guess is not None and truth is not None:
                is_set = set(guess.split(" & ")) == set(truth.split(" & "))
            else:
                is_set = guess is None and truth is None
            exact[name] += is_exact
            component[name] += is_set
            exact_ran[name] += is_exact and ran
            component_ran[name] += is_set and ran
    return [
        CharacteristicAccuracy(
            characteristic=name,
            applicable_rows=applicable_n[name],
            ran_rows=ran_n[name],
            predicted_rows=predicted_n[name],
            exact=exact[name],
            component_set=component[name],
            exact_ran=exact_ran[name],
            component_set_ran=component_ran[name],
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
    """Two views per characteristic. `exact` and `set` are over `n` (the
    submission view); `exact/ran` and `set/ran` are over `ran` (the model
    view). They coincide on a complete run and the footer says which."""
    lines = ["per-characteristic accuracy over rows where it applies under the TRUE module:"]
    lines.append(
        f"  {'characteristic':48s} {'n':>4s} {'ran':>4s} {'ans':>4s} "
        f"{'exact':>6s} {'set':>6s} {'exact/ran':>9s} {'set/ran':>8s}"
    )
    for row in rows:
        set_ran = row.component_set_ran / row.ran_rows if row.ran_rows else 0.0
        lines.append(
            f"  {row.characteristic:48s} {row.applicable_rows:4d} {row.ran_rows:4d} "
            f"{row.predicted_rows:4d} {row.accuracy:6.1%} "
            f"{row.component_set / row.applicable_rows:6.1%} {row.accuracy_ran:9.1%} "
            f"{set_ran:8.1%}"
        )
    total = sum(r.applicable_rows for r in rows)
    ran = sum(r.ran_rows for r in rows)
    hits = sum(r.exact for r in rows)
    hits_ran = sum(r.exact_ran for r in rows)
    if not total:
        lines.append("  (no rows)")
    else:
        lines.append(
            f"  micro accuracy, submission view (missing rows wrong): "
            f"{hits}/{total} = {hits / total:.1%}"
        )
        lines.append(
            f"  micro accuracy, model view (rows that ran only):      "
            f"{hits_ran}/{ran} = {hits_ran / ran:.1%}"
            if ran
            else "  micro accuracy, model view: no rows ran"
        )
        if ran < total:
            lines.append(
                "  the two differ because the run was PARTIAL — only the model view says "
                "anything about the extractor; the submission view is what a sheet from "
                "this tree would score."
            )
    return "\n".join(lines)
