"""LLM configuration — `config/models.yaml`, `05` §3.

Same shape as every other config loader here: one file-reading path, fails
loudly, never defaults. Two rules are enforced at load rather than documented:
the model id must be pinned (`05` §3 forbids `latest`) and the temperature
must be zero (`04` §5 — determinism is non-negotiable).
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "models.yaml"

# `05` §3: "Model version pinned exactly, in config, never 'latest'."
_UNPINNED = frozenset({"", "latest", "default", "auto"})


class LlmConfigError(Exception):
    """`config/models.yaml` is missing, malformed, or violates `05` §3 / `04` §5."""


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    model: str
    endpoint: str
    api_version: str
    temperature: float
    max_output_tokens: int
    request_timeout_s: float
    max_tokens_per_run: int
    max_calls_per_run: int


def _str(data: dict[str, object], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LlmConfigError(f"{path}: `{key}` must be a non-empty string; got {value!r}.")
    return value.strip()


def _positive_int(data: dict[str, object], key: str, path: Path) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LlmConfigError(f"{path}: `{key}` must be a positive integer; got {value!r}.")
    return value


def _number(data: dict[str, object], key: str, path: Path) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise LlmConfigError(f"{path}: `{key}` must be a number; got {value!r}.")
    return float(value)


@lru_cache(maxsize=1)
def load_llm_config(path: Path = CONFIG_PATH) -> LlmConfig:
    """Read and validate. Fails loudly, never defaults (`04` §4, §9)."""
    if not path.exists():
        raise LlmConfigError(f"{path} not found — `specs/adjudicate.md` §6 requires it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise LlmConfigError(f"{path} did not parse to a mapping")

    config = LlmConfig(
        provider=_str(data, "llm_provider", path),
        model=_str(data, "llm_model", path),
        endpoint=_str(data, "llm_endpoint", path),
        api_version=_str(data, "llm_api_version", path),
        temperature=_number(data, "llm_temperature", path),
        max_output_tokens=_positive_int(data, "llm_max_output_tokens", path),
        request_timeout_s=_number(data, "llm_request_timeout_s", path),
        max_tokens_per_run=_positive_int(data, "llm_max_tokens_per_run", path),
        max_calls_per_run=_positive_int(data, "llm_max_calls_per_run", path),
    )
    if config.model.lower() in _UNPINNED:
        raise LlmConfigError(
            f"{path}: `llm_model` is {config.model!r}. `05` §3: the model is pinned exactly, "
            f"never 'latest' — an upstream swap is a silent-quality-shift vector."
        )
    if config.temperature != 0.0:
        raise LlmConfigError(
            f"{path}: `llm_temperature` is {config.temperature}; `04` §5 requires 0 — a re-run "
            f"must be byte-identical, and a sampled answer cannot be."
        )
    if config.request_timeout_s <= 0:
        raise LlmConfigError(f"{path}: `llm_request_timeout_s` must be positive (`04` §6).")
    return config
