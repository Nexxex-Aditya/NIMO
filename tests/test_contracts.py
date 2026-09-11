"""P1 contract tests — specs/contracts.md, Definition of Done.

Every model round-trips through JSON individually (not one test that only
proves the last one), every model is frozen, every Literal rejects an
out-of-vocabulary value, and no model carries a dict keyed by anything but
`str`.
"""

import pathlib
import re
import typing
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

import nimo.contracts as contracts_module
from nimo.contracts import (
    AdjudicationVerdict,
    BlockKey,
    CandidateEvidence,
    CandidateURL,
    CanonicalEntity,
    CharacteristicGuideline,
    CharacteristicRule,
    CharacteristicValues,
    DescTokens,
    GoldPair,
    GoldUrl,
    MatchFeatures,
    ModulePrediction,
    OutputRow,
    ProductQuery,
    RawRow,
    RegistryLookupResult,
    RowFailure,
    RunSummary,
    Selection,
)

FIXED_TS = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)

DESC_TOKENS = DescTokens(
    variant_terms=["whitening", "sensitive"],
    size_value=100.0,
    size_unit="ml",
    size_ml_equiv=100.0,
    size_g_equiv=None,
    count=2,
    format_hints=["pump"],
    stripped_junk=["e0028", "unit 00000012"],
)

RAW_ROW = RawRow(
    row_uid="dev:0",
    nan_key=12722399,
    item_code=5405264,
    barcode="5014697056627",
    barcode_raw="5014697056627",
    barcode_corrupt=False,
    brand_raw="AQUAFRESH (HALEON)",
    brand="AQUAFRESH",
    brand_owner="HALEON",
    brand_encoding_suspect=False,
    retailer_raw="P00R4 (GB) BOOTS",
    retailer="BOOTS",
    countries=["BE", "GB", "NL"],
    desc_raw="aquafresh whitening pump 100ml",
    desc_encoding_suspect=False,
)

CHARACTERISTIC_RULE = CharacteristicRule(
    module="TOOTHBRUSHES - MANUAL - REGULAR",
    characteristic="GLOBAL_BRISTLE_STRENGTH_CLAIM",
    open_close="Close",
    binary=False,
    allowed_values=["HARD", "MEDIUM", "NO CLAIM", "SOFT"],
)

CHARACTERISTIC_GUIDELINE = CharacteristicGuideline(
    module="TOOTHBRUSHES - MANUAL - REGULAR",
    characteristic="GLOBAL_BRISTLE_STRENGTH_CLAIM",
    guideline_text="Relative strength of the bristles. Default to NO CLAIM when absent.",
)

PRODUCT_QUERY = ProductQuery(
    **RAW_ROW.model_dump(),
    desc_clean="aquafresh whitening pump 100ml",
    tokens=DESC_TOKENS,
)

CANONICAL_ENTITY = CanonicalEntity(
    entity_id="sha256:8f1c2d",
    barcode="5014697056627",
    brand="AQUAFRESH",
    size_ml_equiv=100.0,
    size_g_equiv=None,
    count=1,
    variant_terms=["whitening", "pump"],
    module="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
    resolved_url="https://www.boots.com/aquafresh-whitening-100ml",
    page_title="Aquafresh Whitening Toothpaste 100ml | Boots",
    # non-empty on purpose: an empty dict round-trips trivially and proves
    # nothing (specs/contracts.md, JSON round-trip gate)
    characteristics={
        "GLOBAL_IF_WITH_FLUORIDE": "WITH FLUORIDE",
        "GLOBAL_ORAL_CARE_FUNCTION": "ANTI BACTERIAL & FRESHENING & WHITENING",
    },
    confidence=0.93,
    member_row_uids=["dev:0", "qa:117"],
    resolution_tier="tier2_retrieval",
    created_at=FIXED_TS,
    updated_at=FIXED_TS,
)

MODULE_PREDICTION = ModulePrediction(
    row_uid="dev:0",
    module="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
    confidence=0.412,
    runner_up="TOOTH STAIN REMOVERS - FOAM/GEL/LIQUID/PASTE - MULTI DOSE",
    runner_up_gap=0.118,
    nearest_example_row_uid="dev:12",
    nearest_example_similarity=0.821,
    source="text_baseline",
)

ROW_FAILURE = RowFailure(
    row_uid="dev:217",
    stage="fetch",
    error_type="TimeoutError",
    message="read timeout after 30s on boots.com",
    occurred_at=FIXED_TS,
)

