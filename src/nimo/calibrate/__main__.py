"""`uv run python -m nimo.calibrate [--artifacts DIR] [--sheet qa]` — P10's fit.

Harvests labelled pairs from the runner's `fetch` artifacts (the GTIN rule as
the oracle, `specs/calibrate.md` §1), writes `data/calibration/pairs.jsonl`,
fits the isotonic curve when there are enough pairs, writes
`data/calibration/curve.json`, and prints the reliability report. Offline
and reproducible: the same artifacts give the same curve.

`print` is the CLI's user-facing output (`04` §10).
"""

import hashlib
import sys
from pathlib import Path

from nimo.calibrate.harvest import harvest_pairs, write_pairs
from nimo.calibrate.isotonic import CalibrationError, fit_isotonic
from nimo.calibrate.report import build_report, format_report
from nimo.calibrate.store import CURVE_PATH, PAIRS_PATH, load_calibration_config, write_curve
from nimo.match import load_match_config
from nimo.run.artifacts import artifact_filename

REPO_ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str]) -> int:
    sheet = argv[argv.index("--sheet") + 1] if "--sheet" in argv else "qa"
    artifacts = (
        Path(argv[argv.index("--artifacts") + 1])
        if "--artifacts" in argv
        else REPO_ROOT / "data" / "out" / "artifacts" / sheet
    )
    config = load_calibration_config()
    # Every row with a fetch artifact — the harvest needs only normalize +
    # fetch, so a tree from an older, shorter stage sequence still yields.
    row_uids = sorted(
        (
            f"{sheet}:{path.stem.split('-', 1)[1]}"
            for path in (artifacts / "fetch").glob("*.json")
            if path.name == artifact_filename(f"{sheet}:{path.stem.split('-', 1)[1]}")
        ),
        key=lambda uid: int(uid.split(":")[1]),
    )
    pairs = harvest_pairs(artifacts, row_uids, load_match_config())
    write_pairs(PAIRS_PATH, pairs)
    print(f"harvested {len(pairs)} labelled pairs from {len(row_uids)} rows under {artifacts}")
    print(f"wrote {PAIRS_PATH}")
    try:
        curve = fit_isotonic(
            [p.score for p in pairs],
            [p.correct for p in pairs],
            min_pairs=config.min_labelled_pairs,
        )
    except CalibrationError as error:
        print(f"NO CURVE: {error}")
        print("calibrated_prob keeps mirroring raw_score (`specs/calibrate.md` §4).")
        return 1
    digest = hashlib.sha256(PAIRS_PATH.read_bytes()).hexdigest()[:16]
    write_curve(CURVE_PATH, curve, source=f"pairs.jsonl sha256:{digest} ({len(pairs)} pairs)")
    print(f"wrote {CURVE_PATH}")
    print()
    print(format_report(build_report(pairs, curve, min_pairs=config.min_labelled_pairs)))
    print()
    print(
        f"tau_abstain is {config.tau_abstain} "
        + ("(abstention OFF)" if config.tau_abstain == 0.0 else "(abstention ON)")
        + " — [PROVISIONAL — Q3]; the trade-off table above is what setting it buys."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
