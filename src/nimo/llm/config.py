"""LLM configuration — `config/models.yaml`, `05` §3.

Same shape as every other config loader here: one file-reading path, fails
loudly, never defaults. Two rules are enforced at load rather than documented:
the model id must be pinned (`05` §3 forbids `latest`) and the temperature
must be zero (`04` §5 — determinism is non-negotiable).
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    temperature: (
        float | None
    )  # None == not sent; the model runs at its default (measured: required)
    max_output_tokens: int
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"]
    request_timeout_s: float
    max_tokens_per_run: int
    max_calls_per_run: int


def _max_tokens_param(
    data: dict[str, object], path: Path
) -> Literal["max_tokens", "max_completion_tokens"]:
    value = data.get("llm_max_tokens_param")
    if value == "max_tokens":
        return "max_tokens"
    if value == "max_completion_tokens":
        return "max_completion_tokens"
    raise LlmConfigError(
        f"{path}: `llm_max_tokens_param` must be `max_tokens` or `max_completion_tokens`; "
        f"got {value!r}."
    )


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
        temperature=(
            None if data.get("llm_temperature") is None else _number(data, "llm_temperature", path)
        ),
        max_output_tokens=_positive_int(data, "llm_max_output_tokens", path),
        max_tokens_param=_max_tokens_param(data, path),
        request_timeout_s=_number(data, "llm_request_timeout_s", path),
        max_tokens_per_run=_positive_int(data, "llm_max_tokens_per_run", path),
        max_calls_per_run=_positive_int(data, "llm_max_calls_per_run", path),
    )
    if config.model.lower() in _UNPINNED:
        raise LlmConfigError(
            f"{path}: `llm_model` is {config.model!r}. `05` §3: the model is pinned exactly, "
            f"never 'latest' — an upstream swap is a silent-quality-shift vector."
        )
    if config.temperature is not None and config.temperature != 0.0:
        raise LlmConfigError(
            f"{path}: `llm_temperature` is {config.temperature}; `04` §5 requires 0 — a re-run "
            f"must be byte-identical, and a sampled answer cannot be. Use `null` only for a "
            f"model that rejects the parameter (measured for the pinned CIS model)."
        )
    if config.request_timeout_s <= 0:
        raise LlmConfigError(f"{path}: `llm_request_timeout_s` must be positive (`04` §6).")
    return config
