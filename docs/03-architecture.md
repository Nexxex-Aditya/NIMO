# 03 — Architecture & Design

Version 0.5 — 2026-09-10. Living document. Update on every finding that changes
a contract, a stage boundary, or a scoring rule. Change history lives in
`02-decision-log.md`, not here — this file always reflects current state only.

Sections marked **[PROVISIONAL — Qn]** depend on unresolved organizer questions
in `02-decision-log.md`. Implement them behind the stated interface so the
answer changes a config value, not a module.

---

## 1. Architectural stance

**NIMO is a deterministic pipeline with LLMs as bounded components. It is not an
autonomous agent loop.**

This is a deliberate rejection of the obvious "give an agent tools and let it
figure it out" design. Reasons:

- **Scoreability.** A free-roaming agent produces a different trajectory per
  run. With 412 rows to score and no URL ground truth (§`01`, §6), we cannot
  afford non-reproducible output.
- **Debuggability.** When row 217 picks the wrong URL, we need to see *which
  feature* misfired. A pipeline gives a per-stage trace; an agent gives a
  transcript.
- **Cost.** 412 items × ~15 candidates × page content is a lot of tokens.
  Deterministic pre-filtering cuts LLM invocations by roughly an order of
  magnitude.
- **The brief rewards transparency.** "Provide clear and transparent reasoning"
  is an explicit success criterion. Feature-level evidence is transparent;
  chain-of-thought is not.

Where the LLM *is* used: adjudicating the top-k ambiguous candidates, module
classification, characteristic extraction from page evidence, and reasoning
synthesis. Each is a typed function with a schema-validated output — never a
free-form step that can decide to do something else.

The compute cascade in §1a is additional determinism, not a departure from this
stance: tier selection is a threshold comparison against a persisted registry,
not an agent deciding what to do next.

## 1a. Canonical Entity Registry & compute cascade

### The problem this solves

The pipeline in §2 (v0.1) treats every row as new: normalize, retrieve, fetch,
match, from scratch, every time. That is correct for *correctness* but wrong for
*efficiency at production scale*, because it ignores the dominant structure in
this domain: **the same physical product recurs constantly** — across
retailers, across countries, across re-audits of the same catalog. NIQ's own
data already shows this at toy scale: `dev` and `qa` share 40 identical
`ITEM_CODE` values despite being nominally disjoint sets (`01` §6), and `dev`
alone spans 44 retailers and 50+ country combinations for what is very likely
far fewer than 331 truly distinct products (331 is only the distinct
`ITEM_CODE` count in dev, not a floor — a rescan or a promo-cycle refresh
produces new rows for the same real-world item).

A pipeline with no memory pays the full retrieval + matching + LLM cost for
every re-observation of the same product, forever. That does not scale and it
does not win on the stated criteria — the hackathon explicitly weighs time and
resource efficiency, not just accuracy.

### Why not a GNN or hyperbolic embeddings for this (see also §7)

Both were considered and rejected, but the underlying need they gesture at —
"products relate to each other, use that structure" — is real. It's just met
differently:

- A **GNN** needs multi-hop relational structure and enough labeled examples to
  learn message-passing weights. This problem has neither: matching is
  pairwise (does this page describe this product?), and 412 rows with only
  `MODULE` fully labelled cannot train a graph neural net without overfitting.
- What the problem *does* have is a **transitive equivalence relation**: "these
  N rows are the same physical product" is symmetric and transitive by
  construction. That is exactly what **Union-Find** (disjoint-set) computes,
  with no training data and no neural forward pass:

| | Union-Find match graph | Learned GNN |
|---|---|---|
| Training data required | none — deterministic algorithm | thousands of labeled pairs, minimum |
| Complexity | `O(n·α(n))` — effectively linear | forward pass per node, every inference |
| Behavior at n=412 | correct immediately | overfits or fails to converge |
| Generalizes as catalog grows | same algorithm, no retraining | needs retraining as distribution shifts |
| Marginal cost of a repeat item | → 0 as the registry warms | constant, every time |

This is the honest graph-shaped answer to the efficiency requirement — not
neural, but real, and it is what production entity-resolution systems at this
scale (retail master-data matching, e-commerce catalog dedup) actually run.

### Components

