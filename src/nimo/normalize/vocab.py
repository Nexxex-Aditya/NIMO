"""Vocabulary loading for the normalizer — `specs/normalize.md` §1c, §4, §5.

Kept separate from parsing so the parsing functions stay pure and the one
file-reading path is isolated and cached.
"""

from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "normalize.yaml"


class VocabError(Exception):
    """`config/normalize.yaml` is missing, malformed, or missing a key."""


def _read_list(data: object, key: str, path: Path) -> frozenset[str]:
    if not isinstance(data, dict):
        raise VocabError(f"{path} did not parse to a mapping")
    values = data.get(key)
    if not isinstance(values, list) or not values:
        raise VocabError(
            f"{path}: `{key}` is missing or empty. `specs/normalize.md` requires it; "
            f"an empty vocabulary would silently disable a whole normalization rule "
            f"rather than failing (`04` §4)."
        )
    return frozenset(str(value).strip().lower() for value in values)


@lru_cache(maxsize=1)
def load_vocabularies(path: Path = CONFIG_PATH) -> tuple[frozenset[str], ...]:
    """(unit_of_sale_tokens, format_hints, stopwords, multiplier_claim_words).

    A tuple of frozensets rather than a dict, so nothing bare-dict-shaped
    crosses a module boundary (`04` §3) and the result stays hashable for
    `lru_cache`.
    """
    if not path.exists():
        raise VocabError(f"{path} not found — `specs/normalize.md` §1c/§4/§5 require it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return (
        _read_list(data, "unit_of_sale_tokens", path),
        _read_list(data, "format_hints", path),
        _read_list(data, "stopwords", path),
        _read_list(data, "multiplier_claim_words", path),
    )