RUN_SUMMARY = RunSummary(
    run_id="run-2026-09-10-01",
    rows_total=412,
    rows_succeeded=400,
    rows_failed=12,
    failures_by_stage={"fetch": 9, "match": 3},
    tier_counts={"tier0_exact": 4, "tier1_ann": 130, "tier2_retrieval": 250, "tier3_llm": 16},
    llm_calls=266,
    llm_tokens=184_320,
    cache_hits=980,
    cache_misses=310,
    wall_time_s=1425.5,
    config_hash="sha256:c0ffee",
)

GOLD_URL = GoldUrl(
    row_uid="dev:0",
    nan_key=3546967,
    sheet="dev",
    url="https://www.boots.com/aquafresh-whitening-100ml",
    page_title="Aquafresh Whitening Toothpaste 100ml | Boots",
    label="correct",
    evidence="brand AQUAFRESH, 100ml, whitening variant and pump format all shown on page",
    verified_on="2026-09-10",
)

GOLD_PAIR = GoldPair(
    left_row_uid="dev:140",
    right_row_uid="dev:386",
    label="same",
    evidence="Colgate Total Plus Whitening pump 100ml on both sides.",
    verified_on="2026-09-10",
)

BLOCK_KEY = BlockKey(key="5014697056627", method="exact_gtin")

REGISTRY_LOOKUP_RESULT = RegistryLookupResult(
    hit=True,
    tier="tier1_ann",
    entity=CANONICAL_ENTITY,
    similarity=0.91,
)

CANDIDATE_URL = CandidateURL(
    url="https://www.boots.com/aquafresh-whitening-100ml",
    source_query="aquafresh whitening pump 100ml",
    engine="google",
    rank=1,
    title_snippet="Aquafresh Whitening Toothpaste 100ml",
)

CANDIDATE_EVIDENCE = CandidateEvidence(
    url="https://www.boots.com/aquafresh-whitening-100ml",
    fetch_status="ok",
    fetched_at=FIXED_TS,
    content_hash="sha256:deadbeef",
    title="Aquafresh Whitening Toothpaste 100ml | Boots",
    # deliberately nested: JSON-LD's real shape, and the reason this field is
    # dict[str, Any] rather than dict[str, object] — see contracts.py
    jsonld_product={
        "@type": "Product",
        "gtin13": "5014697056627",
        "brand": {"@type": "Brand", "name": "AQUAFRESH"},
        "offers": [{"@type": "Offer", "price": 2.5}],
        "weight": None,
    },
    gtin="5014697056627",
    og={"og:title": "Aquafresh Whitening 100ml", "og:image": "https://x/a.jpg"},
    breadcrumbs=["Home", "Toothpaste"],
    body_text="Aquafresh whitening toothpaste, 100ml pump.",
    image_urls=["https://x/a.jpg"],
    price="2.50",
    parse_warnings=["no microdata"],
)

MATCH_FEATURES = MatchFeatures(
    barcode_exact=True,
    brand_match=1.0,
    size_match="exact",
    count_match="exact",
    variant_overlap=0.8,
    format_consistent=True,
    retailer_domain_match=True,
    market_signal=0.7,
    negative_flags=["refill"],
    raw_score=4.2,
    calibrated_prob=0.93,
)

CHARACTERISTIC_VALUES = CharacteristicValues(
    row_uid="dev:0",
    module="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
    values={
        "GLOBAL_INTERSPACE_CLAIM": None,
        "GLOBAL_CONSUMER_LIFESTAGE_CLAIM": "ADULT",
        "GLOBAL_PACKAGING": "TUBE",
        "GLOBAL_IF_MEDICATED": None,
        "GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS": None,
        "GLOBAL_IF_WITH_SENSITIVE_CLAIM": "WITHOUT SENSITIVE CLAIM",
        "GLOBAL_ORAL_CARE_FUNCTION": "ANTI BACTERIAL & WHITENING",
        "GLOBAL_IF_WITH_FLUORIDE": "WITH FLUORIDE",
        "GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP": "MINT",
        "GLOBAL_METHOD_OF_APPLICATION_DISPENSE": "PUMP",
        "GLOBAL_PACKAGING_MATERIAL": "PLASTIC",
        "GLOBAL_DESCRIPTIVE_SIZE_OF_TOOTHBRUSH_HEAD_CLAIM": None,
        "GLOBAL_BRISTLE_STRENGTH_CLAIM": None,
    },
    applicable=[
        "GLOBAL_CONSUMER_LIFESTAGE_CLAIM",
        "GLOBAL_PACKAGING",
        "GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS",
        "GLOBAL_IF_WITH_SENSITIVE_CLAIM",
        "GLOBAL_ORAL_CARE_FUNCTION",
        "GLOBAL_IF_WITH_FLUORIDE",
        "GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP",
        "GLOBAL_METHOD_OF_APPLICATION_DISPENSE",
        "GLOBAL_PACKAGING_MATERIAL",
    ],
    rejected={"GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS": "MOSTLY NATURAL"},
    source="llm",
    prompt_hash="9f2c1d3e4b5a69788796a5b4c3d2e1f0",
    model="hack-fest-gpt-5.6-luna",
)