**1. Canonical Entity Registry.** A persistent store (`data/registry/`, backed
up, not treated as disposable cache) of resolved products. Each record is a
`CanonicalEntity` (§3): the barcode if known, brand, normalized size/count, the
resolved module, URL, and characteristics, plus every `NAN_KEY` folded into it
and which tier resolved it.

**2. Blocking, before any expensive comparison.** Never compare a new row
against every registry entity. Partition first:
- **Exact-key blocking** (current scope): block key = clean barcode when
  present, else a deterministic fingerprint of `brand + size_ml_equiv + count`
  from `DescTokens`. Cheap, exact, sufficient for a single-category
  (oral-health), single-language dataset.
- **MinHash/LSH blocking** is the specified upgrade path for when description
  drift is high enough that exact keys under-recall — multi-category or
  multi-language catalogs where "aquafresh whitening 100ml" and "AF Whitening
  Pump 100 mL" don't share an exact key. **Do not build this now** — there is
  no measured recall problem at this dataset's scope that justifies it. Build
  it when profiling on a larger, messier catalog shows exact-key blocking
  missing real duplicates.

**3. Union-Find match graph.** When a match is confirmed at high confidence
(§4, stage 4 write-back), the row's `NAN_KEY` is merged into an existing entity
sharing its block key, or a new entity is created. Connected components over
this relation are computed by disjoint-set union — deterministic, no training,
`O(n·α(n))`.

**4. Tiered compute cascade.** Every row falls through only as far as it needs to:

| Tier | Trigger | Cost | Latency | Coverage |
|---|---|---|---|---|
| 0 — exact | clean `barcode` matches a registry entity | ~0 (hash lookup) | ms | previously resolved, same GTIN |
| 1 — ANN | no exact hit; identity-fingerprint similarity ≥ `τ_ann` within the same block | low (dot products) | low ms | previously resolved, near-duplicate description |
| 2 — retrieval | tier 0/1 miss | moderate | seconds (network) | genuinely new item — existing SearxNG pipeline, §4 stages 2–4 |
| 3 — LLM adjudication | tier 2 ambiguous (`runner_up_gap` small) | high | seconds | ambiguous cases only, top-k, §4 stage 4 Layer B — unchanged from v0.1 |

At current registry size (low hundreds to low thousands of entities),
tier-1 similarity search is brute-force cosine — fast enough, and simpler to
audit than an index. Swap for HNSW only once profiling shows brute-force is the
bottleneck; do not pre-build index infrastructure the data doesn't yet justify.

### The efficiency claim, stated so it can be checked, not just asserted

"Cost per item declines as the registry warms" is a testable claim, not a
slogan — but an earlier version of this section proposed the wrong check, and
it's worth being explicit about why rather than quietly swapping it.

**What doesn't work:** resolving `dev` then `qa` and expecting the 40
`ITEM_CODE` values common to both to hit **Tier 0** on their second
observation. This can't happen — Tier 0 is an exact clean-barcode match, and
the barcode corruption defect (`01` §3) hits this exact overlap set too: of
the 102 `dev` rows carrying one of those 40 `ITEM_CODE`s, only 4 have a usable
barcode, and **zero** `ITEM_CODE`s have both a clean `dev`-side barcode and a
clean `qa`-side barcode that actually agree. Tier 0 cannot fire on this set at
all, not rarely — never. Proposing it as the checkable demo was a design
error, caught before it reached a test that would have failed and required
someone to guess why.

**What actually works:** the same overlap, checked against **Tier 1**
instead. Tier 1 blocks on a brand/size/count fingerprint, not the barcode —
it doesn't depend on `EXTERNAL_CODE` being intact. The check: resolve `dev`
first, then `qa`; for the 40 overlapping `ITEM_CODE`s, measure what fraction
of the `qa`-side rows Tier 1 recovers as a fingerprint match to their
already-resolved `dev`-side counterpart. Report this as a **recall
percentage**, not a raw hit count — some legitimate misses are expected where
the fingerprint genuinely differs (a repack, a size change under the same
`ITEM_CODE`), so 100% isn't the bar; a large majority is.

A tighter, currently-unused alternative worth keeping in reserve: 23
`NAN_KEY` values are also common to both sets (`01` §9) — a smaller overlap,
but `NAN_KEY` may be a more reliable "same observed item" signal than
`ITEM_CODE`, which is explicitly documented as non-unique. Not adopted as the
primary check here, just flagged as a fallback if Tier-1 recall on the
`ITEM_CODE` overlap turns out to be hard to interpret.

