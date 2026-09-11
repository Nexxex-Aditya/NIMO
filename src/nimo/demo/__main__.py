"""`uv run python -m nimo.demo --sheet qa --rows 10 [--live] [--out-dir D] [--html]`

P15's walkthrough (`specs/demo.md`). Drives the ordinary runner over the
first N rows (resumable: rows already processed cost nothing), then renders
one card per row from the artifacts and a run summary, and optionally a
self-contained HTML page. It decides nothing — the runner and the eight
stages do; this is what they recorded.

`print` is the CLI's user-facing output (`04` §10).
"""

import sys
from collections import Counter
from pathlib import Path

from nimo.demo.cards import load_card, load_failures, render_failure, render_html, render_text
from nimo.registry import read_entities
from nimo.run.__main__ import OUT_DIR, REGISTRY_DIR
from nimo.run.__main__ import main as run_main

DEFAULT_ROWS = 10  # `04` §1's P15 gate: "Runs end-to-end on 10 sample rows"


def main(argv: list[str]) -> int:
    sheet = argv[argv.index("--sheet") + 1] if "--sheet" in argv else "qa"
    rows = int(argv[argv.index("--rows") + 1]) if "--rows" in argv else DEFAULT_ROWS
    out_dir = Path(argv[argv.index("--out-dir") + 1]) if "--out-dir" in argv else OUT_DIR
    live = "--live" in argv
    want_html = "--html" in argv

    entities_before = len(read_entities(REGISTRY_DIR / "entities.jsonl"))
    run_args = ["--sheet", sheet, "--limit", str(rows), "--run-id", f"demo-{sheet}"]
    run_args += ["--out-dir", str(out_dir)]
    if live:
        run_args.append("--live")
    print(f"--- driving the runner: python -m nimo.run {' '.join(run_args)}")
    run_main(run_args)
    entities_after = len(read_entities(REGISTRY_DIR / "entities.jsonl"))

    root = out_dir / "artifacts" / sheet
    failures = load_failures(out_dir / "failures.jsonl")
    cards = []
    failed = []
    for index in range(rows):
        row_uid = f"{sheet}:{index}"
        card = load_card(root, row_uid)
        if card is None:
            if row_uid in failures:
                failed.append(failures[row_uid])
            continue
        cards.append(card)

    tiers = Counter(card.tier for card in cards)
    gtin_hits = sum(
        1
        for card in cards
        if card.selection.features is not None and card.selection.features.barcode_exact
    )
    registry_hits = sum(1 for card in cards if card.registry.hit)
    summary = [
        f"sheet {sheet}, first {rows} rows: {len(cards)} complete, {len(failed)} failed",
        f"resolution tiers: {dict(sorted(tiers.items()))}",
        f"identity confirmed by GTIN: {gtin_hits} this run + {registry_hits} carried from the "
        f"registry (a hit is a GTIN match to a prior run) = "
        f"{gtin_hits + registry_hits}/{len(cards)}",
        f"registry entities: {entities_before} before -> {entities_after} after",
        "mode: " + ("LIVE (SearxNG + fetch)" if live else "OFFLINE (no network; retrieval empty)"),
        "Tier 0 fires on a RE-RUN against a warm registry, not on a first pass "
        "(`specs/registry.md` §3) — run the same rows again with a fresh --out-dir to see it.",
    ]
    print()
    print("\n".join(summary))
    print()
    for card in cards:
        print(render_text(card))
        print()
    for failure in failed:
        print(render_failure(failure))

    if want_html:
        path = out_dir / f"demo_{sheet}.html"
        path.write_text(
            render_html(f"NIMO demo — {sheet}, {rows} rows", cards, failed, summary),
            encoding="utf-8",
        )
        print(f"\nhtml: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
