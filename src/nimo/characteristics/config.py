"""Characteristics configuration — `config/characteristics.yaml`."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "characteristics.yaml"


class CharacteristicsConfigError(Exception):
    """`config/characteristics.yaml` is missing, malformed, or missing a key."""


@dataclass(frozen=True)
class CharacteristicsConfig:
    body_text_chars: int
    use_image_evidence: bool
    max_value_retries: int


@lru_cache(maxsize=1)
def load_characteristics_config(path: Path = CONFIG_PATH) -> CharacteristicsConfig:
    """Read and validate. Fails loudly, never defaults (`04` §4, §9)."""
    if not path.exists():
        raise CharacteristicsConfigError(
            f"{path} not found — `specs/characteristics.md` requires it"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CharacteristicsConfigError(f"{path} did not parse to a mapping")

    chars = data.get("body_text_chars")
    if isinstance(chars, bool) or not isinstance(chars, int) or chars < 1:
        raise CharacteristicsConfigError(f"{path}: `body_text_chars` must be a positive integer.")
    images = data.get("use_image_evidence")
    if not isinstance(images, bool):
        raise CharacteristicsConfigError(f"{path}: `use_image_evidence` must be a boolean.")
    retries = data.get("max_value_retries")
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        raise CharacteristicsConfigError(f"{path}: `max_value_retries` must be >= 0.")
    if images:
        raise CharacteristicsConfigError(
            f"{path}: `use_image_evidence: true` is not implemented — Q7 (multimodal support) is "
            f"unresolved (`specs/characteristics.md` §2). Leave it false until it is."
        )
    return CharacteristicsConfig(
        body_text_chars=chars, use_image_evidence=images, max_value_retries=retries
    )