Report tier distribution and this recall figure in the run summary (§5) and
the demo — it's a live, honest demonstration of the actual efficiency
property, not the one originally (and incorrectly) proposed.

### Risk this introduces, and its control

A wrong merge is worse than a wrong single-row answer — it poisons every future
row that blocks against it. Two controls:
- `τ_merge` (the write-back confidence threshold, §4 stage 4) is stricter than
  the general acceptance threshold.
- **L6** in the evaluation design (§6) exists specifically to catch this: spot
  agreement-check tier-0/1 hits against the slow path on a held-out sample
  before trusting the registry's hit rate as a demo number.

## 2. Pipeline overview

```
  dev/qa row
      │
  [0] Normalize ─────────────────► ProductQuery
      │
  [1] Registry lookup & block ───► RegistryLookupResult   ◄── Tier 0 / Tier 1
      │
      ├── hit (tier 0 exact, or tier 1 ANN ≥ τ_ann) ──────────────┐
      │                                                            │
      └── miss ──┐                                                 │
                 ▼                                                 │
  [2] Candidate generation ──────► list[CandidateURL]       Tier 2 │
      │           (SearxNG, multi-strategy)                        │
      ▼                                                             │
  [3] Fetch & extract ───────────► list[CandidateEvidence]          │
      │           (cached, JSON-LD first)                          │
      ▼                                                             │
  [4] Match & score ─────────────► RankedCandidates + selected  Tier 3 (LLM)
      │           HARD-20% — build directly                        │
      │           write-back merges into registry (Union-Find)     │
      └──────────────────────────────────────────────────────────┘
      │
      ▼  (both paths converge here)
  [5] Module classification ─────► MODULE
      │
  [6] Characteristic extraction ─► dict[char, value|EMPTY]
      │
  [7] Reasoning synthesis ───────► REASONING
      │
  [8] Assemble & validate ───────► output row (qa schema, exact)
```

Every stage writes its intermediate artifact to disk keyed by `NAN_KEY`. Stages
are independently re-runnable. A change to stage 6 must not force a re-crawl. A
registry hit at stage 1 skips stages 2–4 entirely — that skip is the whole
point of §1a.

## 3. Data contracts

Pydantic models, `src/nimo/contracts.py`. These are the interfaces every stage implements against; changing one is a decision-log entry.

