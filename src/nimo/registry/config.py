"""Registry thresholds — `specs/registry.md` §4d, §4e.

Separate from the store so the lookup functions stay pure and the one
file-reading path is isolated, mirroring `normalize/vocab.py` and
`classify/config.py`.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "thresholds.yaml"


class ThresholdConfigError(Exception):
    """`config/thresholds.yaml` is missing, malformed, or internally unsafe."""


@dataclass(frozen=True)
class RegistryThresholds:
    tau_ann: float  # Tier-1 hit threshold
    tau_merge: float  # write-back threshold; must exceed tau_ann


def _read_float(data: dict[str, object], key: str, path: Path) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ThresholdConfigError(f"{path}: `{key}` must be a number; got {value!r}.")
    return float(value)


@lru_cache(maxsize=1)
def load_thresholds(path: Path = CONFIG_PATH) -> RegistryThresholds:
    """Read and validate the registry thresholds.

    The `tau_merge > tau_ann` invariant is **asserted here, not merely
    documented**. `03` §4 stage 4 requires it and `05` §4 explains why getting
    it backwards is unrecoverable: a merge written at lower confidence than a
    lookup will accept poisons the registry with entries no later lookup can
    tell apart from good ones.
    """
    if not path.exists():
        raise ThresholdConfigError(f"{path} not found — `specs/registry.md` §8 requires it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ThresholdConfigError(f"{path} did not parse to a mapping")

    tau_ann = _read_float(data, "tau_ann", path)
    tau_merge = _read_float(data, "tau_merge", path)

    if not 0.0 < tau_ann <= 1.0:
        raise ThresholdConfigError(
            f"{path}: tau_ann must be in (0, 1]; got {tau_ann}. A tau_ann of 0 would make "
            f"every blocked pair a Tier-1 hit, merging 379 dev pairs of which ~4 are "
            f"genuinely the same product (`specs/registry.md` §4a)."
        )
    if tau_merge <= tau_ann:
        raise ThresholdConfigError(
            f"{path}: tau_merge ({tau_merge}) must exceed tau_ann ({tau_ann}). `03` §4 stage 4 "
            f"requires the write-back threshold to be stricter than the lookup threshold; "
            f"inverted, the registry accumulates merges that later lookups cannot distinguish "
            f"from confirmed ones (`05` §4)."
        )
    if tau_merge > 1.0:
        raise ThresholdConfigError(f"{path}: tau_merge must be <= 1.0; got {tau_merge}.")
    return RegistryThresholds(tau_ann=tau_ann, tau_merge=tau_merge)
