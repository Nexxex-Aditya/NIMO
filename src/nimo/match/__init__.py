"""P9 matcher — `specs/match.md`. Layer A features, hard rules, write-back.

`04` §13 flags this as HARD-20%: the core algorithmic component, where subtle
wrongness costs the most. No LLM (that is P11's Layer B), no calibration (P10).
"""

from nimo.match.adjudicate import (
    DECISIVE_FIELDS,
    AdjudicationError,
    Adjudicator,
    allowed_answers,
    apply_verdict,
    candidate_block,
    query_block,
    should_adjudicate,
    top_k,
)
from nimo.match.config import CONFIG_PATH, MatchConfig, MatchConfigError, load_match_config
from nimo.match.features import (
    barcode_exact,
    brand_match,
    compute_features,
    count_match,
    format_consistent,
    market_signal,
    negative_flags,
    page_gtin_valid,
    page_text,
    query_gtin_valid,
    retailer_domain_match,
    size_match,
    variant_overlap,
)
from nimo.match.score import (
    GTIN_ACCEPT_REASON,
    ScoredCandidate,
    apply_hard_rules,
    rank_candidates,
    score_candidate,
    select,
    weighted_score,
)
from nimo.match.writeback import (
    WriteBackDecision,
    WriteBackError,
    audit_for,
    build_entity,
    decide,
)

__all__ = [
    "DECISIVE_FIELDS",
    "GTIN_ACCEPT_REASON",
    "AdjudicationError",
    "Adjudicator",
    "allowed_answers",
    "apply_verdict",
    "candidate_block",
    "query_block",
    "should_adjudicate",
    "top_k",
    "CONFIG_PATH",
    "MatchConfig",
    "MatchConfigError",
    "ScoredCandidate",
    "WriteBackDecision",
    "WriteBackError",
    "apply_hard_rules",
    "audit_for",
    "barcode_exact",
    "brand_match",
    "build_entity",
    "compute_features",
    "count_match",
    "decide",
    "format_consistent",
    "load_match_config",
    "market_signal",
    "negative_flags",
    "page_gtin_valid",
    "page_text",
    "query_gtin_valid",
    "rank_candidates",
    "retailer_domain_match",
    "score_candidate",
    "select",
    "size_match",
    "variant_overlap",
    "weighted_score",
]