ADJUDICATION_VERDICT = AdjudicationVerdict(
    choice=2,
    decisive_fields=["gtin", "size"],
    rationale="Candidate 2 states EAN 5014697056627 and 100ml; candidate 1 is the 75ml tube.",
    prompt_hash="9f2c1d3e4b5a69788796a5b4c3d2e1f0",
    model="hack-fest-gpt-5.6-luna",
)

SELECTION = Selection(
    url="https://www.boots.com/aquafresh-whitening-100ml",
    page_title="Aquafresh Whitening Toothpaste 100ml | Boots",
    confidence=0.93,
    runner_up_gap=0.41,
    features=MATCH_FEATURES,
    adjudicated_by_llm=True,
    resolution_tier="tier3_llm",
    adjudication=ADJUDICATION_VERDICT,
)

OUTPUT_ROW = OutputRow(
    ITEM_CODE=5405264,
    NAN_KEY=12722399,
    EXTERNAL_CODE="5014697056627",
    COUNTRY="BE,GB,NL",
    RETAILER_DESC="aquafresh whitening pump 100ml",
    RETAILER="P00R4 (GB) BOOTS",
    BRAND="AQUAFRESH (HALEON)",
    PRODUCT_URL="https://www.boots.com/aquafresh-whitening-100ml",
    REASONING="EAN 5014697056627 confirmed on page; 100ml pump format matches.",
    MODULE="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
    GLOBAL_INTERSPACE_CLAIM=None,
    GLOBAL_CONSUMER_LIFESTAGE_CLAIM="NO CLAIM",
    GLOBAL_PACKAGING="BOTTLE",
    GLOBAL_IF_MEDICATED=None,
    GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS="NOT STATED",
    GLOBAL_IF_WITH_SENSITIVE_CLAIM="WITHOUT SENSITIVE CLAIM",
    GLOBAL_ORAL_CARE_FUNCTION="ANTI BACTERIAL & FRESHENING & WHITENING",
    GLOBAL_IF_WITH_FLUORIDE="WITH FLUORIDE",
    GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP="MINT",
    GLOBAL_METHOD_OF_APPLICATION_DISPENSE="PUMP",
    GLOBAL_PACKAGING_MATERIAL="PLASTIC",
    GLOBAL_DESCRIPTIVE_SIZE_OF_TOOTHBRUSH_HEAD_CLAIM=None,
    GLOBAL_BRISTLE_STRENGTH_CLAIM=None,
)

# Dependency order per specs/contracts.md "Class list, in dependency order".
ALL_MODELS: list[tuple[str, BaseModel]] = [
    ("DescTokens", DESC_TOKENS),
    ("RawRow", RAW_ROW),
    ("CharacteristicRule", CHARACTERISTIC_RULE),
    ("CharacteristicGuideline", CHARACTERISTIC_GUIDELINE),
    ("ProductQuery", PRODUCT_QUERY),
    ("CanonicalEntity", CANONICAL_ENTITY),
    ("ModulePrediction", MODULE_PREDICTION),
    ("CharacteristicValues", CHARACTERISTIC_VALUES),
    ("RowFailure", ROW_FAILURE),
    ("RunSummary", RUN_SUMMARY),
    ("GoldUrl", GOLD_URL),
    ("GoldPair", GOLD_PAIR),
    ("BlockKey", BLOCK_KEY),
    ("RegistryLookupResult", REGISTRY_LOOKUP_RESULT),
    ("CandidateURL", CANDIDATE_URL),
    ("CandidateEvidence", CANDIDATE_EVIDENCE),
    ("MatchFeatures", MATCH_FEATURES),
    ("AdjudicationVerdict", ADJUDICATION_VERDICT),
    ("Selection", SELECTION),
    ("OutputRow", OUTPUT_ROW),
]

