"""P10 calibration & abstention — `specs/calibrate.md`. HARD-20% (`04` §13)."""

from nimo.calibrate.harvest import LabelledPair, harvest_pairs, read_pairs, write_pairs
from nimo.calibrate.isotonic import CalibrationError, IsotonicCurve, fit_isotonic
from nimo.calibrate.report import (
    AbstentionPoint,
    CalibrationReport,
    ReliabilityBin,
    build_report,
    format_report,
)

__all__ = [
    "AbstentionPoint",
    "CalibrationError",
    "CalibrationReport",
    "IsotonicCurve",
    "LabelledPair",
    "ReliabilityBin",
    "build_report",
    "fit_isotonic",
    "format_report",
    "harvest_pairs",
    "read_pairs",
    "write_pairs",
]
