"""Calibration config and the persisted curve — `specs/calibrate.md` §2, §5.

`config/thresholds.yaml` carries `min_labelled_pairs` and `tau_abstain`; the
fitted curve lives in `data/calibration/curve.json` beside the pairs it was
fitted on, committed, so the fit is reproducible from the repo and a run
loads the same curve everywhere.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from nimo.calibrate.isotonic import CalibrationError, IsotonicCurve

THRESHOLDS_PATH = Path(__file__).resolve().parents[3] / "config" / "thresholds.yaml"
CURVE_PATH = Path(__file__).resolve().parents[3] / "data" / "calibration" / "curve.json"
PAIRS_PATH = Path(__file__).resolve().parents[3] / "data" / "calibration" / "pairs.jsonl"


class CalibrationConfigError(Exception):
    """`config/thresholds.yaml` lacks or mis-states a calibration key."""


@dataclass(frozen=True)
class CalibrationConfig:
    min_labelled_pairs: int
    tau_abstain: float  # 0.0 == abstention OFF [PROVISIONAL — Q3]


@lru_cache(maxsize=1)
def load_calibration_config(path: Path = THRESHOLDS_PATH) -> CalibrationConfig:
    if not path.exists():
        raise CalibrationConfigError(f"{path} not found")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CalibrationConfigError(f"{path} did not parse to a mapping")
    minimum = data.get("min_labelled_pairs")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 2:
        raise CalibrationConfigError(f"{path}: `min_labelled_pairs` must be an integer >= 2.")
    tau = data.get("tau_abstain")
    if isinstance(tau, bool) or not isinstance(tau, int | float) or not 0.0 <= tau < 1.0:
        raise CalibrationConfigError(f"{path}: `tau_abstain` must be in [0, 1); 0 == off.")
    return CalibrationConfig(min_labelled_pairs=minimum, tau_abstain=float(tau))


def write_curve(path: Path, curve: IsotonicCurve, *, source: str) -> None:
    """Persist a fitted curve. `source` records what it was fitted from."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "thresholds": list(curve.thresholds),
                "values": list(curve.values),
                "n_pairs": curve.n_pairs,
                "n_positive": curve.n_positive,
                "source": source,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def read_curve(path: Path) -> IsotonicCurve | None:
    """The persisted curve, or `None` when none has been fitted — the state
    in which `calibrated_prob` mirrors `raw_score` (`specs/calibrate.md` §4).
    A malformed file raises: a curve that quietly fails to load would make a
    calibrated run look uncalibrated with nothing to find later."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        curve = IsotonicCurve(
            thresholds=tuple(float(t) for t in data["thresholds"]),
            values=tuple(float(v) for v in data["values"]),
            n_pairs=int(data["n_pairs"]),
            n_positive=int(data["n_positive"]),
        )
    except (ValueError, KeyError, TypeError) as error:
        raise CalibrationError(f"{path} is not a readable curve: {error}") from error
    if len(curve.thresholds) != len(curve.values) or not curve.values:
        raise CalibrationError(f"{path}: thresholds and values must align and be non-empty")
    if list(curve.values) != sorted(curve.values):
        raise CalibrationError(f"{path}: values are not monotone — not an isotonic curve")
    return curve
