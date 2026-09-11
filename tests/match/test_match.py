"""P9 matcher tests — `specs/match.md` §9, `04` §8.

`04` §8: "**Adversarial matcher cases**, hand-built: same brand different size;
same product different multipack count; refill vs complete pack; a page with a
conflicting GTIN; a page with no structured data at all. The brief's success
criterion is 'distinguish the correct product from similar or misleading
matches' — **these tests *are* that criterion**."

They also test what the gate cannot: **zero of the six gold rows have a usable
GTIN**, so Precision@1 on the gold set can never exercise the hard rules that
carry all of `qa` (`specs/match.md` §1).

Zero network, zero LLM.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nimo.contracts import CandidateEvidence, DescTokens, ProductQuery
from nimo.extract import FetchStatus
from nimo.match import (
    MatchConfigError,
    compute_features,
    decide,
    load_match_config,
    rank_candidates,
    score_candidate,
    select,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pages"
TS = datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)
CONFIG = load_match_config()


def query(
    *,
    barcode: str | None = None,
    corrupt: bool = False,
    brand: str = "AQUAFRESH",
    desc: str = "aquafresh whitening pump toothpaste 100ml",
    variants: list[str] | None = None,
    size_ml: float | None = 100.0,
    size_g: float | None = None,
    count: int | None = None,
    hints: list[str] | None = None,
) -> ProductQuery:
    return ProductQuery(
        row_uid="dev:0",
        nan_key=1,
        item_code=1,
        barcode=barcode,
        barcode_raw=barcode,
        barcode_corrupt=corrupt,
        brand_raw=f"{brand} (X)",
        brand=brand,
        brand_owner="X",
        brand_encoding_suspect=False,
        retailer_raw="P00R4 (GB) BOOTS",
        retailer="BOOTS",
        countries=["GB"],
        desc_raw=desc,
        desc_encoding_suspect=False,
        desc_clean=desc,
        tokens=DescTokens(
            variant_terms=variants if variants is not None else ["whitening"],
            size_value=size_ml or size_g,
            size_unit="ml" if size_ml else ("g" if size_g else None),
            size_ml_equiv=size_ml,
            size_g_equiv=size_g,
            count=count,
            format_hints=hints if hints is not None else ["toothpaste"],
            stripped_junk=[],
        ),
    )


def page(
    url: str = "https://boots.com/p",
    title: str = "Aquafresh Whitening Pump Toothpaste 100ml",
    gtin: str | None = None,
    body: str = "",
    status: FetchStatus = "ok",
) -> CandidateEvidence:
    return CandidateEvidence(
        url=url,
        fetch_status=status,
        fetched_at=TS,
        content_hash="sha256:test",
        title=title,
        jsonld_product={"gtin13": gtin} if gtin else None,
        gtin=gtin,
        og={},
        breadcrumbs=[],
        body_text=body,
        image_urls=[],
        price=None,
        parse_warnings=[],
    )


# =============================================================================
# The five adversarial cases `04` §8 names, one test each
# =============================================================================


def test_adversarial_conflicting_gtin_beats_near_identical_text() -> None:
    """**The rule that has to beat text.** The wrong page is textually
    *better* than the right one — identical title, matching size. Only the
    GTIN separates them, which is why `03` §4 stage 4 makes it a hard rule:
    "a confirmed different GTIN is a different product regardless of how
    similar the text is"."""
    subject = query(barcode="5014697056627")
    right = page(url="https://a.test/p", title="Aquafresh Pump 100ml", gtin="5014697056627")
    wrong = page(
        url="https://b.test/p",
        title="Aquafresh Whitening Pump Toothpaste 100ml",  # a BETTER text match
        gtin="9999999999999",
    )
    ranked = rank_candidates(subject, [wrong, right], CONFIG)
    assert ranked[0].evidence.url == "https://a.test/p"
    assert ranked[0].score == 1.0
    assert ranked[-1].rejected is True
    assert "gtin_conflict" in ranked[-1].reason


