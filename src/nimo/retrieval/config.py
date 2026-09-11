"""Retrieval configuration — `specs/retrieval.md` §7.

Same shape as `classify/config.py` and `registry/config.py`: one file-reading
path, isolated, so the query and merge functions stay pure.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "retrieval.yaml"


class RetrievalConfigError(Exception):
    """`config/retrieval.yaml` is missing, malformed, or missing a key."""


# `portfolio`: every request fans out to every available engine.
# `rotate`: one engine per query, cycling, next engine on an empty answer
# (`specs/retrieval.md` §5a.7).
EngineMode = Literal["portfolio", "rotate"]


@dataclass(frozen=True)
class RetrievalConfig:
    max_candidates: int
    fetch_budget: int
    per_strategy_limit: int
    strategy_order: tuple[str, ...]
    engines: tuple[str, ...]
    connect_timeout_s: float
    read_timeout_s: float
    max_retries: int
    backoff_base_s: float
    backoff_max_s: float
    min_interval_s: float
    early_exit: bool
    engine_mode: EngineMode
    wait_for_cooldown: bool
    max_cooldown_waits: int
    engine_failure_threshold: int
    engine_cooldown_s: float
    cache_enabled: bool
    cache_ttl_days: float


def _positive_int(data: dict[str, object], key: str, path: Path) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RetrievalConfigError(f"{path}: `{key}` must be a positive integer; got {value!r}.")
    return value


def _positive_float(data: dict[str, object], key: str, path: Path) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise RetrievalConfigError(f"{path}: `{key}` must be a positive number; got {value!r}.")
    return float(value)


def _read_bool(data: dict[str, object], key: str, path: Path) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise RetrievalConfigError(f"{path}: `{key}` must be a boolean; got {value!r}.")
    return value


def _engine_mode(data: dict[str, object], key: str, path: Path) -> EngineMode:
    value = data.get(key)
    if value == "portfolio":
        return "portfolio"
    if value == "rotate":
        return "rotate"
    raise RetrievalConfigError(
        f"{path}: `{key}` must be one of {sorted(get_args(EngineMode))}; got {value!r}."
    )


def _str_tuple(data: dict[str, object], key: str, path: Path) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise RetrievalConfigError(f"{path}: `{key}` must be a non-empty list; got {value!r}.")
    return tuple(str(item) for item in value)


@lru_cache(maxsize=1)
def load_retrieval_config(path: Path = CONFIG_PATH) -> RetrievalConfig:
    """Read and validate. Fails loudly, never defaults (`04` §4, §9)."""
    if not path.exists():
        raise RetrievalConfigError(f"{path} not found — `specs/retrieval.md` §7 requires it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RetrievalConfigError(f"{path} did not parse to a mapping")

    config = RetrievalConfig(
        max_candidates=_positive_int(data, "max_candidates", path),
        fetch_budget=_positive_int(data, "fetch_budget", path),
        per_strategy_limit=_positive_int(data, "per_strategy_limit", path),
        strategy_order=_str_tuple(data, "strategy_order", path),
        engines=_str_tuple(data, "engines", path),
        connect_timeout_s=_positive_float(data, "connect_timeout_s", path),
        read_timeout_s=_positive_float(data, "read_timeout_s", path),
        max_retries=_positive_int(data, "max_retries", path),
        backoff_base_s=_positive_float(data, "backoff_base_s", path),
        backoff_max_s=_positive_float(data, "backoff_max_s", path),
        min_interval_s=_positive_float(data, "min_interval_s", path),
        early_exit=_read_bool(data, "early_exit", path),
        engine_mode=_engine_mode(data, "engine_mode", path),
        wait_for_cooldown=_read_bool(data, "wait_for_cooldown", path),
        max_cooldown_waits=_positive_int(data, "max_cooldown_waits", path),
        engine_failure_threshold=_positive_int(data, "engine_failure_threshold", path),
        engine_cooldown_s=_positive_float(data, "engine_cooldown_s", path),
        cache_enabled=_read_bool(data, "cache_enabled", path),
        cache_ttl_days=_positive_float(data, "cache_ttl_days", path),
    )
    if config.per_strategy_limit > config.max_candidates:
        raise RetrievalConfigError(
            f"{path}: per_strategy_limit ({config.per_strategy_limit}) exceeds max_candidates "
            f"({config.max_candidates}), so one strategy could fill the whole budget and starve "
            f"the others — S5 in particular would crowd out a barcode-exact S1 hit."
        )
    if config.fetch_budget > config.max_candidates:
        raise RetrievalConfigError(
            f"{path}: fetch_budget ({config.fetch_budget}) exceeds max_candidates "
            f"({config.max_candidates}); the runner cannot fetch more candidates than the list "
            f"holds, and early exit keys off fetch_budget (`specs/retrieval.md` §5a.7)."
        )
    return config
