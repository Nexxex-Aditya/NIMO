"""Characteristics configuration — `config/characteristics.yaml`."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "characteristics.yaml"


class CharacteristicsConfigError(Exception):
    """`config/characteristics.yaml` is missing, malformed, or missing a key."""


@dataclass(frozen=True)
class PracticeDefault:
    """The value the labelled data uses when the evidence is silent, where
    that differs from (or is absent from) the guideline's written default.
    Measured on `dev`; `evidence` is the measurement, rendered into the
    prompt so the model sees why (`specs/characteristics.md` §2a)."""

    value: str
    evidence: str


@dataclass(frozen=True)
class CharacteristicsConfig:
    body_text_chars: int
    use_image_evidence: bool
    max_value_retries: int
    excerpt_prefix_chars: int
    excerpt_window_chars: int
    excerpt_anchor_terms: tuple[str, ...]
    practice_defaults: dict[str, PracticeDefault]  # characteristic -> default; str keys


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
    prefix = data.get("excerpt_prefix_chars")
    if isinstance(prefix, bool) or not isinstance(prefix, int) or prefix < 0:
        raise CharacteristicsConfigError(f"{path}: `excerpt_prefix_chars` must be >= 0.")
    window = data.get("excerpt_window_chars")
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise CharacteristicsConfigError(f"{path}: `excerpt_window_chars` must be >= 1.")
    anchors = data.get("excerpt_anchor_terms")
    if not isinstance(anchors, list) or not anchors or not all(isinstance(a, str) for a in anchors):
        raise CharacteristicsConfigError(
            f"{path}: `excerpt_anchor_terms` must be a non-empty list of strings (a bare YAML "
            f"word like `on` parses as a boolean — quote it)."
        )
    if prefix > chars:
        raise CharacteristicsConfigError(
            f"{path}: `excerpt_prefix_chars` exceeds `body_text_chars`."
        )
    return CharacteristicsConfig(
        body_text_chars=chars,
        use_image_evidence=images,
        max_value_retries=retries,
        excerpt_prefix_chars=prefix,
        excerpt_window_chars=window,
        excerpt_anchor_terms=tuple(a.lower() for a in anchors),
        practice_defaults=_practice_defaults(data, path),
    )


def _practice_defaults(data: dict[str, object], path: Path) -> dict[str, PracticeDefault]:
    raw = data.get("practice_defaults")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CharacteristicsConfigError(f"{path}: `practice_defaults` must be a mapping.")
    out: dict[str, PracticeDefault] = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not name.startswith("GLOBAL_"):
            raise CharacteristicsConfigError(
                f"{path}: `practice_defaults` key {name!r} is not a characteristic column."
            )
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("value"), str)
            or not entry["value"].strip()
            or not isinstance(entry.get("evidence"), str)
            or not entry["evidence"].strip()
        ):
            raise CharacteristicsConfigError(
                f"{path}: `practice_defaults.{name}` needs non-empty `value` and `evidence` "
                f"strings — a default without its measurement is a guess (`04` §9)."
            )
        out[name] = PracticeDefault(
            value=entry["value"].strip(), evidence=" ".join(entry["evidence"].split())
        )
    return out