def test_adversarial_same_brand_different_size_is_demoted() -> None:
    subject = query(size_ml=100.0)
    right = page(url="https://a.test/p", title="Aquafresh Whitening Pump Toothpaste 100ml")
    wrong = page(url="https://b.test/p", title="Aquafresh Whitening Pump Toothpaste 75ml")
    ranked = rank_candidates(subject, [wrong, right], CONFIG)
    assert ranked[0].evidence.url == "https://a.test/p"
    assert "size_mismatch" in ranked[1].reason


def test_adversarial_same_product_different_multipack_count_is_demoted() -> None:
    """`03` §4 stage 0: multipack count is a HARD identity attribute. A 2-pack
    and a single are different products."""
    subject = query(desc="aquafresh whitening toothpaste 100ml", count=None)
    single = page(url="https://a.test/p", title="Aquafresh Whitening Toothpaste 100ml")
    pack = page(url="https://b.test/p", title="Aquafresh Whitening Toothpaste 100ml pack of 4")
    ranked = rank_candidates(subject, [pack, single], CONFIG)
    assert ranked[0].evidence.url == "https://a.test/p"
    assert "count_mismatch" in ranked[1].reason


def test_adversarial_refill_page_for_a_non_refill_query_is_demoted() -> None:
    subject = query(
        brand="ORAL B",
        desc="oral b electric toothbrush complete pack",
        variants=["electric"],
        size_ml=None,
        hints=["toothbrush"],
    )
    complete = page(url="https://a.test/p", title="Oral-B Electric Toothbrush Complete Pack")
    refill = page(url="https://b.test/p", title="Oral-B Electric Toothbrush Refill Heads 4 pack")
    ranked = rank_candidates(subject, [refill, complete], CONFIG)
    assert ranked[0].evidence.url == "https://a.test/p"
    assert "negative:refill" in ranked[1].reason


def test_adversarial_page_with_no_structured_data_still_ranks() -> None:
    """The Amazon fixture: 1.4 MB, no JSON-LD, no OpenGraph. `03` §4 stage 3
    keeps such a page in the record; the matcher must be able to rank it on
    text alone rather than discarding it."""
    subject = query(
        brand="ULTRADEX",
        desc="ultradex mouthwash sachets 15ml",
        variants=["mouthwash", "sachets"],
        size_ml=15.0,
        hints=["mouthwash"],
    )
    from nimo.extract import extract_evidence

    amazon = extract_evidence(
        "https://amazon.co.uk/dp/B07CM9LMX2",
        (FIXTURES / "amazon.html").read_text(encoding="utf-8"),
        TS,
    )
    assert amazon.gtin is None and amazon.og == {}
    scored = score_candidate(subject, amazon, CONFIG)
    assert scored.rejected is False
    assert scored.score > 0.0
    assert scored.features.barcode_exact is None  # cannot evaluate, not "no match"


def test_adversarial_search_listing_is_demoted_below_a_product_page() -> None:
    """**Measured on the first live run**: 2 of 5 qa rows selected an Amazon
    search-results page. A listing mentions the brand, the size and every
    variant term at once — exactly why the weighted features like it — and
    identifies no product at all."""
    subject = query(
        brand="ORAL B",
        desc="oral b pro expert toothbrush",
        variants=["pro", "expert"],
        size_ml=None,
        hints=["toothbrush"],
    )
    product = page(
        url="https://boots.com/oral-b-pro-expert-toothbrush-10012345",
        title="Oral-B Pro Expert Toothbrush",
    )
    listing = page(
        url="https://amazon.co.uk/oral-b-toothbrush/s?k=oral+b+pro+expert+toothbrush",
        title="Amazon.co.uk: oral b pro expert toothbrush",
    )
    ranked = rank_candidates(subject, [listing, product], CONFIG)
    assert ranked[0].evidence.url.startswith("https://boots.com")
    assert "negative:listing_page" in ranked[1].reason