# `01` §2 / `03` §3 — the literal qa header, name and order.
QA_HEADER: list[str] = [
    "ITEM_CODE",
    "NAN_KEY",
    "EXTERNAL_CODE",
    "COUNTRY",
    "RETAILER_DESC",
    "RETAILER",
    "BRAND",
    "PRODUCT_URL",
    "REASONING",
    "MODULE",
    "GLOBAL_INTERSPACE_CLAIM",
    "GLOBAL_CONSUMER_LIFESTAGE_CLAIM",
    "GLOBAL_PACKAGING",
    "GLOBAL_IF_MEDICATED",
    "GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS",
    "GLOBAL_IF_WITH_SENSITIVE_CLAIM",
    "GLOBAL_ORAL_CARE_FUNCTION",
    "GLOBAL_IF_WITH_FLUORIDE",
    "GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP",
    "GLOBAL_METHOD_OF_APPLICATION_DISPENSE",
    "GLOBAL_PACKAGING_MATERIAL",
    "GLOBAL_DESCRIPTIVE_SIZE_OF_TOOTHBRUSH_HEAD_CLAIM",
    "GLOBAL_BRISTLE_STRENGTH_CLAIM",
]


def test_every_contract_model_is_covered() -> None:
    """Guards the parametrized list itself against a silently-dropped model."""
    assert len(ALL_MODELS) == 20


@pytest.mark.parametrize("name,instance", ALL_MODELS, ids=[n for n, _ in ALL_MODELS])
def test_json_round_trip(name: str, instance: BaseModel) -> None:
    """specs/contracts.md: the P1 gate, one test per model, not one for all."""
    restored = type(instance).model_validate_json(instance.model_dump_json())
    assert restored == instance


@pytest.mark.parametrize("name,instance", ALL_MODELS, ids=[n for n, _ in ALL_MODELS])
def test_every_model_is_frozen(name: str, instance: BaseModel) -> None:
    assert type(instance).model_config.get("frozen") is True
    with pytest.raises(ValidationError):
        setattr(instance, next(iter(type(instance).model_fields)), "mutated")


@pytest.mark.parametrize("name,instance", ALL_MODELS, ids=[n for n, _ in ALL_MODELS])
def test_no_dict_keyed_by_non_str(name: str, instance: BaseModel) -> None:
    """`03` §3: a tuple-keyed dict has no JSON object-key form.

    Reflective rather than by inspection, so a future model that reintroduces
    one fails here instead of at a serialization boundary much later.
    """
    for field_name, field in type(instance).model_fields.items():
        for annotation in _walk_annotations(field.annotation):
            if typing.get_origin(annotation) is dict:
                key_type = typing.get_args(annotation)[0]
                assert key_type is str, f"{name}.{field_name} dict key is {key_type}, not str"


def _walk_annotations(annotation: object) -> list[object]:
    """Flatten a nested annotation into every generic it contains."""
    found = [annotation]
    for arg in typing.get_args(annotation):
        found.extend(_walk_annotations(arg))
    return found


def test_product_query_inherits_and_round_trips_in_one_call() -> None:
    """specs/contracts.md: tested explicitly, not implied by RawRow passing."""
    restored = ProductQuery.model_validate_json(PRODUCT_QUERY.model_dump_json())
    assert restored == PRODUCT_QUERY
    # inherited RawRow fields survive
    assert restored.nan_key == RAW_ROW.nan_key
    assert restored.brand_owner == "HALEON"
    assert restored.desc_encoding_suspect is False
    # own additions survive, including the nested model
    assert restored.desc_clean == "aquafresh whitening pump 100ml"
    assert restored.tokens == DESC_TOKENS
    assert restored.tokens.size_ml_equiv == 100.0
    assert isinstance(restored, RawRow)


def test_canonical_entity_characteristics_survive_round_trip() -> None:
    restored = CanonicalEntity.model_validate_json(CANONICAL_ENTITY.model_dump_json())
    assert restored.characteristics == CANONICAL_ENTITY.characteristics
    assert len(restored.characteristics) == 2


def test_nested_jsonld_survives_round_trip_with_types_intact() -> None:
    """The reason jsonld_product is dict[str, Any] and not dict[str, object]."""
    restored = CandidateEvidence.model_validate_json(CANDIDATE_EVIDENCE.model_dump_json())
    assert restored == CANDIDATE_EVIDENCE
    jsonld = restored.jsonld_product
    assert jsonld is not None
    assert jsonld["brand"]["name"] == "AQUAFRESH"
    assert jsonld["offers"][0]["price"] == 2.5
    assert jsonld["weight"] is None


