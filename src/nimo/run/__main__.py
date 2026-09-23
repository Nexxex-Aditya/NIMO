"""`uv run python -m nimo.run --sheet dev [--live] [--limit N] [--adjudicate]
[--characteristics] [--out-dir D]` — the batch runner CLI.

`print` here is the CLI's user-facing output, which `04` §10 permits; nothing
in the library prints.

Modes:

- **default (offline):** normalize -> registry -> classify -> gate-only
  characteristics -> reason, with empty retrieval/fetch/match. No network.
  This is the resumability and failure-attribution path P6a proved.
- **`--live`:** the full pipeline through SearxNG, the fetcher and the
  matcher. Needs a running SearxNG (`docker compose up -d searxng`) unless
  every query is already in `data/cache/search/`. Resumable: a killed run
  skips completed rows on restart, and every registry merge is persisted the
  moment it happens.
- **`--characteristics`:** P12 extraction through the model (needs
  `CIS_LLM_API_KEY` and the NIQ network). Without `--live` it extracts from
  the product record alone — the description-only baseline, not the gate.
- **`--adjudicate`** (with `--live`): Tier 3 LLM adjudication where Layer A
  could not separate the top candidates.
- **`--out-dir D`:** write artifacts beside a baseline run instead of over
  it (`specs/adjudicate.md` §8).
- **`--input FILE`:** a product list of your own (`.xlsx`/`.csv` with at
  least `RETAILER_DESC` and `BRAND`) instead of a workbook sheet
  (`specs/input.md`). Needs `--live` and a running SearxNG for rows the
  caches have not seen.

The composition itself lives in `run/compose.py`, shared with the UI.
Batch-level setup failures (a missing workbook, a bad config) are deliberately
not caught: a missing workbook is not a per-row condition (`04` §4).
"""

import sys
from pathlib import Path

from nimo.loader import input_rows, load_input, load_rows
from nimo.run.compose import OUT_DIR, RETAILERS, WORKBOOK, Pipeline, PipelineConfigError
from nimo.run.runner import format_summary


def main(argv: list[str]) -> int:
    sheet = argv[argv.index("--sheet") + 1] if "--sheet" in argv else "dev"
    run_id = argv[argv.index("--run-id") + 1] if "--run-id" in argv else f"run-{sheet}"
    live = "--live" in argv
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    adjudicate = "--adjudicate" in argv
    characteristics = "--characteristics" in argv
    out_dir = Path(argv[argv.index("--out-dir") + 1]) if "--out-dir" in argv else OUT_DIR

    if characteristics and not live:
        print(
            "NOTE: --characteristics without --live extracts from the RECORD ALONE (no page "
            "evidence). This is the description-only baseline, not the P12 gate."
        )
    try:
        pipeline = Pipeline.create(
            live=live, adjudicate=adjudicate, characteristics=characteristics, out_dir=out_dir
        )
    except PipelineConfigError as error:
        print(str(error))
        return 2

    if "--input" in argv:
        # A bring-your-own product list (`specs/input.md`). Its rows are keyed
        # `<file-name>:<index>`, so its artifacts and cache entries never
        # collide with the dataset's; `--sheet` is ignored.
        table = load_input(Path(argv[argv.index("--input") + 1]))
        sheet = table.name
        run_id = argv[argv.index("--run-id") + 1] if "--run-id" in argv else f"run-{sheet}"
        rows = input_rows(table, RETAILERS)
        print(f"input: {table.source} -> {len(rows)} rows keyed `{sheet}:<n>`")
    else:
        rows = load_rows(WORKBOOK, sheet, RETAILERS)
    if limit is not None:
        rows = rows[:limit]
    entities_before = pipeline.registry_size

    if pipeline.curve is None:
        print(
            "calibration: NO CURVE at data/calibration/curve.json — calibrated_prob mirrors "
            "raw_score; run `uv run python -m nimo.calibrate` after a harvest."
        )
    else:
        print(
            f"calibration: curve loaded ({pipeline.curve.n_pairs} pairs, "
            f"{pipeline.curve.n_positive} positive); tau_abstain={pipeline.tau_abstain}"
            + (" (OFF)" if pipeline.tau_abstain == 0.0 else "")
        )

    try:
        summary = pipeline.run_rows(rows, sheet, run_id)
    finally:
        pipeline.close()

    if pipeline.searx is not None:
        print(pipeline.searx.status_line())
    if pipeline.fetcher is not None:
        blocked_hosts = sorted(
            host
            for host, counts in pipeline.fetcher.domain_outcomes.items()
            if counts.get("blocked")
        )
        if blocked_hosts:
            print(f"hosts that blocked us ({len(blocked_hosts)}): {', '.join(blocked_hosts[:12])}")
    if live:
        print(f"registry: {pipeline.registry_size} entities after this run")
    if adjudicate or characteristics:
        counter = pipeline.llm_counter
        print(
            f"model: {counter.calls} calls, {counter.cache_hits} cache hits, "
            f"{counter.rejected_verdicts} verdicts rejected by validation"
        )
    if not characteristics:
        print(
            "characteristics: GATE-ONLY (null pattern applied, no values) — pass "
            "--characteristics on the NIQ network to extract values."
        )

    print(format_summary(summary))
    if not live:
        print(
            "mode: OFFLINE — retrieval/fetch/match were empty by construction. "
            "Pass --live for the full pipeline (needs SearxNG up, or a warm search cache)."
        )
    if entities_before == 0 and not live:
        print(
            "registry: cold (0 entities) — every row reads tier2_retrieval, which is the "
            "honest cold-start number. Tier 0 fires on a re-run against a warm registry "
            "(`specs/registry.md` §3)."
        )
    return 1 if summary.rows_failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