def test_a_product_url_containing_search_in_a_slug_is_not_a_listing() -> None:
    """The patterns are unambiguous markers, not bare words — a product slug
    that happens to contain `search` must not be demoted."""
    subject = query()
    fine = page(url="https://boots.com/research-labs-whitening-toothpaste-100ml")
    assert "listing_page" not in score_candidate(subject, fine, CONFIG).features.negative_flags


# =============================================================================
# The corrupt-barcode trap — `01` §3, and 394 of 412 dev rows
# =============================================================================


def test_a_corrupt_query_barcode_is_never_compared() -> None:
    """`01` §3 is an entire document about an identifier silently reshaped by
    a spreadsheet. Comparing the rounded `5000000000000` against a real page
    GTIN would REJECT every correct candidate for that row."""
    subject = query(barcode="5000000000000", corrupt=True)
    candidate = page(gtin="5014697056627")
    features = compute_features(subject, candidate, CONFIG)
    assert features.barcode_exact is None
    assert not score_candidate(subject, candidate, CONFIG).rejected


def test_a_short_non_gtin_query_barcode_is_never_compared() -> None:
    """`01` §3: 17 of dev's 35 surviving barcodes are 6-7 digits and are not
    GTINs at all."""
    features = compute_features(query(barcode="266611"), page(gtin="5014697056627"), CONFIG)
    assert features.barcode_exact is None


def test_a_short_page_gtin_is_never_compared() -> None:
    features = compute_features(query(barcode="5014697056627"), page(gtin="1234"), CONFIG)
    assert features.barcode_exact is None


# =============================================================================
# Two retailers, one product — scoring the PRODUCT not the URL string
# =============================================================================


def test_two_retailers_with_the_same_gtin_both_beat_an_unrelated_page() -> None:
    """**The finding that motivates changing the gate.** chemist-4-u and
    pharmazondirect publish the same GTIN for one Eucryl toothpowder, and the
    gold label for that row (`dev:410`) names a *third* retailer. Scoring the
    URL string marks both wrong; scoring the product marks both right."""
    from nimo.extract import extract_evidence

    subject = query(
        barcode="5011309895612",
        brand="EUCRYL",
        desc="eucryl toothpowder freshmint 50g",
        variants=["freshmint", "toothpowder"],
        size_ml=None,
        size_g=50.0,
        hints=[],
    )
    left = extract_evidence(
        "https://chemist-4-u.com/p", (FIXTURES / "chemist4u.html").read_text(encoding="utf-8"), TS
    )
    right = extract_evidence(
        "https://pharmazondirect.com/p",
        (FIXTURES / "pharmazon.html").read_text(encoding="utf-8"),
        TS,
    )
    unrelated = page(url="https://z.test/p", title="Colgate Total Toothpaste 75ml", gtin=None)

    ranked = rank_candidates(subject, [unrelated, left, right], CONFIG)
    winners = {item.evidence.url for item in ranked[:2]}
    assert winners == {"https://chemist-4-u.com/p", "https://pharmazondirect.com/p"}
    assert all(item.score == 1.0 for item in ranked[:2])
    assert ranked[-1].evidence.url == "https://z.test/p"


# =============================================================================
# Market is scored, never a filter (`01` §5, `04` §12)
# =============================================================================


def test_a_cross_market_candidate_can_still_win() -> None:
    """`01` §5: the organizers' own `sample_output` resolves a `FR,GB` item to
    an Amazon.in page. `04` §12 lists a country hard-filter as forbidden — so
    a better-matching foreign page must be able to beat a weak local one."""
    subject = query()
    foreign_good = page(
        url="https://amazon.in/dp/X", title="Aquafresh Whitening Pump Toothpaste 100ml"
    )
    local_poor = page(url="https://boots.co.uk/other", title="Colgate Total 75ml")
    ranked = rank_candidates(subject, [local_poor, foreign_good], CONFIG)
    assert ranked[0].evidence.url == "https://amazon.in/dp/X"
    assert not any(item.rejected for item in ranked)


# =============================================================================
# Failed fetches, ranking, determinism
# =============================================================================