@pytest.mark.parametrize(
    "model,field,bad_value",
    [
        (CharacteristicRule, "open_close", "Closed"),
        (CandidateEvidence, "fetch_status", "OK"),
        (MatchFeatures, "size_match", "EXACT"),
        (MatchFeatures, "count_match", "partial"),
        (BlockKey, "method", "fuzzy"),
        (RegistryLookupResult, "tier", "tier2_retrieval"),
        (CanonicalEntity, "resolution_tier", "tier4"),
        (Selection, "resolution_tier", "miss"),
        (GoldUrl, "label", "probably_right"),
        (GoldUrl, "sheet", "qa"),
        (RowFailure, "stage", "retrival"),
    ],
)
def test_literals_reject_out_of_vocabulary_values(
    model: type[BaseModel], field: str, bad_value: str
) -> None:
    """`03` §3 Literals are transcribed verbatim and must fail at construction.

    Note `RegistryLookupResult.tier` and `Selection.resolution_tier` are
    deliberately different vocabularies — a value valid in one is invalid in
    the other, and widening either to plain `str` would hide that.
    """
    base = {n: i for n, i in ALL_MODELS}[model.__name__]
    payload = dict(base.model_dump())
    payload[field] = bad_value
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_output_row_field_order_is_the_qa_header() -> None:
    """`03` §3 assembly note: a silently reordered submission scores zero.

    Static guard on the contract's own declaration order. The live-header
    equality assertion against the real workbook is P2/P14's job.
    """
    assert list(OutputRow.model_fields) == QA_HEADER
    assert len(QA_HEADER) == 23


def test_output_row_none_is_the_only_not_applicable_representation() -> None:
    """`03` §3 construction rule: None → empty cell, never a literal string."""
    dumped = OUTPUT_ROW.model_dump()
    assert dumped["GLOBAL_INTERSPACE_CLAIM"] is None
    assert dumped["GLOBAL_BRISTLE_STRENGTH_CLAIM"] is None
    for value in dumped.values():
        assert value not in ("", "N/A", "NOT APPLICABLE")


def test_serialization_is_deterministic() -> None:
    """`04` §5: twice-run byte-identical."""
    for _, instance in ALL_MODELS:
        assert instance.model_dump_json() == instance.model_dump_json()


def _parse_architecture_section_3() -> dict[str, list[str]]:
    """Field names per class, straight out of `03` §3's python block."""
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    text = (repo_root / "docs" / "03-architecture.md").read_text(encoding="utf-8")
    block = text.split("```python", 1)[1].split("```", 1)[0]
    spec: dict[str, list[str]] = {}
    current: str | None = None
    for line in block.splitlines():
        class_match = re.match(r"^class (\w+)", line)
        if class_match:
            current = class_match.group(1)
            spec[current] = []
            continue
        if current and re.match(r"^    [a-zA-Z_]\w*\s*:", line):
            spec[current].append(line.strip().split(":")[0].strip())
    return spec


def test_contracts_match_architecture_section_3_field_for_field() -> None:
    """Drift guard between the design authority and the code implementing it.

    `05` §5 names silent schema drift as a latent-failure mode — one that
    throws nothing and produces plausible wrong output. The same class applies
    at the docs/code boundary: `03` §3 is the authority, `contracts.py` is
    supposed to be its exact transcription, and nothing otherwise notices when
    they diverge. If this test fails after an intentional `03` §3 edit, update
    `contracts.py` to match — do not relax the test.
    """
    spec = _parse_architecture_section_3()
    assert len(spec) == 20, f"expected 20 classes in `03` §3, parsed {len(spec)}"
    for class_name, fields in spec.items():
        model = getattr(contracts_module, class_name, None)
        assert model is not None, f"`03` §3 declares {class_name}; contracts.py has no such model"
        # `03` §3 lists only ProductQuery's own additions; inheritance supplies the rest.
        expected = (spec["RawRow"] + fields) if class_name == "ProductQuery" else fields
        assert list(model.model_fields) == expected, (
            f"{class_name} field names/order differ from `03` §3"
        )


def test_contracts_module_declares_no_type_ignore() -> None:
    """specs/contracts.md DoD: zero `# type: ignore` in this file."""
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    source = (repo_root / "src" / "nimo" / "contracts.py").read_text(encoding="utf-8")
    assert "type: ignore" not in source


def test_datetimes_are_timezone_aware() -> None:
    """specs/contracts.md: aware datetimes, supplied by the caller."""
    assert CANONICAL_ENTITY.created_at.tzinfo is not None
    assert CANDIDATE_EVIDENCE.fetched_at.tzinfo is not None
    restored = CandidateEvidence.model_validate_json(CANDIDATE_EVIDENCE.model_dump_json())
    assert restored.fetched_at == FIXED_TS
    assert restored.fetched_at.tzinfo is not None
