"""`uv run python -m nimo.characteristics [--evaluate DIR]` — P12's measurements.

Without arguments: the OFFLINE instrument (`specs/characteristics.md` §6) —
applicability precision/recall on `dev` when the module comes from P5's
5-fold held-out predictions rather than the label. Needs no model.

With `--evaluate <artifacts-root>`: per-characteristic accuracy on `dev`
over the runner's `characteristics/` artifacts from an on-network
`--live --characteristics` run.

`print` is the CLI's user-facing output (`04` §10).
"""

import sys
from pathlib import Path

from nimo.characteristics.evaluate import (
    accuracy_report,
    applicability_report,
    format_accuracy,
    format_applicability,
    load_characteristic_labels,
)
from nimo.classify import load_classify_config
from nimo.classify.evaluate import cross_validate
from nimo.contracts import CharacteristicValues
from nimo.loader import load_characteristic_rules, load_module_labels, load_rows
from nimo.normalize import normalize_rows
from nimo.run.artifacts import artifact_path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
RETAILERS = REPO_ROOT / "config" / "retailers.yaml"
FOLDS = 5  # the deterministic module-stratified protocol P5 pins (`specs/classify.md`)


def main(argv: list[str]) -> int:
    rules = load_characteristic_rules(WORKBOOK)
    rows = load_rows(WORKBOOK, "dev", RETAILERS)
    modules = load_module_labels(WORKBOOK, "dev", rules)

    print(format_applicability(applicability_report(rules, modules, modules), source="TRUE"))
    predicted = [
        p.module
        for p in cross_validate(normalize_rows(rows), modules, load_classify_config(), FOLDS)
    ]
    print()
    print(
        format_applicability(
            applicability_report(rules, modules, predicted), source="P5 5-fold PREDICTED"
        )
    )
    print(
        "  (the ceiling P5's module accuracy imposes on this stage: a wrong module loses the\n"
        "   value AND the null pattern together — `01` §6)"
    )

    if "--evaluate" in argv:
        root = Path(argv[argv.index("--evaluate") + 1])
        labels = load_characteristic_labels(WORKBOOK, "dev")
        predictions: list[CharacteristicValues | None] = []
        for row in rows:
            path = artifact_path(root, "characteristics", row.row_uid)
            predictions.append(
                CharacteristicValues.model_validate_json(path.read_text(encoding="utf-8"))
                if path.exists()
                else None
            )
        present = sum(1 for p in predictions if p is not None)
        llm_sourced = sum(1 for p in predictions if p is not None and p.source == "llm")
        print()
        print(f"artifacts under {root}: {present}/{len(rows)} rows, {llm_sourced} from the model")
        if llm_sourced == 0:
            print(
                "  NO model-sourced values — this is a gate-only tree. Per-characteristic\n"
                "  accuracy below is the null-pattern-only baseline, NOT the P12 gate number."
            )
        print(format_accuracy(accuracy_report(rules, modules, labels, predictions)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