def test_a_bot_walled_candidate_ranks_last_but_is_not_dropped() -> None:
    """`03` §4 stage 3: do not drop it — a systematic block on one retailer is
    a finding, not noise. Measured: 4 of 10 real pages are bot walls."""
    subject = query()
    good = page(url="https://a.test/p")
    wall = page(url="https://b.test/p", title="Pardon Our Interruption", status="blocked")
    ranked = rank_candidates(subject, [wall, good], CONFIG)
    assert len(ranked) == 2
    assert ranked[0].evidence.url == "https://a.test/p"
    assert ranked[-1].evidence.url == "https://b.test/p"


def test_ranking_is_deterministic_with_ties_broken_by_url() -> None:
    subject = query()
    identical = [page(url=f"https://{host}.test/p") for host in ("c", "a", "b")]
    first = [item.evidence.url for item in rank_candidates(subject, identical, CONFIG)]
    second = [
        item.evidence.url for item in rank_candidates(subject, list(reversed(identical)), CONFIG)
    ]
    assert first == second == ["https://a.test/p", "https://b.test/p", "https://c.test/p"]


def test_selection_reports_the_runner_up_gap() -> None:
    subject = query()
    ranked_selection, ranked = select(
        subject,
        [page(url="https://a.test/p"), page(url="https://b.test/p", title="Colgate Total 75ml")],
        CONFIG,
    )
    assert ranked_selection.url == "https://a.test/p"
    assert ranked_selection.runner_up_gap > 0.0
    assert ranked_selection.features is not None
    assert ranked_selection.adjudicated_by_llm is False  # Layer B is P11


def test_every_candidate_rejected_yields_no_url() -> None:
    subject = query(barcode="5014697056627")
    conflicting = [page(url=f"https://{h}.test/p", gtin="9999999999999") for h in ("a", "b")]
    selection, ranked = select(subject, conflicting, CONFIG)
    assert selection.url is None
    assert len(ranked) == 2  # kept, not dropped


# =============================================================================
# `calibrated_prob` is NOT calibrated at P9 (`specs/match.md` §5)
# =============================================================================


def test_calibrated_prob_mirrors_raw_score_without_a_curve() -> None:
    """Without a fitted curve, `calibrated_prob` is NOT a probability and must
    say so by equalling `raw_score` exactly — the plausible-wrong-value shape
    `05` §5 names, made visible rather than hidden."""
    scored = score_candidate(query(), page(), CONFIG)
    assert scored.features.calibrated_prob == scored.features.raw_score


def test_calibrated_prob_follows_the_curve_when_one_is_supplied() -> None:
    """**P10 broke the P9 mirror test on purpose, as that test demanded.**
    With a curve, the text score is mapped through it; hard-rule outcomes
    bypass it because a GTIN accept is 1.0 by identity, not by similarity."""
    from nimo.calibrate import fit_isotonic

    curve = fit_isotonic([0.1, 0.3, 0.5, 0.7, 0.9], [False, False, True, True, True], min_pairs=5)
    scored = score_candidate(query(), page(), CONFIG, curve=curve)
    assert scored.features.calibrated_prob == curve.predict(
        scored.features.raw_score
    )  # no hard rule fired, so raw == weighted here
    gtin_hit = score_candidate(
        query(barcode="5014697056627"), page(gtin="5014697056627"), CONFIG, curve=curve
    )
    assert gtin_hit.features.calibrated_prob == 1.0  # identity, not the curve


def test_no_abstention_at_p9() -> None:
    """`03` §4 stage 4 gates abstention on `calibrated_prob < tau`, and there
    is no calibration yet — abstaining would threshold a number that does not
    mean what the threshold assumes."""
    weak = page(url="https://z.test/p", title="something unrelated entirely")
    selection, _ = select(query(), [weak], CONFIG)
    assert selection.url == "https://z.test/p"  # weak, but selected


# =============================================================================
# Write-back — GTIN accept only (`03` §1a, `05` §4)
# =============================================================================


