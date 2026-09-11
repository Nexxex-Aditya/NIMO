"""Pydantic contracts for the NIMO pipeline.

Populated in P1 against docs/03-architecture.md §3. Do not add models here
outside that phase without a decision-log entry.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class DescTokens(BaseModel):  # parsed from desc_clean
    model_config = ConfigDict(frozen=True)

    variant_terms: list[str]  # "whitening", "sensitive", "original"
    size_value: float | None  # 100.0
    size_unit: str | None  # "ml" — normalized
    size_ml_equiv: float | None  # volume normalized to ml; None for mass-sized products
    # mass normalized to g; None for volume-sized products. Exactly one of the
    # two is set when size_value is set — never both, never coerced across
    # dimensions (35 rows are mass-only; g->ml at density 1 would be a
    # plausible wrong number, `03` §3's size note).
    size_g_equiv: float | None
    count: int | None  # multipack count; None == 1
    format_hints: list[str]  # "pump", "spray", "tablets"
    stripped_junk: list[str]  # audit trail of what was removed


class RawRow(BaseModel):  # loader (P2) output — one per dev/qa row, pre-normalization
    model_config = ConfigDict(frozen=True)

    # "dev:0", "qa:117" — sheet + 0-based source row. THE row identity.
    # NAN_KEY/ITEM_CODE are corrupted and collide across different products
    # (`01` §14); never key anything on them.
    row_uid: str
    nan_key: int  # NIQ key, verbatim — traceability and submission only, NOT unique
    item_code: int  # NIQ item id, verbatim — traceability and submission only, NOT unique
    barcode: str | None  # normalized string, None if absent OR corrupt (see `01` §3)
    # original string before nulling on corruption — audit/trace only,
    # NEVER used for matching or registry blocking
    barcode_raw: str | None
    barcode_corrupt: bool  # True for the rounded dev values
    # "AQUAFRESH (HALEON)" — verbatim from BRAND column, encoding-repaired
    # (see brand_encoding_suspect) before the parenthetical split below runs
    brand_raw: str
    brand: str  # "AQUAFRESH" — mechanical parenthetical split, not NLP
    brand_owner: str | None  # "HALEON"
    # True if ftfy changed brand_raw from the source cell — `01` §13, `01` §10 #9
    brand_encoding_suspect: bool
    retailer_raw: str  # "P00R4 (GB) BOOTS" — verbatim from RETAILER column
    retailer: str  # "BOOTS" — looked up from config/retailers.yaml, see specs/loader.md
    countries: list[str]  # ["GB"] or ["BE","GB","NL"] — split on COUNTRY
    # RETAILER_DESC, whitespace collapsed/trimmed and encoding-repaired (see
    # desc_encoding_suspect) — no other processing; junk-token stripping is
    # P3's job, not this field's
    desc_raw: str
    # True if ftfy changed desc_raw from the source cell — `01` §13, `01` §10 #9
    desc_encoding_suspect: bool


class CharacteristicRule(BaseModel):  # loader (P2) output — one row of char_value_list
    model_config = ConfigDict(frozen=True)

    module: str
    characteristic: str  # underscored form, e.g. "GLOBAL_BRISTLE_STRENGTH_CLAIM"
    open_close: Literal["Close", "Open-ended"]
    binary: bool
    allowed_values: list[str]  # parsed from possible_values via ast.literal_eval


class CharacteristicGuideline(BaseModel):  # loader (P2) output — one row of char_guidelines
    model_config = ConfigDict(frozen=True)

    module: str
    characteristic: str  # normalized to the same underscored form as above
    guideline_text: str


class ProductQuery(RawRow):  # normalizer (P3) output — RawRow + parsed description
    desc_clean: str  # junk tokens stripped
    tokens: DescTokens


class ModulePrediction(BaseModel):  # P5 — stage [5] output, `specs/classify.md`
    model_config = ConfigDict(frozen=True)

    row_uid: str  # `01` §14 — never nan_key
    # one of char_value_list's 59. Always set, never None: stage [5] is the
    # fallback path (`03` §4 stage 5), and a fallback that abstains isn't one.
    module: str
    # winning cosine, 0..1. NOT a calibrated probability — calibration (P10)
    # is about URL selection, not this.
    confidence: float
    runner_up: str | None  # None only when the model knows exactly one module
    runner_up_gap: float  # confidence - runner-up score; 0.0 when runner_up is None
    # closest labelled training row — the transparency surface. Char 4-gram
    # weights explain nothing to a human; a cited neighbour does (`03` §3).
    nearest_example_row_uid: str | None
    nearest_example_similarity: float  # its cosine; 0.0 when there is no training row
    source: Literal["text_baseline", "page_evidence", "registry"]


class CanonicalEntity(BaseModel):  # §1a — one persisted, resolved product
    model_config = ConfigDict(frozen=True)

    # stable hash of (barcode or fingerprint) — never a random uuid;
    # must be reproducible
    entity_id: str
    barcode: str | None  # authoritative GTIN once confirmed
    brand: str
    size_ml_equiv: float | None  # volume in ml — mirrors DescTokens
    # mass in g — mirrors DescTokens; both feed the fingerprint block key
    size_g_equiv: float | None
    count: int
    # mirrors DescTokens — what Tier 1 actually compares. brand/size/count ARE
    # the block key and are equal across a block by construction, so without
    # this a persisted entity cannot rebuild its own identity vector and Tier 1
    # silently never fires (`03` §3, `02-decision-log.md`).
    variant_terms: list[str]
    module: str | None
    resolved_url: str | None
    page_title: str | None  # see [PROVISIONAL — Q2]
    characteristics: dict[str, str]  # applicable-only, post-gate values
    confidence: float
    # every row folded into this entity, by row_uid — NOT nan_key, which
    # collides across different products (`01` §14)
    member_row_uids: list[str]
    resolution_tier: Literal["tier0_exact", "tier1_ann", "tier2_retrieval", "tier3_llm"]
    created_at: datetime
    updated_at: datetime


class RowFailure(BaseModel):  # P6a — the batch runner's typed failure record
    model_config = ConfigDict(frozen=True)

    row_uid: str  # which row failed (`01` §14 — never nan_key)
    stage: Literal[
        "normalize",
        "registry",
        "retrieve",
        "fetch",
        "match",
        "classify",
        "characteristics",
        "reason",
        "assemble",
    ]
    error_type: str  # exception class name, e.g. "DatasetSchemaError"
    message: str  # str(exception), truncated by the runner
    occurred_at: datetime  # metadata only, never read by logic (`04` §5)


class RunSummary(BaseModel):  # P6a — what every run prints (`04` §10)
    model_config = ConfigDict(frozen=True)

    run_id: str  # stable per invocation; appears in every trace record
    rows_total: int
    rows_succeeded: int
    rows_failed: int
    failures_by_stage: dict[str, int]  # str keys — JSON round-trip rule
    tier_counts: dict[str, int]  # resolution_tier -> count; the §1a efficiency evidence
    llm_calls: int
    llm_tokens: int
    cache_hits: int
    cache_misses: int
    wall_time_s: float
    config_hash: str  # config+prompt fingerprint — `05` §5 version-skew guardrail


class GoldUrl(BaseModel):  # P4 — one hand-verified URL label, `03` §6 L3/L4
    model_config = ConfigDict(frozen=True)

    # "dev:N" — the row identity (`01` §14); nan_key would not be unique
    row_uid: str
    nan_key: int  # carried for traceability only
    sheet: Literal["dev"]  # dev only — qa has no MODULE to stratify on
    url: str | None  # set iff label == "correct"
    page_title: str | None  # see [PROVISIONAL — Q2]
    label: Literal["correct", "no_page_found", "ambiguous"]
    # what was actually checked on the page — never "looks right"
    evidence: str
    verified_on: str  # ISO date; audit trail for a hand-produced artifact


class GoldPair(BaseModel):  # P6 — one hand-adjudicated same/different pair, `03` §1a
    model_config = ConfigDict(frozen=True)

    # both rows are always `dev`; ordering is (lower, higher) by source index
    left_row_uid: str
    right_row_uid: str
    # "ambiguous" is a real answer, not a placeholder: two retailer descriptions
    # can be genuinely undecidable without a product page (`specs/registry.md`).
    label: Literal["same", "different", "ambiguous"]
    evidence: str  # what was actually compared — never "looks similar"
    verified_on: str  # ISO date; audit trail for a hand-produced artifact


class BlockKey(BaseModel):  # §1a — blocking, computed at stage [1]
    model_config = ConfigDict(frozen=True)

    key: str  # clean barcode, or fingerprint(brand,size,count)
    method: Literal["exact_gtin", "fingerprint"]


class RegistryLookupResult(BaseModel):  # §1a — output of stage [1]
    model_config = ConfigDict(frozen=True)

    hit: bool
    tier: Literal["tier0_exact", "tier1_ann", "miss"]
    entity: CanonicalEntity | None
    similarity: float | None  # None for tier0 exact match


class CandidateURL(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str  # canonicalized
    source_query: str  # which strategy produced it
    engine: str  # which SearxNG engine
    rank: int
    title_snippet: str | None


class CandidateEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    fetch_status: Literal["ok", "http_error", "timeout", "blocked", "parse_error"]
    fetched_at: datetime
    content_hash: str
    title: str | None
    # schema.org/Product if present. `dict[str, Any]`, not bare `dict` (fails
    # mypy --strict [type-arg]) and not `dict[str, object]` (breaks nested
    # access like jp["brand"]["name"], which is JSON-LD's actual shape). This
    # is the documented `Any` boundary `04` §3 permits: arbitrary third-party
    # JSON-LD has no schema we control. See `02-decision-log.md`.
    jsonld_product: dict[str, Any] | None
    gtin: str | None  # from JSON-LD/microdata — highest value
    og: dict[str, Any]  # OpenGraph tags — same documented-boundary rationale
    breadcrumbs: list[str]
    body_text: str  # boilerplate-stripped
    image_urls: list[str]
    price: str | None
    parse_warnings: list[str]


class MatchFeatures(BaseModel):  # one per candidate — the audit surface
    model_config = ConfigDict(frozen=True)

    barcode_exact: bool | None  # None == cannot evaluate
    brand_match: float  # 0..1
    size_match: Literal["exact", "unit_converted", "mismatch", "absent"]
    count_match: Literal["exact", "mismatch", "absent"]
    variant_overlap: float
    format_consistent: bool | None
    retailer_domain_match: bool
    market_signal: float
    negative_flags: list[str]  # "refill","bundle","travel_size","sample"
    raw_score: float
    calibrated_prob: float


class AdjudicationVerdict(BaseModel):  # P11 — Tier 3's schema-validated answer
    model_config = ConfigDict(frozen=True)

    choice: int | None  # 1-based index into the evidence pack; None == none fits. NEVER a URL
    decisive_fields: list[str]  # which evidence decided it — the citation stage 7 quotes
    rationale: str  # short, grounded; capped by config. Not chain-of-thought (`04` §7)
    prompt_hash: str  # sha256 of the prompt file — `05` §5 version skew. Set by us
    model: str  # the pinned model id that answered — `05` §3


class Selection(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str | None  # None == abstained
    page_title: str | None  # see [PROVISIONAL — Q2]
    confidence: float
    runner_up_gap: float
    features: MatchFeatures | None  # None when resolved via registry hit (tier 0/1)
    adjudicated_by_llm: bool
    resolution_tier: Literal["tier0_exact", "tier1_ann", "tier2_retrieval", "tier3_llm"]
    adjudication: AdjudicationVerdict | None  # set iff adjudicated_by_llm


class OutputRow(BaseModel):  # serializes to qa header exactly, in order
    model_config = ConfigDict(frozen=True)

    ITEM_CODE: int
    NAN_KEY: int
    EXTERNAL_CODE: str  # text, never numeric — see `01` §3
    COUNTRY: str  # comma-joined, passthrough from input
    RETAILER_DESC: str  # passthrough from input, raw
    RETAILER: str  # passthrough from input
    BRAND: str  # passthrough from input
    PRODUCT_URL: str | None  # None serializes to empty cell; see [PROVISIONAL — Q2]
    REASONING: str | None
    MODULE: str | None  # must be one of the 59-value set if set
    GLOBAL_INTERSPACE_CLAIM: str | None
    GLOBAL_CONSUMER_LIFESTAGE_CLAIM: str | None
    GLOBAL_PACKAGING: str | None
    GLOBAL_IF_MEDICATED: str | None
    GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS: str | None
    GLOBAL_IF_WITH_SENSITIVE_CLAIM: str | None
    GLOBAL_ORAL_CARE_FUNCTION: str | None
    GLOBAL_IF_WITH_FLUORIDE: str | None
    GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT_GROUP: str | None
    GLOBAL_METHOD_OF_APPLICATION_DISPENSE: str | None
    GLOBAL_PACKAGING_MATERIAL: str | None
    GLOBAL_DESCRIPTIVE_SIZE_OF_TOOTHBRUSH_HEAD_CLAIM: str | None
    GLOBAL_BRISTLE_STRENGTH_CLAIM: str | None

    # Construction rule: every one of the 13 characteristic fields is either
    # a validated value from `char_value_list.possible_values` (closed) or
    # `char_guidelines`-conformant text (open-ended), or None if the
    # characteristic is not applicable to `MODULE` (`01` §7, `03` §4 stage 6
    # step 1). None is the ONLY representation of "not applicable" — never an
    # empty string, never "N/A", never "NOT APPLICABLE" as a literal value.
    # The assembler (`03` §4 stage 8) writes None → an empty cell, nothing else.
