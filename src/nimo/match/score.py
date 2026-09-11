"""Hard rules, weighted scoring and ranking — `03` §4 stage 4.

Pure. `04` §13 flags this as HARD-20%: it is the component whose subtle
wrongness costs the most, because a confident wrong URL looks exactly like a
confident right one.

**The hard rules are evaluated first and override the weighted sum.** That
ordering is the design: `03` §4 stage 4 puts GTIN equality above every text
feature because "a confirmed different GTIN is a different product regardless
of how similar the text is", and P6 measured the consequence of ignoring it —
Sensodyne Pronamel Extra Fresh and its Whitening variant differ by two words
in a fifteen-word description and no similarity measure separates them.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nimo.contracts import CandidateEvidence, MatchFeatures, ProductQuery, Selection
from nimo.match.config import MatchConfig
from nimo.match.features import compute_features

if TYPE_CHECKING:
    # Type-only: calibration CONSUMES the matcher (harvest recomputes scores),
    # so a runtime import here would be circular. The matcher only ever calls
    # `curve.predict(score)`; the curve is fitted and loaded elsewhere.
    from nimo.calibrate.isotonic import IsotonicCurve

# The one reason string other modules branch on: calibration bypasses it and
# adjudication refuses to second-guess it. A constant so a reworded reason
# cannot silently break either.
GTIN_ACCEPT_REASON = "gtin_exact: page GTIN equals the query barcode"


@dataclass(frozen=True)
class ScoredCandidate:
    """One candidate with its features, score and why. `reason` is the audit
    surface `03` §1 promises — "when row 217 picks the wrong URL, we need to
    see *which feature* misfired"."""

    evidence: CandidateEvidence
    features: MatchFeatures
    score: float
    rejected: bool
    reason: str


def apply_hard_rules(
    features: MatchFeatures, weighted: float, config: MatchConfig
) -> tuple[float, bool, str]:
    """`(score, rejected, reason)`. `03` §4 stage 4, in its stated order."""
    # 1. GTIN accept — near-decisive, stops everything else.
    if features.barcode_exact is True:
        return 1.0, False, GTIN_ACCEPT_REASON

    # 2. GTIN reject — a confirmed different GTIN is a different product,
    #    however similar the text. This is the rule that has to beat text.
    if features.barcode_exact is False:
        return 0.0, True, "gtin_conflict: page GTIN differs from the query barcode"

    score = weighted
    reasons: list[str] = []

    # 3. Size mismatch — DEMOTION, not rejection. `03` §4 stage 4: "retailer
    #    pages sometimes list a range." A demoted candidate can still win when
    #    nothing better exists, and with 4 of 10 pages bot-walled that happens.
    if features.size_match == "mismatch":
        score *= 1.0 - config.size_mismatch_penalty
        reasons.append("size_mismatch")

    # 4. Count mismatch — multipack count is a HARD identity attribute
    #    (`03` §4 stage 0): a 2-pack and a single are different products.
    if features.count_match == "mismatch":
        score *= 1.0 - config.count_mismatch_penalty
        reasons.append("count_mismatch")

    # 5. Negative flags — a refill page for a non-refill query is a different
    #    SKU of the same line.
    for flag in features.negative_flags:
        score *= 1.0 - config.negative_flag_penalty
        reasons.append(f"negative:{flag}")

    if reasons:
        # Floored rather than allowed to reach zero: a demoted candidate must
        # stay rankable and distinguishable from a REJECTED one. Rejection is
        # a separate, explicit outcome that only the GTIN conflict produces.
        score = max(score, config.score_floor)
        return score, False, "demoted: " + ", ".join(reasons)

    return score, False, "weighted"


def weighted_score(features: MatchFeatures, config: MatchConfig) -> float:
    """The five-feature weighted sum, before hard rules.

    Weights sum to 1.0 (asserted at config load), so a raw score reads as
    "how much of the available evidence agreed" rather than as an arbitrary
    scale. `format_consistent is None` contributes nothing rather than
    counting as disagreement — the query simply has no format to check, which
    is the case for 160 of 412 `dev` rows.
    """
    score = 0.0
    score += config.brand_match * features.brand_match
    score += config.variant_overlap * features.variant_overlap
    if features.format_consistent is not None:
        score += config.format_consistent * (1.0 if features.format_consistent else 0.0)
    score += config.retailer_domain_match * (1.0 if features.retailer_domain_match else 0.0)
    score += config.market_signal * features.market_signal
    return score