def test_write_back_fires_on_a_gtin_accept() -> None:
    scored = score_candidate(query(barcode="5014697056627"), page(gtin="5014697056627"), CONFIG)
    assert decide(scored).allowed is True
    assert decide(scored).reason == "gtin_exact"


def test_write_back_refuses_a_merely_high_score() -> None:
    """**The narrowing that keeps the registry clean.** `03` §4 stage 4 offers
    two triggers; the second is `calibrated_prob >= tau_merge`, which does not
    exist yet. `03` §1a: a wrong merge "poisons every future row that blocks
    against it"."""
    scored = score_candidate(query(), page(), CONFIG)  # perfect text match, no GTIN
    assert scored.score > 0.8
    decision = decide(scored)
    assert decision.allowed is False
    assert "uncalibrated" in decision.reason


def test_write_back_refuses_a_rejected_candidate() -> None:
    scored = score_candidate(query(barcode="5014697056627"), page(gtin="9999999999999"), CONFIG)
    assert decide(scored).allowed is False


def test_write_back_refuses_when_there_is_no_candidate() -> None:
    assert decide(None).allowed is False


def test_an_entity_built_from_a_gtin_accept_carries_row_uids_and_variants() -> None:
    """`01` §14: membership is by `row_uid`, never `nan_key`. And P6's fix —
    the entity must carry `variant_terms` or Tier 1 cannot rebuild its own
    identity vector."""
    from nimo.match import audit_for, build_entity

    subject = query(barcode="5014697056627")
    scored = score_candidate(subject, page(gtin="5014697056627"), CONFIG)
    entity = build_entity(subject, scored, module="TOOTH CLEANING", now=TS)

    assert entity.member_row_uids == ["dev:0"]
    assert entity.variant_terms == ["whitening"]
    assert entity.entity_id.startswith("gtin:")
    assert entity.barcode == "5014697056627"

    record = audit_for(entity, run_id="run-1", now=TS)
    assert record.row_uids == ["dev:0"]
    assert record.entity_id == entity.entity_id


def test_merging_into_an_existing_entity_unions_membership() -> None:
    from nimo.match import build_entity

    subject = query(barcode="5014697056627")
    scored = score_candidate(subject, page(gtin="5014697056627"), CONFIG)
    first = build_entity(subject, scored, module="M", now=TS)

    second_row = query(barcode="5014697056627")
    merged = build_entity(
        second_row.model_copy(update={"row_uid": "qa:9"}),
        scored,
        module="M",
        now=TS,
        existing=first,
    )
    assert merged.member_row_uids == ["dev:0", "qa:9"]
    assert merged.entity_id == first.entity_id  # same GTIN -> same stable id
    assert merged.created_at == first.created_at  # creation time preserved


# =============================================================================
# Config (`04` §9)
# =============================================================================


def test_shipped_weights_sum_to_one() -> None:
    total = (
        CONFIG.brand_match
        + CONFIG.variant_overlap
        + CONFIG.format_consistent
        + CONFIG.retailer_domain_match
        + CONFIG.market_signal
    )
    assert total == pytest.approx(1.0)


def test_weights_that_do_not_sum_to_one_are_refused(tmp_path: Path) -> None:
    """So a raw score reads as "how much of the available evidence agreed"
    rather than as an arbitrary scale."""
    import yaml

    from nimo.match.config import CONFIG_PATH

    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    data["weights"]["brand_match"] = 0.9
    path = tmp_path / "match.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(MatchConfigError, match="sum to"):
        load_match_config(path)


def test_hard_rules_use_no_numeric_literals() -> None:
    """`04` §12: "magic number in a scoring function" is a forbidden pattern,
    and a scoring function is where the temptation is strongest."""
    import inspect

    import nimo.match.score as module

    source = inspect.getsource(module.apply_hard_rules) + inspect.getsource(module.weighted_score)
    for literal in ("0.5", "0.6", "0.4", "0.35", "0.3", "0.15"):
        assert literal not in source, f"{literal} is hard-coded; it belongs in config/match.yaml"
