# 03 — Architecture & Design

Version 0.1 — 2026-09-09. Living document. Update on every finding that changes
a contract, a stage boundary, or a scoring rule.

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

## 2. Pipeline overview

```
  dev/qa row
      │
  [0] Normalize ──────────► ProductQuery
      │
  [1] Candidate generation ─► list[CandidateURL]      (SearxNG, multi-strategy)
      │
  [2] Fetch & extract ──────► list[CandidateEvidence] (cached, JSON-LD first)
      │
  [3] Match & score ────────► RankedCandidates + selected  ◄── HARD-20%
      │                                                        (build directly)
  [4] Module classification ► MODULE
      │
  [5] Characteristic extraction ► dict[char, value|EMPTY]
      │
  [6] Reasoning synthesis ──► REASONING
      │
  [7] Assemble & validate ──► output row (qa schema, exact)
```

Every stage writes its intermediate artifact to disk keyed by `NAN_KEY`. Stages
are independently re-runnable. A change to stage 5 must not force a re-crawl.

## 3. Data contracts

Pydantic models, `src/nimo/contracts.py`. These are the interfaces every stage implements against; changing one is a decision-log entry.

```python
class ProductQuery:
    nan_key: int
    item_code: int
    barcode: str | None            # normalized, None if absent or corrupt
    barcode_corrupt: bool          # True for the rounded dev values
    brand_raw: str                 # "AQUAFRESH (HALEON)"
    brand: str                     # "AQUAFRESH"
    brand_owner: str | None        # "HALEON"
    retailer_raw: str              # "P00R4 (GB) BOOTS"
    retailer: str                  # "BOOTS"
    countries: list[str]           # ["GB"] or ["BE","GB","NL"]
    desc_raw: str
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
    features: MatchFeatures
    adjudicated_by_llm: bool

class OutputRow:                   # serializes to qa header exactly
    ...
```

## 4. Stage specifications

### [0] Normalize

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
and every downstream feature depends on it.

### [1] Candidate generation

SearxNG, self-hosted (`docker compose`, pinned image tag). Never call public
instances — rate limits and non-reproducibility.

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
- Retailer→domain map lives in `config/retailers.yaml`. 44 retailer strings,
  hand-mapped. Unmapped retailers skip S4.
- Canonicalize URLs before dedup: lowercase host, strip `utm_*`, `gclid`,
  fragments, trailing slash, session params.
- Target 10–20 unique candidates. Cap hard; more costs fetch budget for no gain.

Because 377/412 dev barcodes are corrupt (§`01` §3), S1/S2 are dead on most of
dev. **Do not tune retrieval on dev alone** — it will over-fit to the
no-barcode path and silently regress on qa where barcodes are clean.

### [2] Fetch & extract

- Content-addressed disk cache. Key: canonical URL. Re-runs must never re-crawl.
  This is non-negotiable — it makes stages 3–7 iterable in seconds.
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

### [3] Match & score — **HARD-20%, built directly, not delegated**

This is the core algorithmic component. Two layers.

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

**Layer B — LLM adjudication, top-k only.** Invoked when
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

### [4] Module classification

59 modules, closed set from `char_value_list`. `MODULE` is fully labelled in
`dev` (412/412) — **this is the only stage with real, measurable ground truth.**

Design consequence: build a text-only baseline **first**, from `RETAILER_DESC` +
`BRAND` alone, with no URL involved. Two reasons:
1. It is likely to be strong on its own — "wisdom mouthwash ... 300ml" names its
   own module. Measure it before assuming page evidence is needed.
2. It is the fallback path when stage 3 abstains or retrieval fails. Without it,
   a retrieval miss cascades into losing all 14 output columns for that row.

Then layer page evidence on top and measure the delta. If the delta is small,
the URL pipeline's real job is characteristics, not module — which changes where
effort goes.

Evaluate with stratified per-module accuracy. Overall accuracy is misleading:
the top 4 modules are 77% of dev, so a classifier that ignores the tail scores
well and fails on 23 of 27 module types.

### [5] Characteristic extraction

Order matters and is not negotiable:

1. **Applicability gate.** `applicable_characteristics(module)` from
   `char_value_list`. Characteristics not in that set are written as **empty**
   and never sent to the LLM. This is a rule from the dataset guide: guessing a
   non-applicable value is wrong, not partially right.
