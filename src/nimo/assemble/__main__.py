"""`uv run python -m nimo.assemble --sheet qa [--out-dir D] [--artifacts D]` — P14.

Reads the runner's artifact trees, writes `submission_<sheet>.csv`,
`submission_<sheet>.xlsx` and `assembly_<sheet>.txt`. No network, no model.
`print` is the CLI's user-facing output (`04` §10).
"""

import sys
from pathlib import Path

from nimo.assemble.assemble import (
    assemble_rows,
    format_report,
    load_output_config,
    write_csv,
    write_xlsx,
)
from nimo.loader import load_characteristic_rules

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
OUT_DIR = REPO_ROOT / "data" / "out"


def main(argv: list[str]) -> int:
    sheet = argv[argv.index("--sheet") + 1] if "--sheet" in argv else "qa"
    out_dir = Path(argv[argv.index("--out-dir") + 1]) if "--out-dir" in argv else OUT_DIR
    artifacts = (
        Path(argv[argv.index("--artifacts") + 1])
        if "--artifacts" in argv
        else out_dir / "artifacts" / sheet
    )
    config = load_output_config()
    rows, report = assemble_rows(
        WORKBOOK,
        sheet,
        artifacts,
        load_characteristic_rules(WORKBOOK),
        config,
        failures_path=out_dir / "failures.jsonl",
    )
    write_csv(rows, out_dir / f"submission_{sheet}.csv")
    write_xlsx(rows, out_dir / f"submission_{sheet}.xlsx", sheet, config)
    text = format_report(report)
    (out_dir / f"assembly_{sheet}.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"written: {out_dir / f'submission_{sheet}.csv'} and .xlsx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
