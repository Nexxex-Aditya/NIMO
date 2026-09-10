"""Fetcher configuration — `specs/fetch.md` §7.

Same shape as every other config loader here: one file-reading path, isolated,
so the fetching logic stays free of I/O it does not own.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "fetch.yaml"


class FetchConfigError(Exception):
    """`config/fetch.yaml` is missing, malformed, or missing a key."""


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str
    min_interval_s: float
    max_concurrent_per_host: int
    respect_robots: bool
    connect_timeout_s: float
    read_timeout_s: float
    max_response_bytes: int
    max_redirects: int
    max_retries: int
    backoff_base_s: float
    backoff_max_s: float
    cache_enabled: bool
    cache_ttl_days: float
    failure_cache_ttl_hours: float


def _num(data: dict[str, object], key: str, path: Path) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise FetchConfigError(f"{path}: `{key}` must be a positive number; got {value!r}.")
    return float(value)


def _int(data: dict[str, object], key: str, path: Path) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FetchConfigError(f"{path}: `{key}` must be a positive integer; got {value!r}.")
    return value


def _bool(data: dict[str, object], key: str, path: Path) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise FetchConfigError(f"{path}: `{key}` must be a boolean; got {value!r}.")
    return value


def _text(data: dict[str, object], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FetchConfigError(f"{path}: `{key}` must be a non-empty string; got {value!r}.")
    return value


@lru_cache(maxsize=1)
def load_fetch_config(path: Path = CONFIG_PATH) -> FetchConfig:
    """Read and validate. Fails loudly, never defaults (`04` §4, §9)."""
    if not path.exists():
        raise FetchConfigError(f"{path} not found — `specs/fetch.md` §7 requires it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FetchConfigError(f"{path} did not parse to a mapping")

    config = FetchConfig(
        user_agent=_text(data, "user_agent", path),
        min_interval_s=_num(data, "min_interval_s", path),
        max_concurrent_per_host=_int(data, "max_concurrent_per_host", path),
        respect_robots=_bool(data, "respect_robots", path),
        connect_timeout_s=_num(data, "connect_timeout_s", path),
        read_timeout_s=_num(data, "read_timeout_s", path),
        max_response_bytes=_int(data, "max_response_bytes", path),
        max_redirects=_int(data, "max_redirects", path),
        max_retries=_int(data, "max_retries", path),
        backoff_base_s=_num(data, "backoff_base_s", path),
        backoff_max_s=_num(data, "backoff_max_s", path),
        cache_enabled=_bool(data, "cache_enabled", path),
        cache_ttl_days=_num(data, "cache_ttl_days", path),
        failure_cache_ttl_hours=_num(data, "failure_cache_ttl_hours", path),
    )
    if "nimo" not in config.user_agent.lower():
        raise FetchConfigError(
            f"{path}: `user_agent` must identify this project (`04` §6 requires an identifying "
            f"UA). A browser-impersonation string would disguise exactly the blocking `05` §5 "
            f"asks us to measure."
        )
    return config