2. **Per-characteristic extraction.** For each applicable characteristic,
   retrieve its `char_guidelines` row and inject only that guidance. Never dump
   all 196 guideline rows into context.
3. **Closed characteristics** (106 of 195 rows): output constrained to
   `possible_values` exactly. Enforce by validation, not by prompt politeness —
   an out-of-vocabulary value is a failed generation, retried once, then
   `EMPTY`.
4. **Open-ended characteristics** (89 rows): free value derived from evidence,
   but must conform to the guideline's stated form.
5. **Image evidence.** Several characteristics are visual — packaging material,
   bristle strength, head size, dispense method. Route the primary pack shot to
   a multimodal call for those specifically. **[PROVISIONAL — Q7]**
6. **Evidence-absent policy.** When a characteristic is applicable but the page
   carries no evidence, follow the guideline's stated default (often
   `NO CLAIM` or `NOT STATED` — note these are *values*, not nulls, and are
   distinct from "not applicable").

Validate against dev's null-rate profile. If our applicability logic marks a
characteristic applicable where dev has it null in all 412 rows
(`GLOBAL_INTERSPACE_CLAIM`), one of the two is wrong and it needs resolving
before it costs score silently.

### [6] Reasoning synthesis

Generated from the structured evidence record, not free-form. Must cite
concrete signals: which barcode confirmed, which image showed what, which page
element established the module. The `sample_output` reasoning sets the bar —
it names the pack format, the ml size, the fluoride ppm, and the EAN.

Anti-hallucination: any factual claim in `REASONING` must trace to a field in
`CandidateEvidence` or `MatchFeatures`. Assert this in tests with a fixture
where the evidence record deliberately lacks fluoride data — the reasoning must
not mention fluoride.

### [7] Assemble & validate

- Exact `qa` header, exact column order, exact row order, no extra columns.
- Schema validation: closed values in vocabulary; non-applicable characteristics
  empty; `MODULE` in the 59-value set.
- Write `EXTERNAL_CODE` back as text to avoid reintroducing the rounding defect.
- Emit a parallel `trace.jsonl` with the full per-row evidence and features.
  This is the demo artifact and the debugging surface.

## 5. Cross-cutting

- **Determinism.** Temperature 0, fixed seeds, LLM responses cached by
  `hash(model, prompt, params)`. A re-run with no code change must produce a
  byte-identical output file.
- **Resumability.** Batch runner processes by `NAN_KEY`, skips completed,
  survives interruption. 412 rows × network I/O will fail partway; plan for it.
- **Observability.** One structured JSON trace record per row per stage. Cost
  and latency counters per LLM call.
- **Budget.** Track token spend per stage. Stage 2 and 5 dominate.

## 6. Evaluation design

Because there is no URL ground truth, evaluation is layered:

| Layer | Measures | Against |
|---|---|---|
| L1 | Module accuracy, per-module stratified | `dev.MODULE`, 412 labelled rows |
| L2 | Characteristic accuracy per characteristic; applicability precision/recall | `dev` characteristic columns |
| L3 | URL correctness | hand-labelled gold set, ~50 rows stratified by module — **we must build this** |
| L4 | Abstention calibration: is `calibrated_prob` honest? | L3 gold set |
| L5 | Reasoning groundedness | fixture-based assertions, manual spot check |

L3 is the missing piece and the first thing to build after the loader. Without
it, stage 3 is unoptimizable and every improvement is a guess.

## 7. Rejected alternatives

- **Autonomous ReAct agent over search+fetch tools.** Rejected: non-reproducible,
  expensive, and unscoreable against a 412-row batch. Revisit only if the
  deterministic pipeline plateaus.
- **Pure-LLM ranking of raw candidate HTML.** Rejected: token cost, and it
  discards the hard signals (GTIN, size, count) that actually decide identity.
- **Embedding-only nearest-neighbour matching.** Rejected: cosine similarity
  cannot represent "2-pack ≠ single" or "different GTIN ⇒ different product".
  Useful as one feature inside layer A, not as the mechanism.
- **Hard country filter on candidate domains.** Rejected: contradicts the
  organizers' reference answer. Scored feature instead.
