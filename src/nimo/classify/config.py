"""Classifier configuration — `specs/classify.md` §3, §8.

Kept separate from the model so the feature and scoring functions stay pure
and the one file-reading path is isolated, mirroring `normalize/vocab.py`.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "classify.yaml"


class ClassifyConfigError(Exception):
    """`config/classify.yaml` is missing, malformed, or missing a key."""


@dataclass(frozen=True)
class ClassifyConfig:
    """Tunables for the module baseline. Every value is measured — see the
    sweeps in `config/classify.yaml` and `specs/classify.md` §3."""

    ngram_sizes: tuple[int, ...]
    use_brand: bool
    unseen_margin: float


def _read_ngram_sizes(data: dict[str, object], path: Path) -> tuple[int, ...]:
    sizes = data.get("ngram_sizes")
    if not isinstance(sizes, list) or not sizes:
        raise ClassifyConfigError(
            f"{path}: `ngram_sizes` is missing or empty. An empty list would produce "
            f"featureless documents and a classifier that silently predicts one module "
            f"for everything, rather than failing (`04` §4)."
        )
    parsed: list[int] = []
    for size in sizes:
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise ClassifyConfigError(
                f"{path}: `ngram_sizes` must contain positive integers; got {size!r}."
            )
        parsed.append(size)
    return tuple(sorted(set(parsed)))


def _read_bool(data: dict[str, object], key: str, path: Path) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ClassifyConfigError(f"{path}: `{key}` must be a boolean; got {value!r}.")
    return value


def _read_float(data: dict[str, object], key: str, path: Path) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ClassifyConfigError(f"{path}: `{key}` must be a number; got {value!r}.")
    return float(value)


@lru_cache(maxsize=1)
def load_classify_config(path: Path = CONFIG_PATH) -> ClassifyConfig:
    """Read and validate `config/classify.yaml`. Fails loudly, never defaults."""
    if not path.exists():
        raise ClassifyConfigError(f"{path} not found — `specs/classify.md` §8 requires it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ClassifyConfigError(f"{path} did not parse to a mapping")
    return ClassifyConfig(
        ngram_sizes=_read_ngram_sizes(data, path),
        use_brand=_read_bool(data, "use_brand", path),
        unseen_margin=_read_float(data, "unseen_margin", path),
    )