**Every model must round-trip through JSON** (`04` §1's P1 gate) —
`model_dump_json()` then `model_validate_json()` returns an equal object. This
rules out `dict` keyed by anything other than `str` (a `tuple[str, str]` key,
for instance, has no valid JSON object-key representation). Where the natural
shape is a lookup table — `CharacteristicRule`, `CharacteristicGuideline`
below — the contract is a flat `list[Model]`; building an in-memory
`dict[(module, characteristic), ...]` from that list for convenient lookup is
fine *inside* a module, it just isn't the type that crosses the boundary.

```python
class RawRow:                      # loader (P2) output — one per dev/qa row, pre-normalization
    nan_key: int
    item_code: int
    barcode: str | None             # normalized string, None if absent OR corrupt (see `01` §3)
    barcode_raw: str | None         # original string before nulling on corruption — audit/trace only, NEVER used for matching or registry blocking
    barcode_corrupt: bool           # True for the rounded dev values
    brand_raw: str                  # "AQUAFRESH (HALEON)" — verbatim from BRAND column, encoding-repaired (see brand_encoding_suspect) before the parenthetical split below runs
    brand: str                      # "AQUAFRESH" — mechanical parenthetical split, not NLP
    brand_owner: str | None         # "HALEON"
    brand_encoding_suspect: bool    # True if ftfy changed brand_raw from the source cell — `01` §13, `01` §10 #9
    retailer_raw: str               # "P00R4 (GB) BOOTS" — verbatim from RETAILER column
    retailer: str                   # "BOOTS" — looked up from config/retailers.yaml, see specs/loader.md
    countries: list[str]            # ["GB"] or ["BE","GB","NL"] — split on COUNTRY
    desc_raw: str                   # RETAILER_DESC, whitespace collapsed/trimmed and encoding-repaired (see desc_encoding_suspect) — no other processing; junk-token stripping is P3's job, not this field's
    desc_encoding_suspect: bool     # True if ftfy changed desc_raw from the source cell — `01` §13, `01` §10 #9

class CharacteristicRule:          # loader (P2) output — one row of char_value_list
    module: str
    characteristic: str             # underscored form, e.g. "GLOBAL_BRISTLE_STRENGTH_CLAIM"
    open_close: Literal["Close", "Open-ended"]
    binary: bool
    allowed_values: list[str]       # parsed from possible_values via ast.literal_eval

class CharacteristicGuideline:     # loader (P2) output — one row of char_guidelines
    module: str
    characteristic: str             # normalized to the same underscored form as above
    guideline_text: str

class ProductQuery(RawRow):        # normalizer (P3) output — RawRow + parsed description
    desc_clean: str                # junk tokens stripped
    tokens: DescTokens

class DescTokens:                  # parsed from desc_clean
    variant_terms: list[str]       # "whitening", "sensitive", "original"
    size_value: float | None       # 100.0
    size_unit: str | None          # "ml" — normalized
    size_ml_equiv: float | None    # for cross-unit comparison
    count: int | None              # multipack count; None == 1
    format_hints: list[str]        # "pump", "spray", "tablets"
    stripped_junk: list[str]       # audit trail of what was removed

class BlockKey:                    # §1a — blocking, computed at stage [1]
    key: str                       # clean barcode, or fingerprint(brand,size,count)
    method: Literal["exact_gtin", "fingerprint"]

class CanonicalEntity:             # §1a — one persisted, resolved product
    entity_id: str                 # stable hash of (barcode or fingerprint) —
                                    # never a random uuid; must be reproducible
    barcode: str | None            # authoritative GTIN once confirmed
    brand: str
    size_ml_equiv: float | None
    count: int
    module: str | None
    resolved_url: str | None
    page_title: str | None         # see [PROVISIONAL — Q2]
    characteristics: dict[str, str]  # applicable-only, post-gate values
    confidence: float
    member_nan_keys: list[int]     # every row folded into this entity
    resolution_tier: Literal["tier0_exact","tier1_ann","tier2_retrieval","tier3_llm"]
    created_at: datetime
    updated_at: datetime

class RegistryLookupResult:        # §1a — output of stage [1]
    hit: bool
    tier: Literal["tier0_exact", "tier1_ann", "miss"]
    entity: CanonicalEntity | None
    similarity: float | None       # None for tier0 exact match

class CandidateURL:
    url: str                       # canonicalized
    source_query: str              # which strategy produced it
    engine: str                    # which SearxNG engine
    rank: int
    title_snippet: str | None

class CandidateEvidence:
    url: str
    fetch_status: Literal["ok","http_error","timeout","blocked","parse_error"]
    fetched_at: datetime
    content_hash: str
    title: str | None
    jsonld_product: dict | None    # schema.org/Product if present
    gtin: str | None               # from JSON-LD/microdata — highest value
    og: dict
    breadcrumbs: list[str]
    body_text: str                 # boilerplate-stripped
    image_urls: list[str]
    price: str | None
    parse_warnings: list[str]

class MatchFeatures:               # one per candidate — the audit surface
    barcode_exact: bool | None     # None == cannot evaluate
    brand_match: float             # 0..1
    size_match: Literal["exact","unit_converted","mismatch","absent"]
    count_match: Literal["exact","mismatch","absent"]
    variant_overlap: float
    format_consistent: bool | None
    retailer_domain_match: bool
    market_signal: float
    negative_flags: list[str]      # "refill","bundle","travel_size","sample"
    raw_score: float
    calibrated_prob: float

class Selection:
    url: str | None                # None == abstained
    page_title: str | None         # see [PROVISIONAL — Q2]
    confidence: float
    runner_up_gap: float
    features: MatchFeatures | None # None when resolved via registry hit (tier 0/1)
    adjudicated_by_llm: bool
    resolution_tier: Literal["tier0_exact","tier1_ann","tier2_retrieval","tier3_llm"]

class OutputRow:                   # serializes to qa header exactly, in order
    ITEM_CODE: int
    NAN_KEY: int
    EXTERNAL_CODE: str              # text, never numeric — see `01` §3
    COUNTRY: str                    # comma-joined, passthrough from input
    RETAILER_DESC: str               # passthrough from input, raw
    RETAILER: str                   # passthrough from input
    BRAND: str                      # passthrough from input
    PRODUCT_URL: str | None          # None serializes to empty cell; see [PROVISIONAL — Q2]
    REASONING: str | None
    MODULE: str | None              # must be one of the 59-value set if set
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
```

Assembly note (ties to `03` §4 stage 8): field order above is the literal qa
sheet column order, verified against the workbook header, not re-derived from
memory each time — assert equality against the live `qa` header at load time
and fail loudly on drift, since a silently reordered submission scores zero
regardless of correct values.
```

## 4. Stage specifications

### [0] Normalize

Input: `RawRow` (loader output, P2 — one per `dev`/`qa` row). Output:
`ProductQuery` (`RawRow` plus `desc_clean` and `tokens`). This is the P3 build
phase; the loader (P2) that produces `RawRow` is not itself a pipeline stage —
it runs once, batch-wide, before any row enters the per-row pipeline below.

`RETAILER_DESC` is dirty. Real examples:

    "aquafresh whitening pump 100ml unit 00000012 e0028"
    "wisdom mouthwash chlorhexidine digluconate 0.2% original alcohol free 300ml wisdom chlorhexidine mouthwash intouch"
    "Colgate Total Advanced Pump Toothpaste 100ML                                    100ML   "

Observed junk classes to strip: trailing retailer codes (`e0028`, `intouch`),
`unit \d+` fragments, duplicated size suffixes, run-on whitespace, brand name
repeated mid-string.

Rules:
- Strip, never delete silently — record removals in `stripped_junk`.
- Size parsing handles `ml`, `l`, `g`, `kg`, `oz`, bare counts (`4 pack`,
  `x4`, `2s`). Normalize volume to ml, mass to g.
- Multipack count is a **hard identity attribute**. A 2-pack and a single are
  different products. Do not let it be absorbed into fuzzy text similarity.
- Percentages (`0.2%`) are concentration, not size. Do not parse as pack size.

Deterministic and rule-based. No LLM here — it must be reproducible and cheap,
and every downstream feature (including the stage-1 blocking key) depends on it.

### [1] Registry lookup & blocking — Tier 0 / Tier 1

Full rationale in §1a. Mechanics:

1. **Block key computation.**
   - `barcode` present and not corrupt → `BlockKey(key=barcode, method="exact_gtin")`.
   - Else → `BlockKey(key=fingerprint(brand, size_ml_equiv, count), method="fingerprint")`,
     a deterministic hash of normalized identity fields from `DescTokens`. Not
     free text, and not module — module isn't known yet on a first pass.
2. **Tier 0 — exact.** Registry lookup by the barcode key. A hit means this
   GTIN has been resolved before, in this run or a prior persisted one.
   Confidence carries over from the stored entity. **Skip stages 2–4**; proceed
   to stage 5 with the entity's `module`, `resolved_url`, `characteristics`.
3. **Tier 1 — approximate.** No exact hit → brute-force cosine over a small
   identity embedding (brand + variant terms + size + count — not page
   content) against other entities in the same block. Hit above `τ_ann` →
   short-circuit the same way as tier 0, with a confidence discount recorded on
   `Selection.confidence`.
4. **Miss.** No hit at either tier → proceed to stage 2. This is the only path
   that touches the network or an LLM for identity resolution.

`τ_ann` and `τ_merge` (stage 4) are both tuned against the gold set (`04` P4),
the same way the abstention threshold is — not hand-picked.

### [2] Candidate generation

Reached only on a stage-1 miss. SearxNG, self-hosted (`docker compose`, pinned
image tag). Never call public instances — rate limits and non-reproducibility.

Query strategies, run in order, results merged:

| # | Strategy | Query shape | Use when |
|---|---|---|---|
| S1 | Barcode exact | `"5014697056627"` | `barcode` present and not corrupt |
| S2 | Barcode + brand | `5014697056627 aquafresh` | as S1 |
| S3 | Brand + variant + size | `aquafresh whitening pump 100ml` | always |
| S4 | Site-restricted | `site:boots.com aquafresh whitening 100ml` | `retailer` maps to a known domain |
| S5 | Brand + desc verbatim | `desc_clean` | fallback |

- S1/S2 first — if a barcode-exact hit returns a page whose JSON-LD `gtin13`
  equals the query barcode, that is near-decisive and short-circuits ranking.
- Retailer→domain map lives in `config/retailers.yaml`. **50 retailer
  strings** (`01` §9 — not 44, that was a `dev`-only count), hand-mapped. The
  same file also supplies the retailer name-cleaning table the loader (P2)
  uses — `01` §12: a mechanical regex fails on 21 of the 50, one silently
  (drops the actual retailer name), so this table is hand-reviewed in full,
  not regex-derived and spot-checked. Unmapped retailers skip S4.
- Canonicalize URLs before dedup: lowercase host, strip `utm_*`, `gclid`,
  fragments, trailing slash, session params.
- Target 10–20 unique candidates. Cap hard; more costs fetch budget for no gain.

Because 377/412 dev barcodes are corrupt (§`01` §3), S1/S2 are dead on most of
dev. **Do not tune retrieval on dev alone** — it will over-fit to the
no-barcode path and silently regress on qa where barcodes are clean.

### [3] Fetch & extract

- Content-addressed disk cache. Key: canonical URL. Re-runs must never re-crawl.
  This is non-negotiable — it makes stages 4–8 iterable in seconds.
- Politeness: per-domain rate limit, honor `robots.txt`, real UA string with
  contact, concurrency cap. **[PROVISIONAL — Q6]**
- Retries: exponential backoff with jitter, max 3, only on 5xx/timeout. Never
  retry a 404 or 403.
- Extraction priority, highest-value first:
  1. **JSON-LD `schema.org/Product`** — often carries `gtin13`, `brand`, `name`,
     `image`, `size`. When present this is worth more than the entire body text.
  2. Microdata / RDFa fallback.
  3. OpenGraph tags.
  4. Boilerplate-stripped body text.
  5. Image URLs — primary pack shot heuristic: largest, in-gallery, non-icon.
- A page that fails extraction gets `fetch_status` set and stays in the record.
  Do not drop it — a systematic block on one retailer is a finding, not noise.

### [4] Match & score — **HARD-20%, built directly, not delegated**

This is the core algorithmic component. Two layers, plus registry write-back.

**Layer A — deterministic feature scoring.** Produces `MatchFeatures` per
candidate. Weighted, with hard rules that override the weighted sum:

Hard rules (evaluated first):
- `gtin` on page == query barcode (both valid) → accept, score 1.0, stop.
- `gtin` on page != query barcode (both valid) → reject outright. A confirmed
  different GTIN is a different product regardless of how similar the text is.
- Size mismatch where both sizes are confidently parsed → hard demotion, not
  rejection (retailer pages sometimes list a range).
- Count mismatch (single vs multipack) → hard demotion.
- Negative flags (`refill` when query isn't a refill, `travel`, `sample`,
  `bundle`, `gift set`) → hard demotion.

Weighted features for everything else: brand match, variant token overlap
(TF-IDF or embedding cosine over variant terms only, not whole description),
format consistency, retailer domain match, market signal.

**Market is a scored feature, not a filter.** The organizers' own
`sample_output` resolves a `FR,GB` item to an Amazon.in page (§`01` §5). A
country hard-filter would reject their reference answer.
**[PROVISIONAL — Q4]**

**Layer B — LLM adjudication, top-k only (Tier 3).** Invoked when
`runner_up_gap < threshold`. Input is the structured evidence record for the
top 3–5 candidates — never raw HTML. Output is a schema-constrained choice plus
a citation of which evidence decided it. Temperature 0, cached by prompt hash.

**Calibration.** Raw scores are meaningless as confidence. Fit a calibration
map (isotonic or Platt) on the hand-labelled URL gold set so
`calibrated_prob` is an actual probability. This is what abstention thresholds
key off.

**Abstention.** If `calibrated_prob < τ`, emit no URL. Whether that is correct
depends on whether a wrong URL is penalized more than a blank one.
**[PROVISIONAL — Q3]** Build the threshold as config; set it once scoring is known.

**Write-back to the registry (§1a).** A confirmed match — hard-rule GTIN
accept, or `calibrated_prob ≥ τ_merge` — creates or updates a `CanonicalEntity`:
union this row's `NAN_KEY` into an existing entity sharing the block key
(Union-Find merge, deterministic, no training), or create a new one. This is
what makes tiers 0–1 warm up over a run and across runs — the registry is
disk-persisted, not scoped to one batch. `τ_merge` must be stricter than the
general acceptance threshold: a wrong merge poisons every future row that
blocks against it, not just this one (§1a, "Risk").

### [5] Module classification

59 modules, closed set from `char_value_list`. `MODULE` is fully labelled in
`dev` (412/412) — **this is the only stage with real, measurable ground truth.**

Design consequence: build a text-only baseline **first**, from `RETAILER_DESC` +
`BRAND` alone, with no URL involved. Two reasons:
1. It is likely to be strong on its own — "wisdom mouthwash ... 300ml" names its
   own module. Measure it before assuming page evidence is needed.
2. It is the fallback path when stage 4 abstains, or when both the registry
   (stage 1) and retrieval (stage 2) fail to produce a usable page. Without it,
   a retrieval miss cascades into losing all 14 output columns for that row.

Then layer page evidence on top and measure the delta. If the delta is small,
the URL pipeline's real job is characteristics, not module — which changes where
effort goes.

Evaluate with stratified per-module accuracy. Overall accuracy is misleading:
the top 4 modules are 77% of dev, so a classifier that ignores the tail scores
well and fails on 23 of 27 module types.

### [6] Characteristic extraction

Order matters and is not negotiable:

1. **Applicability gate.** `applicable_characteristics(module)` from
   `char_value_list`. Characteristics not in that set are written as **empty**
   and never sent to the LLM. This is a rule from the dataset guide: guessing a
   non-applicable value is wrong, not partially right.
2. **Per-characteristic extraction.** For each applicable characteristic,
   retrieve its `char_guidelines` row and inject only that guidance. Never dump
   all 196 guideline rows into context.
3. **Closed characteristics** (106 of 195 rows): output constrained to
   `possible_values`, validated **per `&`-separated component**, not as a
   whole-string match. `01` §11: 187 of `dev`'s 412 ground-truth rows are
   `&`-joined combinations of 2–3 individually-valid values (e.g.
   `'ANTI BACTERIAL & FRESHENING & WHITENING'`), and this is the *common*
   case for `GLOBAL_ORAL_CARE_FUNCTION` and `GLOBAL_CONSUMER_LIFESTAGE_CLAIM`
   specifically, not a rare one. Split on `&`, validate each component against
   `possible_values` independently, accept if every component is valid. A
   generation where every component fails to validate is a failed generation —
   retried once, then `EMPTY`, same as before; this changes what counts as
   "failed," not the failure-handling policy itself.
4. **Open-ended characteristics** (89 rows): free value derived from evidence,
   but must conform to the guideline's stated form.
5. **Image evidence.** Several characteristics are visual — packaging material,
   bristle strength, head size, dispense method. Route the primary pack shot to
   a multimodal call for those specifically. **[PROVISIONAL — Q7]**
6. **Evidence-absent policy.** When a characteristic is applicable but the page
   carries no evidence, follow the guideline's stated default (often
   `NO CLAIM` or `NOT STATED` — note these are *values*, not nulls, and are
   distinct from "not applicable").

Validate against dev's null-rate profile — this cross-check is now confirmed
clean (`01` §6): with the corrected characteristic-name alias map (`01` §8),
applicability and null pattern agree on all 412 rows. One characteristic
needs explicit attention despite being null in all 412 `dev` rows:
`GLOBAL_INTERSPACE_CLAIM` is genuinely applicable to one module
(`TOOTHBRUSHES - MANUAL - INTERDENTAL`), which simply has zero `dev` rows —
but two `qa` candidate rows need it predicted (`01` §6). Do not treat this
characteristic's all-null `dev` history as evidence the applicability logic
has a bug; it doesn't, `dev` just doesn't happen to cover that module.

A row resolved via a registry hit (stage 1, tier 0/1) carries its
characteristics directly from the stored `CanonicalEntity` and skips
re-extraction — that stored value was itself produced by this same stage on a
prior row, so the applicability gate has already been applied once, correctly.

### [7] Reasoning synthesis

Generated from the structured evidence record, not free-form. Must cite
concrete signals: which barcode confirmed, which image showed what, which page
element established the module. The `sample_output` reasoning sets the bar —
it names the pack format, the ml size, the fluoride ppm, and the EAN.

Anti-hallucination: any factual claim in `REASONING` must trace to a field in
`CandidateEvidence` or `MatchFeatures`. Assert this in tests with a fixture
where the evidence record deliberately lacks fluoride data — the reasoning must
not mention fluoride.

For a registry-resolved row, reasoning should say so plainly ("identity
confirmed by exact barcode match to a previously resolved item") rather than
fabricating fresh page-evidence language for evidence that wasn't re-examined
this time.

### [8] Assemble & validate

- Exact `qa` header, exact column order, exact row order, no extra columns.
- Schema validation: closed values in vocabulary; non-applicable characteristics
  empty; `MODULE` in the 59-value set.
- Write `EXTERNAL_CODE` back as text to avoid reintroducing the rounding defect.
- Emit a parallel `trace.jsonl` with the full per-row evidence, features, and
  `resolution_tier`. This is the demo artifact and the debugging surface — tier
  distribution is what makes the efficiency claim in §1a checkable.

## 5. Cross-cutting

- **Determinism.** Temperature 0, fixed seeds, LLM responses cached by
  `hash(model, prompt, params)`. A re-run with no code change must produce a
  byte-identical output file.
- **Resumability.** Batch runner processes by `NAN_KEY`, skips completed,
  survives interruption. 412 rows × network I/O will fail partway; plan for it.
- **Observability.** One structured JSON trace record per row per stage. Cost
  and latency counters per LLM call.
- **Budget.** Track token spend per stage. Stages 3 and 6 dominate.
- **Registry warm-start.** The registry persists across runs
  (`data/registry/`, backed up — this is derived-but-valuable state, unlike
  `data/cache/` which is disposable). Cost per row is not constant: a tier-0/1
  hit skips retrieval and matching entirely. Report tier distribution in every
  run summary — that is the evidence for the time/resource-efficiency claim,
  not an assertion (§1a).

## 6. Evaluation design

Because there is no URL ground truth, evaluation is layered:

| Layer | Measures | Against |
|---|---|---|
| L1 | Module accuracy, per-module stratified | `dev.MODULE`, 412 labelled rows |
| L2 | Characteristic accuracy per characteristic; applicability precision/recall | `dev` characteristic columns |
| L3 | URL correctness | hand-labelled gold set, ~50 rows stratified by module — **we must build this** |
| L4 | Abstention calibration: is `calibrated_prob` honest? | L3 gold set |
| L5 | Reasoning groundedness | fixture-based assertions, manual spot check |
| L6 | Registry precision: do tier-0/1 hits agree with the tier-2/3 answer for the same item? | held-out rows forced through both paths |

L3 is the missing piece and the first thing to build after the loader. Without
it, stage 4 is unoptimizable and every improvement is a guess.

L6 exists because a wrong registry hit is worse than a miss — it poisons every
row that blocks against it (§1a, "Risk"). Before reporting tier-0/1 hit rate as
a demo number, spot-check it against the slow path on a sample.

## 7. Rejected alternatives

- **Learned GNN over a product/candidate graph.** Rejected: this problem has no
  multi-hop structure — matching is pairwise (does this page describe this
  product?), not chain-dependent — and 412 rows with only `MODULE` fully
  labelled cannot train message-passing weights without overfitting. The
  graph-shaped need this points at — merging confirmed-duplicate entities — is
  met by Union-Find in §1a: no training data, `O(n·α(n))`, correct immediately
  at this dataset's scale, and the same algorithm still works unchanged as the
  catalog grows.
- **Hyperbolic embeddings / hyperbolic RAG.** Rejected: the taxonomy
  (`char_value_list`) is 3 levels deep and fully enumerable — 59 modules, 13
  characteristics, ~195 (module, characteristic) pairs. That is a lookup table,
  not an approximate-retrieval problem, and Euclidean distance does not distort
  a tree this shallow. Would only apply if the category taxonomy grew far
  deeper and higher-branching than this dataset's.
- **Autonomous ReAct agent over search+fetch tools.** Rejected: non-reproducible,
  expensive, and unscoreable against a 412-row batch. Revisit only if the
  deterministic pipeline plateaus.
- **Pure-LLM ranking of raw candidate HTML.** Rejected: token cost, and it
  discards the hard signals (GTIN, size, count) that actually decide identity.
- **Embedding-only nearest-neighbour matching.** Rejected: cosine similarity
  cannot represent "2-pack ≠ single" or "different GTIN ⇒ different product".
  Useful as one feature inside layer A, and as the tier-1 registry similarity
  check (§1a) — not as the sole mechanism.
- **Hard country filter on candidate domains.** Rejected: contradicts the
  organizers' reference answer. Scored feature instead.
- **MinHash/LSH blocking, built now.** Deferred, not rejected: exact-key
  blocking is sufficient for this dataset's single-category, single-language
  scope. Build LSH when a larger or messier catalog shows measured recall loss
  from exact-key blocking — not preemptively (§1a).
