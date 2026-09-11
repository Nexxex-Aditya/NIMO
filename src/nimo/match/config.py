"""Matcher configuration — `specs/match.md` §4, `04` §9.

Every weight is a named config value. `04` §12 lists "magic number in a
scoring function" as a forbidden pattern, and a scoring function is where the
temptation is strongest.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "match.yaml"


class MatchConfigError(Exception):
    """`config/match.yaml` is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class MatchConfig:
    brand_match: float
    variant_overlap: float
    format_consistent: float
    retailer_domain_match: float
    market_signal: float
    size_mismatch_penalty: float
    count_mismatch_penalty: float
    negative_flag_penalty: float
    score_floor: float
    negative_flags: tuple[str, ...]
    listing_url_patterns: tuple[str, ...]
    directory_domains: tuple[str, ...]
    page_text_chars: int
    # P11 — `specs/adjudicate.md`; all [PROVISIONAL] until the gate runs
    adjudicate_gap_threshold: float
    adjudicate_top_k: int
    adjudicate_body_text_chars: int
    adjudicate_max_rationale_chars: int


def _positive_int(block: dict[object, object], key: str, path: Path) -> int:
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MatchConfigError(f"{path}: `adjudication.{key}` must be a positive integer.")
    return value


def _weight(data: dict[str, object], section: str, key: str, path: Path) -> float:
    block = data.get(section)
    if not isinstance(block, dict):
        raise MatchConfigError(f"{path}: `{section}` must be a mapping; got {block!r}.")
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= value <= 1.0:
        raise MatchConfigError(f"{path}: `{section}.{key}` must be in [0, 1]; got {value!r}.")
    return float(value)


@lru_cache(maxsize=1)
def load_match_config(path: Path = CONFIG_PATH) -> MatchConfig:
    if not path.exists():
        raise MatchConfigError(f"{path} not found — `specs/match.md` §7 requires it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MatchConfigError(f"{path} did not parse to a mapping")

    flags = data.get("negative_flags")
    if not isinstance(flags, list) or not flags:
        raise MatchConfigError(f"{path}: `negative_flags` must be a non-empty list.")
    listing = data.get("listing_url_patterns")
    if not isinstance(listing, list) or not listing:
        raise MatchConfigError(f"{path}: `listing_url_patterns` must be a non-empty list.")
    directories = data.get("directory_domains")
    if not isinstance(directories, list) or not directories:
        raise MatchConfigError(f"{path}: `directory_domains` must be a non-empty list.")
    chars = data.get("page_text_chars")
    if isinstance(chars, bool) or not isinstance(chars, int) or chars < 1:
        raise MatchConfigError(f"{path}: `page_text_chars` must be a positive integer.")
    adjudication = data.get("adjudication")
    if not isinstance(adjudication, dict):
        raise MatchConfigError(f"{path}: `adjudication` must be a mapping (`specs/adjudicate.md`).")
    gap = adjudication.get("runner_up_gap_threshold")
    if isinstance(gap, bool) or not isinstance(gap, int | float) or not 0.0 <= gap <= 1.0:
        raise MatchConfigError(f"{path}: `adjudication.runner_up_gap_threshold` must be in [0, 1].")
    top_k = _positive_int(adjudication, "top_k", path)
    body_chars = _positive_int(adjudication, "body_text_chars", path)
    rationale_chars = _positive_int(adjudication, "max_rationale_chars", path)
    floor = data.get("score_floor")
    if isinstance(floor, bool) or not isinstance(floor, int | float) or not 0.0 <= floor < 1.0:
        raise MatchConfigError(f"{path}: `score_floor` must be in [0, 1).")

    config = MatchConfig(
        brand_match=_weight(data, "weights", "brand_match", path),
        variant_overlap=_weight(data, "weights", "variant_overlap", path),
        format_consistent=_weight(data, "weights", "format_consistent", path),
        retailer_domain_match=_weight(data, "weights", "retailer_domain_match", path),
        market_signal=_weight(data, "weights", "market_signal", path),
        size_mismatch_penalty=_weight(data, "penalties", "size_mismatch", path),
        count_mismatch_penalty=_weight(data, "penalties", "count_mismatch", path),
        negative_flag_penalty=_weight(data, "penalties", "negative_flag", path),
        score_floor=float(floor),
        negative_flags=tuple(str(flag).lower() for flag in flags),
        listing_url_patterns=tuple(str(pattern).lower() for pattern in listing),
        directory_domains=tuple(str(host).lower().lstrip(".") for host in directories),
        page_text_chars=chars,
        adjudicate_gap_threshold=float(gap),
        adjudicate_top_k=top_k,
        adjudicate_body_text_chars=body_chars,
        adjudicate_max_rationale_chars=rationale_chars,
    )

    total = (
        config.brand_match
        + config.variant_overlap
        + config.format_consistent
        + config.retailer_domain_match
        + config.market_signal
    )
    if abs(total - 1.0) > 1e-6:
        raise MatchConfigError(
            f"{path}: the five feature weights sum to {total}, not 1.0. They must, so that a "
            f"raw_score is comparable across rows and readable as 'how much of the available "
            f"evidence agreed' rather than as an arbitrary scale."
        )
    return config