def score_candidate(
    query: ProductQuery,
    evidence: CandidateEvidence,
    config: MatchConfig,
    retailer_domain: str | None = None,
    curve: "IsotonicCurve | None" = None,
) -> ScoredCandidate:
    """Features, then hard rules, then calibration if a curve exists."""
    features = compute_features(query, evidence, config, retailer_domain)
    weighted = weighted_score(features, config)
    score, rejected, reason = apply_hard_rules(features, weighted, config)

    # `calibrated_prob` is a probability ONLY when a fitted curve is supplied.
    # Without one it MIRRORS `raw_score` and is not a probability — a field
    # with that name holding an uncalibrated number is the plausible-wrong-
    # value shape `05` §5 names, so the mirror state is tested explicitly and
    # abstention stays off (`tau_abstain: 0.0`) until a curve is loaded.
    # Hard-rule outcomes bypass the curve: a GTIN accept is 1.0 and a GTIN
    # reject is 0.0 by identity, not by text similarity, and the curve was
    # fitted on the text score alone (`specs/calibrate.md` §1).
    if curve is not None and not rejected and reason != GTIN_ACCEPT_REASON:
        calibrated = curve.predict(weighted)
    else:
        calibrated = score
    scored_features = features.model_copy(
        update={"raw_score": score, "calibrated_prob": calibrated}
    )
    return ScoredCandidate(
        evidence=evidence,
        features=scored_features,
        score=score,
        rejected=rejected,
        reason=reason,
    )


def rank_candidates(
    query: ProductQuery,
    candidates: list[CandidateEvidence],
    config: MatchConfig,
    retailer_domain: str | None = None,
    curve: "IsotonicCurve | None" = None,
) -> list[ScoredCandidate]:
    """Every candidate, best first. Rejected ones sort last but are KEPT.

    `03` §4 stage 3: "A page that fails extraction gets `fetch_status` set and
    stays in the record. Do not drop it — a systematic block on one retailer
    is a finding, not noise." The same applies to a GTIN-rejected candidate:
    dropping it loses the evidence that we looked and found a conflict.

    Ties break on URL so the ranking is deterministic (`04` §5).
    """
    scored = [
        score_candidate(query, evidence, config, retailer_domain, curve) for evidence in candidates
    ]
    return sorted(scored, key=lambda item: (item.rejected, -item.score, item.evidence.url))


def select(
    query: ProductQuery,
    candidates: list[CandidateEvidence],
    config: MatchConfig,
    retailer_domain: str | None = None,
    curve: "IsotonicCurve | None" = None,
) -> tuple[Selection, list[ScoredCandidate]]:
    """The chosen candidate and the full ranking behind it.

    Returns the ranking too, because `03` §1 makes per-feature transparency a
    design goal and `03` §4 stage 8 writes it to `trace.jsonl`.

    **No abstention at P9.** `03` §4 stage 4 gates abstention on
    `calibrated_prob < τ`, and there is no calibration yet (§5 of
    `specs/match.md`), so abstaining here would be thresholding a number that
    does not mean what the threshold assumes.
    """
    ranked = rank_candidates(query, candidates, config, retailer_domain, curve)
    usable = [item for item in ranked if not item.rejected]

    if not usable:
        return (
            Selection(
                url=None,
                page_title=None,
                confidence=0.0,
                runner_up_gap=0.0,
                features=None,
                adjudicated_by_llm=False,
                resolution_tier="tier2_retrieval",
                adjudication=None,
            ),
            ranked,
        )

    best = usable[0]
    runner_up = usable[1].score if len(usable) > 1 else 0.0
    return (
        Selection(
            url=best.evidence.url,
            page_title=best.evidence.title,
            confidence=best.score,
            runner_up_gap=best.score - runner_up,
            features=best.features,
            adjudicated_by_llm=False,
            resolution_tier="tier2_retrieval",
            adjudication=None,
        ),
        ranked,
    )
