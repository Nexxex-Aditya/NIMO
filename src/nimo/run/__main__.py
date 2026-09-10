"""`uv run python -m nimo.run --sheet dev` — the batch runner CLI.

`print` here is the CLI's user-facing output, which `04` §10 permits; nothing
in the library prints.

Batch-level setup (workbook, config, classifier fit, registry index) happens
once, before any row is touched, and is deliberately **not** wrapped in the
runner's failure handling: a missing workbook is not a per-row condition and
retrying it 412 times would print the same error 412 times.
"""

import sys
from pathlib import Path

from nimo.classify import load_classify_config
from nimo.classify.model import ModuleClassifier
from nimo.loader import load_characteristic_rules, load_module_labels, load_rows
from nimo.normalize import normalize_rows
from nimo.registry import build_index, fit_identity_idf, load_thresholds, read_entities
from nimo.run.runner import RunPaths, default_stages, format_summary, run

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
CONFIG_DIR = REPO_ROOT / "config"
RETAILERS = CONFIG_DIR / "retailers.yaml"
REGISTRY_DIR = REPO_ROOT / "data" / "registry"
OUT_DIR = REPO_ROOT / "data" / "out"


def main(argv: list[str]) -> int:
    sheet = "dev"
    if "--sheet" in argv:
        sheet = argv[argv.index("--sheet") + 1]
    run_id = argv[argv.index("--run-id") + 1] if "--run-id" in argv else f"run-{sheet}"

    rows = load_rows(WORKBOOK, sheet, RETAILERS)

    # The classifier always fits on `dev` — it is the only sheet with MODULE
    # ground truth (`01` §6). Running over `qa` classifies with a dev-fitted
    # model, which is the intended direction.
    rules = load_characteristic_rules(WORKBOOK)
    dev_rows = rows if sheet == "dev" else load_rows(WORKBOOK, "dev", RETAILERS)
    dev_queries = normalize_rows(dev_rows)
    classifier = ModuleClassifier.fit(
        dev_queries, load_module_labels(WORKBOOK, "dev", rules), load_classify_config()
    )

    entities = read_entities(REGISTRY_DIR / "entities.jsonl")
    index = build_index(entities, fit_identity_idf(dev_queries))

    paths = RunPaths(
        artifacts=OUT_DIR / "artifacts" / sheet,
        trace=OUT_DIR / "trace.jsonl",
        failures=OUT_DIR / "failures.jsonl",
        config_dir=CONFIG_DIR,
    )
    summary = run(rows, default_stages(index, load_thresholds(), classifier), paths, run_id)
    print(format_summary(summary))
    if entities:
        print(f"registry: {len(entities)} entities loaded")
    else:
        print(
            "registry: cold (0 entities) — every row reads tier2_retrieval, which is the "
            "honest cold-start number. Tier 0 fires 412/412 on a re-run against a warm "
            "registry (`specs/registry.md` §3)."
        )
    return 1 if summary.rows_failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
