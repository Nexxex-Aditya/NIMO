"""`uv run python -m nimo.classify` — the P5 report.

`04` §1's P5 gate is "per-module stratified accuracy reported". This is what
reports it, so the number is reproducible by anyone with the repo rather than
being a figure quoted in a document. `print` here is the CLI's user-facing
output, which `04` §10 permits; nothing in the library prints.

Leave-one-out over all 412 `dev` rows takes about a minute — 412 fits, by
construction (`specs/classify.md` §7). Pass `--folds N` for the fast
stratified k-fold protocol instead, which is what the test suite guards on.
"""

import sys
import time
from pathlib import Path

from nimo.classify.config import load_classify_config
from nimo.classify.evaluate import build_report, cross_validate, format_report, leave_one_out
from nimo.loader import load_characteristic_rules, load_module_labels, load_rows
from nimo.normalize import normalize_rows

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
RETAILERS = REPO_ROOT / "config" / "retailers.yaml"


def main(argv: list[str]) -> int:
    folds = 0
    if "--folds" in argv:
        folds = int(argv[argv.index("--folds") + 1])

    config = load_classify_config()
    rules = load_characteristic_rules(WORKBOOK)
    queries = normalize_rows(load_rows(WORKBOOK, "dev", RETAILERS))
    labels = load_module_labels(WORKBOOK, "dev", rules)

    started = time.monotonic()
    if folds:
        predictions = cross_validate(queries, labels, config, folds)
        protocol = f"module-stratified {folds}-fold"
    else:
        predictions = leave_one_out(queries, labels, config)
        protocol = "leave-one-out"
    elapsed = time.monotonic() - started

    report = build_report(protocol, predictions, labels)
    print(format_report(report))
    print()
    print(f"config: ngram_sizes={list(config.ngram_sizes)} use_brand={config.use_brand}")
    print(f"fitted and scored in {elapsed:.1f}s")

    absent = sorted({rule.module for rule in rules} - set(labels))
    print()
    print(
        f"{len(absent)} of {len({rule.module for rule in rules})} defined modules have no `dev` "
        f"row and are unreachable by this model — measured and deliberate, "
        f"`specs/classify.md` §6."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
