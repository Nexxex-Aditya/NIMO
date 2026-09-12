"""`uv run python -m nimo.site --sheet qa [--out-dir D] [--title T] [--note "..."]...`

Writes `<out-dir>/site_<sheet>.html`: the run's results explorer, one file,
no server. `print` is the CLI's user-facing output (`04` §10).
"""

import sys
from pathlib import Path

from nimo.loader import load_rows
from nimo.run.compose import CONFIG_DIR, OUT_DIR, REGISTRY_DIR, RETAILERS, WORKBOOK
from nimo.site.build import build_site


def main(argv: list[str]) -> int:
    sheet = argv[argv.index("--sheet") + 1] if "--sheet" in argv else "qa"
    out_dir = Path(argv[argv.index("--out-dir") + 1]) if "--out-dir" in argv else OUT_DIR
    title = (
        argv[argv.index("--title") + 1] if "--title" in argv else f"NIMO — {sheet} results explorer"
    )
    notes = [argv[i + 1] for i, a in enumerate(argv) if a == "--note" and i + 1 < len(argv)]
    rows = load_rows(WORKBOOK, sheet, RETAILERS)
    report = build_site(
        rows=rows,
        sheet=sheet,
        artifacts=out_dir / "artifacts" / sheet,
        failures_path=out_dir / "failures.jsonl",
        registry_path=REGISTRY_DIR / "entities.jsonl",
        config_dir=CONFIG_DIR,
        out=out_dir / f"site_{sheet}.html",
        title=title,
        notes=notes,
    )
    print(
        f"site: {report.rows_complete}/{report.rows_total} rows"
        + (f", {report.rows_failed} failed" if report.rows_failed else "")
        + f", {report.entities} registry entities, {report.bytes / 1e6:.1f} MB"
    )
    print(f"written: {report.path}  (open it in a browser; no server needed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
