"""P7 query-strategy tests — `specs/retrieval.md` §2, §6, §8.

Includes the coverage measurements against the real 824 rows, pinned so a
change to the normalizer or the retailer table shows up as a strategy-coverage
change rather than silently.
"""

from pathlib import Path

import pytest

from nimo.contracts import CandidateURL, ProductQuery
from nimo.loader import load_rows
from nimo.normalize import normalize_rows
from nimo.retrieval import (
    RetrievalConfigError,
    SearchFn,
    SearchQuery,
    SearchResult,
    build_queries,
    load_retrieval_config,
    merge_candidates,
    retailer_domain,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
RETAILERS = REPO_ROOT / "config" / "retailers.yaml"

# --- Pinned coverage, `specs/retrieval.md` §2 --------------------------------
# The dev/qa asymmetry is the headline: the single most decisive strategy is
# available on 4% of dev and 100% of qa, which is why `03` §4 stage 2 says not
# to tune retrieval on dev alone.
EXPECTED_S1_DEV = 18  # `01` §3: 35 rows survive rounding, only 18 are valid GTIN lengths
EXPECTED_S1_QA = 412
EXPECTED_S4_DEV = 223
EXPECTED_S4_QA = 256


@pytest.fixture(scope="module")
def dev() -> list[ProductQuery]:
    return normalize_rows(load_rows(WORKBOOK, "dev", RETAILERS))


@pytest.fixture(scope="module")
def qa() -> list[ProductQuery]:
    return normalize_rows(load_rows(WORKBOOK, "qa", RETAILERS))


def strategies(query: ProductQuery) -> set[str]:
    return {item.strategy for item in build_queries(query, RETAILERS)}


# --- coverage ----------------------------------------------------------------


def test_barcode_strategies_fire_only_on_valid_gtins(dev: list[ProductQuery]) -> None:
    """**S1/S2 are gated on `barcode_valid`, not merely "not corrupt".** 35
    `dev` rows survive the rounding defect but only 18 are valid GTIN lengths;
    the other 17 are 6-7 digits (`266611`) and are not GTINs at all. Searching
    a non-GTIN as though it were one returns unrelated results with no error
    anywhere — a latent failure (`05` §5), not a bad query."""
    with_s1 = [query for query in dev if "S1" in strategies(query)]
    assert len(with_s1) == EXPECTED_S1_DEV
    for query in with_s1:
        assert query.barcode is not None
        assert len(query.barcode) in {8, 12, 13, 14}


def test_qa_has_a_barcode_strategy_for_every_row(qa: list[ProductQuery]) -> None:
    """The other half of the asymmetry — 100% of qa, versus 4% of dev."""
    assert sum(1 for query in qa if "S1" in strategies(query)) == EXPECTED_S1_QA


def test_site_restricted_coverage_matches_the_mapped_retailers(
    dev: list[ProductQuery], qa: list[ProductQuery]
) -> None:
    """28 of 50 retailers carry a domain; the rest are panels and aggregators
    with no single product site, and `03` §4 stage 2 says they skip S4."""
    assert sum(1 for query in dev if "S4" in strategies(query)) == EXPECTED_S4_DEV
    assert sum(1 for query in qa if "S4" in strategies(query)) == EXPECTED_S4_QA


def test_every_row_gets_at_least_the_fallback(dev: list[ProductQuery]) -> None:
    """`03` §4 stage 2 lists S5 as the fallback; a row with no query at all
    would silently drop out of retrieval."""
    for query in dev:
        assert build_queries(query, RETAILERS), f"{query.row_uid} produced no query"


def test_queries_come_back_in_strategy_order(dev: list[ProductQuery]) -> None:
    for query in dev[:50]:
        names = [item.strategy for item in build_queries(query, RETAILERS)]
        assert names == sorted(names)


# --- shapes ------------------------------------------------------------------


def test_site_restricted_query_is_prefixed_with_the_domain(dev: list[ProductQuery]) -> None:
    for query in dev:
        built = {item.strategy: item.text for item in build_queries(query, RETAILERS)}
        if "S4" in built:
            domain = retailer_domain(query.retailer_raw, RETAILERS)
            assert domain is not None
            assert built["S4"].startswith(f"site:{domain} ")
            return
    pytest.fail("no dev row produced an S4 query")


def test_barcode_query_is_quoted_for_exactness(dev: list[ProductQuery]) -> None:
    for query in dev:
        built = {item.strategy: item.text for item in build_queries(query, RETAILERS)}
        if "S1" in built:
            assert built["S1"] == f'"{query.barcode}"'
            assert query.brand in built["S2"]
            return
    pytest.fail("no dev row produced an S1 query")


def test_unmapped_retailer_has_no_domain() -> None:
    assert retailer_domain("BRANDBANK (UK)", RETAILERS) is None
    assert retailer_domain("P00R4 (GB) BOOTS", RETAILERS) == "boots.com"
    assert retailer_domain("NOT A REAL RETAILER", RETAILERS) is None


# --- merge, cap and provenance ----------------------------------------------


def fake_search(results: dict[str, list[SearchResult]]) -> SearchFn:
    def search(query: SearchQuery, limit: int) -> list[SearchResult]:
        return results.get(query.strategy, [])[:limit]

    return search


def test_first_strategy_owns_a_shared_url() -> None:
    """A URL found by both S2 and S5 is recorded as S2's — the stronger signal,
    and the one worth knowing about when the candidate turns out right."""
    shared = SearchResult(url="https://boots.com/p", engine="google", rank=1, title="p")
    merged = merge_candidates(
        [SearchQuery("S2", "a"), SearchQuery("S5", "b")],
        fake_search({"S2": [shared], "S5": [shared]}),
        load_retrieval_config(),
    )
    assert [candidate.source_query for candidate in merged] == ["S2"]


def test_ordering_is_strategy_then_rank() -> None:
    """A barcode+brand hit outranks a verbatim-text hit regardless of what the
    engine thought its rank was."""
    merged = merge_candidates(
        [SearchQuery("S2", "a"), SearchQuery("S5", "b")],
        fake_search(
            {
                "S5": [SearchResult("https://a.com/1", "google", 1, None)],
                "S2": [SearchResult("https://b.com/1", "google", 9, None)],
            }
        ),
        load_retrieval_config(),
    )
    assert [candidate.url for candidate in merged] == ["https://b.com/1", "https://a.com/1"]


def test_candidates_are_capped() -> None:
    config = load_retrieval_config()
    many = [
        SearchResult(f"https://shop{index}.com/p", "google", index, None) for index in range(1, 60)
    ]
    merged = merge_candidates(
        [SearchQuery("S5", "x")],
        fake_search({"S5": many}),
        config,
    )
    assert len(merged) <= config.per_strategy_limit <= config.max_candidates


def test_unsafe_candidates_never_enter_the_pipeline() -> None:
    merged = merge_candidates(
        [SearchQuery("S5", "x")],
        fake_search(
            {
                "S5": [
                    SearchResult("http://127.0.0.1/admin", "google", 1, None),
                    SearchResult("file:///etc/passwd", "google", 2, None),
                    SearchResult("https://boots.com/p", "google", 3, None),
                ]
            }
        ),
        load_retrieval_config(),
    )
    assert [candidate.url for candidate in merged] == ["https://boots.com/p"]


def test_urls_differing_only_by_tracking_dedup_to_one_candidate() -> None:
    merged = merge_candidates(
        [SearchQuery("S5", "x")],
        fake_search(
            {
                "S5": [
                    SearchResult("https://boots.com/p?utm_source=a", "google", 1, None),
                    SearchResult("https://www.boots.com/p/", "bing", 2, None),
                ]
            }
        ),
        load_retrieval_config(),
    )
    assert len(merged) == 1


def test_merged_candidates_are_contract_instances() -> None:
    merged = merge_candidates(
        [SearchQuery("S3", "x")],
        fake_search({"S3": [SearchResult("https://boots.com/p", "google", 1, "Title")]}),
        load_retrieval_config(),
    )
    assert isinstance(merged[0], CandidateURL)
    assert merged[0].title_snippet == "Title"


# --- config ------------------------------------------------------------------


def test_shipped_config_loads_and_is_internally_consistent() -> None:
    config = load_retrieval_config()
    assert config.per_strategy_limit <= config.max_candidates
    # S1 last, measured (`config/retrieval.yaml`): bare-barcode queries were
    # empty on 5 of 10 qa rows and filled the fetch set with digit-matching
    # junk on the one row where they returned 8; S2 dominated them.
    assert config.strategy_order == ("S2", "S3", "S4", "S5", "S1")
    assert config.connect_timeout_s > 0 and config.read_timeout_s > 0


def test_a_strategy_limit_above_the_cap_is_refused(tmp_path: Path) -> None:
    """One strategy filling the whole budget would starve the others — S5 in
    particular would crowd out a barcode-exact S1 hit."""
    # Built from the shipped config with one field overridden, rather than
    # retyped: a hand-written YAML fixture silently rots into "missing key"
    # every time a setting is added, which is a failure about the fixture
    # rather than about the rule under test.
    import yaml

    from nimo.retrieval.config import CONFIG_PATH

    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    data["max_candidates"] = 5
    data["per_strategy_limit"] = 50

    path = tmp_path / "retrieval.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(RetrievalConfigError, match="exceeds max_candidates"):
        load_retrieval_config(path)
