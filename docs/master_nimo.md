# master_nimo — the whole project in one document

NIMO, "The Product Truth Agent". Team Matrix Slayers, NielsenIQ Innovation
Portal hackathon. Written 2026-09-12 from the repo's own record: every
number here is in `docs/02-decision-log.md` or `docs/04-build-standards.md`
§1 with the measurement that produced it. Where something is *not* measured,
this document says so rather than rounding up.

How to read it: §1–§3 are the problem and the shape of the answer; §4 walks
every stage (what it does, why that way, what it bought); §5–§7 are the
guarantees, the tooling and how to run it; §8–§10 are results, limits and
what we would tell the organizers.

---

## 1. The problem, in the organizers' words and in ours

**The brief.** The same product appears across ecommerce sites, retailer
catalogs, marketplaces and manufacturer pages under different names, pack
sizes and languages. Given a retail record (retailer description, barcode,
brand, country, retailer), find the webpage that is *that product's* true
digital representation, distinguish it from similar or misleading matches,
and explain the reasoning. Success criteria: accurate URL, correct against
look-alikes, transparent reasoning, evidence beyond keyword matching.

**What the dataset actually asks for, which is more than the brief.** The
workbook's own guide states a two-stage chain: find the URL → identify the
product's **MODULE** (one of 59 oral-care categories) → determine which of
**13 characteristics** apply to that module → predict each one's value from
page/image evidence and business guidelines. The submission is a 23-column
sheet per row. So URL selection is stage 1, and **structured characteristic
extraction is stage 2 and is most of the scored surface** (13 columns
against 1). A hard rule from the guide: a characteristic that does not apply
to the module must be left **empty** — a plausible value there is a wrong
answer, not partial credit.

**What NIMO is.** A deterministic, resumable, eight-stage pipeline that
turns each record into a URL, a module, 13 characteristic values and a
grounded explanation — with the LLM used as two bounded, schema-validated
components (tie-breaking between candidate pages; extracting characteristic
values from evidence), a persistent memory of resolved products so repeat
items cost nothing, and a full trace per row per stage. It is **not** an
autonomous agent loop, on purpose (§3).

---

## 2. The dataset — what we found before designing anything

Everything below was measured on the workbook, not inferred from the brief.
Several of these findings invalidated the obvious design and are the reason
the pipeline looks the way it does. (`docs/01-dataset-contract.md`)

| Finding | Measured | Consequence |
|---|---|---|
| **No candidate webpages are provided** — the brief promised them; `PRODUCT_URL` is 100% empty in both sheets | 412/412 dev, 412/412 qa | Candidate retrieval is ours to build: a meta-search layer (SearxNG), a fetcher, an extractor |
| **dev barcodes are destroyed** by an Excel numeric cell format (`0.00E+00`) — rounded to 3 significant figures | 377 of 412 dev rows; of the 35 survivors only **18** are valid GTIN lengths | The strongest identity signal is unusable on dev and clean on qa (412/412). Anything tuned on dev tunes the no-barcode path only |
| `NAN_KEY` / `ITEM_CODE` carry the **same corruption** | NAN_KEY 65/412 dev, 67/412 qa; ITEM_CODE 162/412, 168/412 | They collide across different products — 11 dev NAN_KEYs span multiple modules. Row identity is `row_uid` (`"qa:117"`), never these. The apparent 40-row dev/qa overlap is entirely an artifact — the sets are disjoint |
| **No URL ground truth anywhere** — `dev` has MODULE (412/412) and characteristics, nothing for URLs | — | URL selection can only be scored indirectly, or against a gold set we label by hand |
| Closed characteristic values use **`&` as a combinator** | 187 of dev's ground-truth values are `&`-joined (e.g. `ANTI BACTERIAL & FRESHENING & WHITENING`) | Validation is per component, not whole-string — whole-string would reject the organizers' own answers |
| `RETAILER` has no reliable mechanical parse | a regex fails on 21 of 50 values, one *silently* (`"BOOTS (GB) (HOMESCAN)"` → `"(HOMESCAN)"`) | A hand-reviewed 50-entry table (`config/retailers.yaml`), not a cleverer pattern |
| Encoding corruption | `JASÃƒâ€“N` (double-encoded `JASÖN`), 23 non-ASCII descriptions, a `U+2011` hyphen in a sample URL | `ftfy` repair on load with a flag; explicit dash folding in URL canonicalization (NFKC alone does not fold it — measured) |
| Modules are long-tailed; dev covers 27 of 59 | top 4 modules = 77% of dev | Macro accuracy is the headline for classification; 32 modules are unreachable by any model trained on dev |
| Organizer data errors | `GLASS` packaging on a gum/tablet module (allowed: cardboard/paper/plastic), 2 rows | Logged as a question, not designed around |
| The sample output's `PRODUCT_URL` holds page **titles**, and resolves a `FR,GB` item to Amazon.in | 6 sample rows | Both kept open as questions; the output field is a config switch, and market is scored, never filtered |

---

## 3. The shape of the answer, and what was rejected

### 3.1 A deterministic pipeline, not an agent

`docs/03-architecture.md` §1. Four reasons, all from the brief's criteria:

- **Scoreability** — 412 rows with no URL ground truth cannot afford a
  different trajectory per run.
- **Debuggability** — when row 217 picks the wrong URL we need to see which
  *feature* misfired; a pipeline gives a per-stage trace, an agent a
  transcript.
- **Cost** — deterministic pre-filtering cuts model calls by roughly an order
  of magnitude; the whole 412-row run with adjudication is ~560 calls.
- **Transparency is scored** — feature-level evidence is transparent;
  chain-of-thought is not.

Where the model *is* used: adjudicating the top candidates when the
deterministic scorer cannot separate them, and extracting characteristic
values from page evidence. Each is a typed function with a schema-validated
output. The reasoning text is **composed** from the typed record, never
generated (§4.13).

### 3.2 The eight stages

```
record → [0] normalize → [1] registry lookup (Tier 0/1) ──hit──┐
                              │ miss                            │
              [2] retrieve → [3] fetch & extract → [4] match   │  (Tier 2, Tier 3)
                              │                                 │
                              ▼◄────────────────────────────────┘
              [5] classify module → [6] characteristics → [7] reason → [8] assemble
```

Every stage writes one artifact per row to disk, keyed by `row_uid`; stages
are independently re-runnable; a change to stage 6 never forces a re-crawl.

### 3.3 A memory: the Canonical Entity Registry and the compute cascade

The same physical product recurs across retailers and re-audits. A pipeline
with no memory pays the full retrieval + matching + model cost every time.
NIMO keeps a persistent registry of resolved products (`data/registry/`,
committed, audit-logged) and every row falls only as far as it must:

| Tier | Trigger | Cost |
|---|---|---|
| 0 — exact | clean barcode already resolved | a hash lookup |
| 1 — near | same brand/size/count block, variant-text similarity ≥ τ | a few dot products |
| 2 — retrieval | miss | search + fetch + match |
| 3 — adjudication | Tier 2 ambiguous | one model call |

Measured facts that shaped it: a content fingerprint (`brand + size + count`)
blocks **136 of 220 sized qa rows (62%)** against a dev row — but the block
is *not* a match: of 379 blocked dev pairs roughly 4 are the same product
(Sensodyne alone has 14 SKUs in one 75 ml block). So the fingerprint blocks
and the variant text discriminates, with a threshold derived from 20
hand-adjudicated pairs (`τ_ann = 0.75`, precision-first, 3/4 true positives,
0/14 true negatives). Tier 0 fires **0/412 on a first pass** over this dataset
(no shared barcodes) and **412/412 on a re-run** — its value is warm start,
and that is how it is demonstrated.

**Rejected:** a GNN (no multi-hop structure, 412 rows cannot train one),
hyperbolic embeddings (the taxonomy is a 3-level lookup table), a ReAct agent
(unscoreable), pure-LLM ranking of raw HTML (discards the hard signals that
decide identity), embedding-only matching (cannot represent "2-pack ≠
single"), a country hard-filter (contradicts the organizers' own sample).
The merge structure a GNN gestures at is met by Union-Find: deterministic,
no training, effectively linear.

---

## 4. Every stage — what, why, what it bought

Phases P0–P18 in `docs/04-build-standards.md` §1. Each has a spec in
`specs/`, a module in `src/nimo/`, a mirrored test directory, and a gate that
was measured before the row said "done".

### 4.1 Contracts (P1) — `src/nimo/contracts.py`

Twenty-one pydantic models, zero logic, every one round-trips through JSON.
**Why:** every value that crosses a module boundary is typed, so schema
drift is a type error rather than a day of debugging; `mypy --strict` is a
gate. Two `dict[str, Any]` fields exist (JSON-LD and OpenGraph — third-party
markup we do not control) and are the only `Any` in the contracts, chosen
after measuring that `dict[str, object]` pushes casts into every reader.

### 4.2 Loader (P2) — `src/nimo/loader/`

Reads the workbook with every identifier as **text**, asserts the dataset's
fingerprint on every load (the 377/412 corruption count — if the file
changes, we stop rather than run on stale assumptions), nulls a rounded
barcode instead of passing it through (a rounded `5000000000000` would
merge unrelated products in the registry), repairs encoding with `ftfy` and
flags it, parses retailer names through the hand-reviewed table, and mints
`row_uid`. **What it bought:** the corruption found in three columns was
caught at the loader, not in the registry; the same bug (keying on
`NAN_KEY`) was introduced twice later and caught both times by tests.

### 4.3 Normalizer (P3) — `src/nimo/normalize/`

`RETAILER_DESC` → brand, size (ml *or* g, never converted — toothpaste is
not water), multipack count, variant terms, format hints, and an audit
trail of what was stripped. Designed from measurements over all 824 rows:
retailer-suffix stripping is data-driven (824/824 rows end in a token from
their own retailer string), variant terms are derived not curated (1,725
distinct residual tokens), count parsing has explicit precedence (`pack of
N` dominates; `N count` last because `"1 count (pack of 4)"` means four),
and `N x` is guarded against marketing claims (`"3x more effective"` is not a
3-pack). **What it bought:** the module classifier scores **3.2 points
better on `desc_clean` than on the raw text** on identical features — the
first downstream evidence the normalizer does real work.

### 4.4 Module classifier (P5) — `src/nimo/classify/`

Character-4-gram TF-IDF nearest centroid over `desc_clean`. Hand-written
(no scikit-learn — a hundred lines of arithmetic, unit-tested against
hand-computed vectors). **Measured, leave-one-out over all 412 dev rows:
80.3% overall, 49.7% macro** over 27 modules.

Why each choice, measured: character n-grams beat word tokens by **+8
points** because the data writes one product as `toothpaste`, `tooth
paste`, `t/paste`, `pste`; the centroid beat Naive Bayes on **macro** (NB
was within 2 points overall and 11 worse on macro by collapsing the tail —
overall alone would have picked the wrong model); **BRAND is excluded**
(including it costs 7.5 points: ORAL-B makes brushes, heads and paste, so
the brand pulls every product toward its dominant module). Every prediction
cites the nearest labelled dev row — a citation a human can check, which is
what "transparent reasoning" needs from a classifier whose features are
strings like `othp`.

Two things measured and **rejected**: routing to the 32 modules absent from
dev by matching module names (resolves the family, guesses the form —
destroys 6 correct answers to gain 4); and adding page evidence (title,
JSON-LD name, breadcrumbs) to the classifier — **every variant loses**, even
on the 329 rows whose page is ~97% likely right, because a title carries the
retailer's category vocabulary. Consequence: `MODULE` ships from text, and
the URL pipeline's value is the characteristics.

### 4.5 Registry (P6) — `src/nimo/registry/`

Blocking (a row gets **both** a GTIN key and a fingerprint key — an
either/or rule was measured to make Tier 1 unreachable for all 412 qa rows),
Tier 0/1 lookup, a deterministic Union-Find (representative = smallest
member, so a re-run is byte-identical), a JSONL store, and an append-only
audit log of every write. `entity_id` is a hash of the block key, never a
uuid, so the registry warm-starts across runs. **Current state: 112
entities**, every one a GTIN-confirmed product.

### 4.6 Batch runner (P6a) — `src/nimo/run/`

One choke point for failure: the runner is the **only `except Exception` in
`src/`**, a test greps the tree to keep it that way, and a failure becomes a
typed `RowFailure` with the stage that raised. A failed row leaves **no**
artifacts (never a partial output row). Artifacts are one file per row per
stage, written atomically (temp file + rename), so a kill mid-run resumes
cleanly: **412 dev rows in 3.6 s cold, 0.1 s and zero work on resume.** A
`RunSummary` prints tiers, failures by stage, model calls and tokens, cache
hits, wall time and a config hash. The pipeline is composed **once**
(`run/compose.py`); the CLI, the demo and the UI all call it.

### 4.7 Retrieval (P7) — `src/nimo/retrieval/`

Self-hosted SearxNG (Docker, pinned by image digest — a tag was once
invented and caught), five query strategies, URL canonicalization, merge,
cap. What it took to make **free** search engines carry a 412-row run, each
step measured:

- **Engines chosen by measurement, with tags verified**: `google cse` 87%
  relevant, `duckduckgo` 82%, `brave` 95% when not suspended. Bing was
  removed for answering a *different query* while reporting healthy
  (`"aquafresh whitening pump"` → a Bluetooth support article); `startpage`
  was found never to exist — SearxNG silently falls back to defaults on an
  unknown engine name, and the client now **refuses results from any engine
  it did not ask for**.
- **A per-engine circuit breaker** (3 failures → 15 min), **rotation** (one
  engine per query, next engine on an empty answer), **early exit** once the
  fetch budget is filled, **wait-for-cooldown** for unattended runs, and a
  **cache keyed by query + engine** with a 14-day TTL.
- **Strategy order from measurement**: S2 (barcode + brand) first — it found
  every page the bare barcode found and attached the brand — bare barcode
  last (on an engine that matches digit strings it returned pages about
  phone prefixes and the digits of pi).
- **Candidate quality, not quantity**: a count of candidates was satisfied
  equally by 20 product pages and 20 support articles; `brand_signal_rate`
  replaced it.

**Result:** the full qa run on free engines, **412/412 rows, 0 failures,
107 minutes, zero cooldown waits** — after an earlier measurement of "8 rows
per cooldown window (~13 hours)" that the re-engineering replaced. Product-
level retrieval quality, the honest replacement for an unmeasurable gold
gate: **111 of 412 qa rows fetched a page publishing the record's GTIN**;
given any GTIN-publishing page was fetched, the right product was among
them **72%** of the time. 149 hosts served bot walls.

**Found today (2026-09-12) through P18 and fixed:** a barcode no engine
indexes makes S2 return the brand's *homepage* and category pages — eight
safe URLs, none a product — and early exit stopped the cascade before S3
ran. **94 of 412 qa selections (23%) were brand homepages.** Now a URL whose
shape says "about, not of" (site root, listing, directory) never fills the
early-exit budget and is fetched last; qa and dev are being re-harvested
under the rule (§8).

### 4.8 Fetch and extract (P8) — `src/nimo/fetch/`, `src/nimo/extract/`

Measured first, on ten real UK oral-care pages: JSON-LD `Product` on **3 of
10**, OpenGraph on 4, bot walls on 2, JS shells on 2, body text on all 10;
**Amazon publishes neither JSON-LD nor OpenGraph**. So the extraction
cascade is JSON-LD → microdata → OpenGraph → body text, handling `@graph`
nesting, `@type` lists and one malformed block among valid ones (all real
markup). Two retailers were found to agree on a GTIN for the same product —
the evidence that URL correctness should be scored per *product*, not per
URL string.

The fetcher: one HTTP client, connect and read timeouts, per-domain rate
limit, `robots.txt` once per host (unreachable = allowed, per RFC 9309),
retries on 5xx/timeout only (a 403 is recorded as `blocked`, never retried —
that is rudeness for an answer that will not change), a streamed size cap,
a content-addressed cache with a 30-day TTL for pages and 12 hours for
failures, and **redirects followed by hand** so the SSRF guard re-validates
every hop (tested with a 302 to the cloud metadata address). The
User-Agent must identify the project; config load refuses one that does not.

### 4.9 Matcher (P9) — `src/nimo/match/`

The core. Hard rules first, in the architecture's order: page GTIN equals
the record's barcode (both valid) → accept, 1.0, stop; differs → reject;
size mismatch, count mismatch, negative flags (`refill`, `travel`, `sample`,
`bundle`…) → demotion, never rejection (retailer pages list ranges; with 4
of 10 pages bot-walled a demoted page sometimes has to win). Then five
weighted features from config (brand, variant overlap, format, retailer
domain, market), summing to 1.0 by assertion, explicitly untuned — fitting
them to five gold URLs would produce numbers that look measured and are
not. The same normalizer parses the page title, so both sides of every
comparison are in one shape.

URL-shape flags, each added from a measurement over real selections: search
**listings** (2 of the first 5 live rows were Amazon search pages),
**barcode directories** (70 of 412 qa selections were `grocefully.com`,
`buycott.com`, `prodlookup.co.uk` — they publish the GTIN, which is why the
scorer likes them; demoted so a retailer page wins when one exists),
**non-commerce hosts** (Wikipedia, Instagram), and **site roots** (94 of 412,
today). Among equal scores: identifier first, page type second, URL third.

"Both valid" is load-bearing: comparing a rounded dev barcode against a
page's real GTIN would reject every correct candidate. The five adversarial
cases the standards name — same brand different size, different multipack
count, refill vs complete, conflicting GTIN, no structured data — each pass
as a named test, and they *are* the gate, because zero of the six gold rows
have a usable GTIN.

### 4.10 Calibration and abstention (P10) — `src/nimo/calibrate/`

Raw scores are not probabilities. The gold set was too small to fit on, so
the instrument is the GTIN rule itself: every qa row has a clean barcode, so
any fetched page that publishes a GTIN is labelled for free — equal means
*this is the product*. The **pre-hard-rule weighted score** is paired with
that label (so the oracle cannot leak into the number it labels) and a
hand-written isotonic (pool-adjacent-violators) fit produces the curve —
refused below 30 pairs, refused on single-class input. **Committed curve:
236 labelled pairs, held-out ECE 0.068** (5-fold, grouped by row). The
selection bias is printed in every report: pairs come only from pages that
publish a GTIN, the well-behaved end of the web.

Abstention (`tau_abstain`) is wired and **off**: whether a wrong URL is
penalised more than a blank one is an open organizer question (Q3); the
report prints the trade-off table so it can be turned on in one config line.

### 4.11 The model client and adjudication (P11) — `src/nimo/llm/`, `src/nimo/match/adjudicate.py`

One shared client for every model call: prompts in `config/prompts/*.md`
(never inline), untrusted page text inside a delimited block that cannot
close its own delimiter, a cache keyed by `sha256(model + system + user +
temperature + max_tokens + image hashes)`, a per-run token budget that
**aborts** on breach, schema validation with one retry, transient-error
retry with jitter. The Azure adapter is ~30 lines and the only importer of
the SDK.

Tier 3 adjudication, when the scorer's top candidates are within a
threshold: the model sees the structured evidence of the top-k (never raw
HTML) and answers with an **index into the pack, never a URL** — the answer
schema has no URL field, so an injected "choose candidate 9" is a typed
rejection. A GTIN accept is never adjudicated; write-back ignores the model;
a rejected verdict keeps the deterministic pick. Four injection fixtures
pin this.

What the first live calls taught us about the pinned model
(`hack-fest-gpt-5.6-luna`): it **rejects `temperature=0`** (parameter now
omitted; determinism rests on the response cache); it is a **reasoning
model** that bills hidden reasoning inside the output cap (a 64-token ping
came back empty — cap raised to 4096, a cap hit is a typed `LlmTruncated`,
reasoning tokens are logged: 0–270 per call); transient gateway errors
happened on 3 rows in 412 (retry added). Measured cost: **559 calls, 1.02M
tokens for 412 rows with adjudication**, 61 minutes. The adjudication delta
over the deterministic scorer is **not yet measured** — the office A/B ran
with 94% of page fetches failing, i.e. without evidence.

### 4.12 Characteristics (P12) — `src/nimo/characteristics/`

The stage that carries most of the score. In order, and the order is not
negotiable: (1) the **applicability gate** from `char_value_list` — non-
applicable characteristics are never sent to the model and are written
empty; measured under the classifier's held-out predictions it gets the null
pattern exactly right on **359/412 dev rows (87%)**, precision 0.955, recall
0.928 — a wrong module is usually a sibling that shares most
characteristics. (2) **One model call per row** carrying only the applicable
guidelines (1–9 per module, median 2; thirteen calls per row would not fit
the budget). (3) **Per-`&`-component validation** against the closed
vocabularies — reproducing the organizers' own dev counts exactly (1,719
accepted, the 2 `GLASS` rows rejected, 187 `&`-joined), pinned. A rejected
value gets one retry with the allowed set, then empty, recorded. (4) The
page text the model sees is not a prefix but **windows around anchor
terms** (`fluorid`, `ppm`, `flavour`, `bristle`…) — a real prompt showed the
first 3,000 characters of a Shopify page are entirely navigation.

**First measurement (office, 2026-09-12): 68.6% (354/516 cells) over the 92
dev rows that ran** — effectively record-only, since the office network
failed the page fetches. The three worst characteristics were a
guideline-vs-practice divergence: the guideline says WITHOUT fluoride is the
default, the coders' practice is WITH (123/148); FLAVOUR is `NOT STATED`
rather than blank; ORAL_CARE_FUNCTION carries 2–3 components on 65% of
truths. **Practice defaults** — value plus the dev measurement, refused
without one — now ride beside the untouched guideline text.

**Image evidence**: the organizer confirmed the model accepts images. When
a visual characteristic applies (packaging, material, bristle strength, head
size, dispense method — the weakest ones in the first measurement, 59–77%),
the selected page's pack shot is fetched through the same guard and cache
and attached as base64 to the one characteristics call. Harvested: **636 of
824 rows have a pack shot** (77% — the ceiling image evidence can reach).
The gateway's acceptance of image content is verified on the office network
by `python -m nimo.llm --ping-image`; a one-line switch turns it off.

### 4.13 Reasoning (P13) — `src/nimo/reason/`

The `REASONING` cell is **composed from the row's typed record by a
deterministic composer, not generated by the model.** Every sentence comes
from a named field and carries a provenance tag. The organizers' sample
reasonings are citations (EAN, pack size, fluoride ppm, which codes those
support, which claims are absent) — a composition over evidence, which is
exactly what the composer produces, and it is honest where the pipeline is
weak ("ranked first on a score of 0.10"). The anti-hallucination test is
therefore exact rather than a hope about a prompt: evidence lacking fluoride
⇒ nothing is asserted about fluoride; every number in the text is a field's
string form; page text is never quoted. It also closes the one exposed
free-text injection surface: page text reaches the reasoning only through
validated fields. Runs off-network, byte-identical on re-run.

### 4.14 Assembly (P14) — `src/nimo/assemble/`

One validated `OutputRow` per sheet row, in the exact qa header order,
asserted against the live workbook header. Passthrough columns are the
**workbook's own bytes** (the repaired `RawRow` values would alter the
organizers' data), a failed row is **blank in every output column** (a
half-filled row is worse than a blank one), identifier columns are text
cells so the rounding defect is not re-created on the way out, and every
module and characteristic value is re-validated on assembly — a violation
raises. The `.xlsx` is **byte-identical on re-run**, which took two rounds
of pinning: openpyxl stamps zip entry times *and* re-stamps
`dcterms:modified` inside `save()`; both are rewritten in a deterministic
repack. Verified byte-identical across two different laptops.

### 4.15 Demo, UI, explorer, own files (P15–P18)

All four are **renderers over the artifacts; none computes a new fact.**

- **Demo** (`python -m nimo.demo`) — ten rows, every stage's record, an HTML
  page; prints the warm-start caveat every time.
- **UI** (`python -m nimo.ui --live`) — a local web page over the same
  composed pipeline: run any row, run it again to watch Tier 0 fire, type a
  product of your own (its barcode goes through the loader's parsers, so a
  rounded one is nulled exactly as a sheet's would be).
- **Results explorer** (`python -m nimo.site`) — one self-contained HTML file
  over a whole run: every row's card, search, filters by tier/module/
  identity, failures, the registry, the run's numbers. This is what
  evaluators open. It is a **file, not a hosted site**, for two reasons: no
  free host can *run* NIMO (the model endpoint is NIQ-internal, retrieval is
  a container), and the rows are NIQ's data, which a public host would
  publish. It renders identically from a local path or a server.
- **Bring your own product list** (`--input FILE` on run/assemble/site) —
  any `.xlsx`/`.csv` with `RETAILER_DESC` + `BRAND` (barcode, retailer,
  country optional) through the same parsers, keyed by the file's name so it
  can never masquerade as `qa`, producing the same 23-column output and its
  own explorer page. Its live check is what found the site-root defect.

---

## 5. Security, safety and the failures that do not throw

`docs/05-security-safety.md`. Not user-facing security — there is no user —
but the two surfaces this design genuinely exposes, plus the class ordinary
error handling misses.

- **Fetched content is data, never instructions.** Every page text, title
  and JSON-LD goes into a labelled, delimited block that cannot close its
  own delimiter. Defence in depth: `MODULE` and closed characteristics are
  validated against fixed vocabularies, the URL can only be an index into a
  pack fixed before the model saw anything, and nothing downstream reads
  `REASONING` back into a prompt. A successful injection produces one odd
  row, not a cascade. Injection fixtures are a permanent regression suite.
- **SSRF.** Non-http(s) schemes refused; hostnames resolved and *every*
  returned address checked against loopback, link-local (cloud metadata),
  and private ranges; re-validated after every redirect hop; hard timeouts
  and a streamed size cap. Deliberately scoped to untrusted candidate URLs —
  the model endpoint is itself a private address.
- **Model calls.** Version pinned exactly (never `latest`); no secret or
  config interpolated into a prompt; hard per-run token budget that aborts;
  images framed as untrusted data with the same schema validation.
- **Registry integrity.** Write-back on a GTIN accept only (a wrong merge
  poisons every future row that blocks against it); every write audit-logged
  with `row_uid`s, append-only.
- **Latent-failure taxonomy** — the defining property is that no exception
  is thrown: registry poisoning, calibration decay, cache staleness (TTLs,
  never infinite), silent input schema drift (the fingerprint assertion),
  model drift (pinning), aggregate domain block (per-domain outcome counts),
  type coercion across serialization boundaries (the barcode defect is the
  canonical instance — assert on load and on write), a parsing rule matching
  the wrong substring (the BOOTS/HOMESCAN instance), config/prompt version
  skew (a config hash and prompt hash per row).

**No credentials anywhere in the repo.** The model key and the SearxNG
secret live only in a gitignored `.env`, copied by hand. Fixture HTML was
scrubbed shape-wise — the first pass left 45 copies of a live session id in
data attributes; the second pass found them.

---

## 6. How it was built — the standards that made the numbers trustworthy

`docs/04-build-standards.md`. The gate before any commit:
`ruff check`, `ruff format --check`, `mypy --strict`, `pytest` — currently
**819 tests, zero network calls in any of them** (every network seam is an
injected callable; HTTP is tested through mock transports with stubbed DNS).

- **Fail loud.** No bare except, no masking default (`size = parsed or
  100.0` is forbidden), no partial output row.
- **Zero magic numbers.** Every weight, threshold, TTL and limit is a named
  config value in `config/*.yaml`, several carrying the measurement that set
  them in a comment.
- **Determinism.** No wall clock in logic (clocks and sleeps are injected),
  sort before serializing, response cache keyed by everything that affects
  an answer, a twice-run byte-identical acceptance test.
- **Specs before code.** Every module has `specs/<module>.md` with
  acceptance criteria and a Definition of Done; the row in `04` §1 says what
  was measured and what was not.
- **A decision log** (`docs/02-decision-log.md`, ~50 entries) records every
  design decision with what was rejected and why — including the project's
  own mistakes: an invented Docker tag, a "startpage" engine that never
  existed, a Tier 1 that could not fire in the real pipeline while its tests
  passed, a candidate count that reported success on junk. The recurring
  lesson, written down each time: **a test or a script that constructs its
  inputs differently from production verifies the function, not the
  wiring.** Later tests go through persistence and assert call signatures
  because of it.
- **Verify before deciding.** Tool behaviour was reproduced (real `uv`,
  `mypy`, pydantic, the SDK) rather than reasoned about from memory; three
  build-tooling defects and the `dict[str, Any]` decision were settled that
  way.

---

## 7. Running it

Two machines, because two things live in two places: the internet (home)
and the model (the NIQ network).

**At home** — Docker for SearxNG, ordinary internet:

```bash
uv sync && cp .env.example .env            # SEARXNG_SECRET; the model key only on the NIQ network
docker compose up -d searxng
uv run python -m nimo.run --sheet qa --live   # retrieve, fetch, match, classify, gate-only characteristics, reason
uv run python -m nimo.calibrate               # refit the curve from the harvest
uv run python -m nimo.assemble --sheet qa     # submission_qa.xlsx + .csv + report
```

**At the office** — `docs/06-office-runbook.md`. The office network fails
94% of retailer-page fetches (a proxy) and **Docker cannot start on the
laptop** (virtualization disabled), so the run there uses only the caches
plus the model: carry `data/cache/{search,pages,llm,images}` (~480 MB zip),
`.env`, `git pull`; then

```bash
uv run python -m nimo.llm --ping && uv run python -m nimo.llm --ping-image
uv run python -m nimo.run --sheet dev --live --characteristics --out-dir data/out/office2-dev
uv run python -m nimo.characteristics --evaluate data/out/office2-dev/artifacts/dev   # the P12 number
uv run python -m nimo.run --sheet qa --live --characteristics --out-dir data/out/office2
uv run python -m nimo.assemble --sheet qa --out-dir data/out/office2
uv run python -m nimo.site --sheet qa --out-dir data/out/office2                       # the explorer file
```

A query or page missing from the cache fails its row loudly; nothing is
searched or fetched silently. Search entries expire 14 days after harvest,
pages 30 days.

**For evaluators** — `docs/07-judges-guide.md`: open `site_qa.html` (no
install, no server), or run the UI live, or reproduce end to end.

---

## 8. Results so far — measured, and what is not

| What | Number | Status |
|---|---|---|
| Module classification, leave-one-out over 412 dev rows | **80.3% overall, 49.7% macro** | measured |
| Applicability gate under predicted modules | **precision 0.955, recall 0.928**, exact null pattern 87.1% | measured |
| Closed-value validator against dev ground truth | 1,719 accepted / 2 rejected (the GLASS rows) / 187 `&`-joined | measured, pinned |
| Full qa run on free engines | **412/412, 0 failures, 107 min** | measured |
| Product-level retrieval | 111/412 rows fetched the record's GTIN page; 72% given any GTIN page | measured |
| Registry | 112 GTIN-confirmed entities; Tier 0 412/412 on a re-run | measured |
| Calibration | 236 pairs, **held-out ECE 0.068** | measured |
| Model cost, 412 qa rows with adjudication | 559 calls, 1.02M tokens, 61 min | measured (office) |
| Characteristic accuracy | **68.6% over 92 dev rows, record-only** (no page evidence at the office) | first measurement; re-run pending with the page cache and practice defaults |
| Adjudication delta over the deterministic scorer | — | **not measured** (office A/B ran without evidence) |
| Image evidence at the gateway | — | **not verified** until `--ping-image` runs on the network |
| Brand-homepage selections in qa | 94/412 before today's fix | re-harvest in progress |
| Byte-identical output | across two laptops | measured |

**In progress (2026-09-12):** the qa and dev artifact trees are being
re-harvested at home under the site-root rule; the calibration curve is then
refitted and the cache zip rebuilt; the second office run produces the
deliverable.

---

## 9. Limits, stated

- **Six of ~50 gold URLs are labelled.** Partial by design: a fabricated URL
  miscalibrates the scorer undetectably. URL correctness is therefore
  measured at the product level through the GTIN rule, not against gold.
- **32 of 59 modules cannot be predicted** by anything trained on dev; two
  qa rows need one of them. Two fixes were measured and rejected; the lever
  is recorded for a stage with page evidence.
- **The dev/qa asymmetry**: dev has 18 usable barcodes, qa 412. Anything
  measured on dev measures the no-barcode path.
- **JSON-LD availability is ~30%**; Amazon, the largest retailer, publishes
  none. The GTIN rule cannot fire on the other 70% of pages.
- **Roughly half of large UK retail bot-walls a polite fetcher** (149 hosts
  in the full run).
- **The pinned model is non-deterministic on a cold cache**; byte-identical
  re-runs rest on the response cache, which travels with the registry.
- **The office laptop can neither fetch pages nor run Docker.** Everything
  the office run needs is pre-harvested; a live demo on a new product runs
  from a non-office machine.

---

## 10. Open questions for the organizers

From the decision log's table: Q1 uncorrupted `EXTERNAL_CODE`/`NAN_KEY`/
`ITEM_CODE` (three columns damaged by one cell format); Q2 is `PRODUCT_URL` a
URL or a page title (the sample has titles); Q3 how is URL selection scored,
and is a wrong URL worse than a blank one (decides abstention); Q4 is cross-
market resolution acceptable (the sample resolves a GB item to Amazon.in);
Q5 the sample's 14th characteristic; Q6 scraping policy and the office
network/laptop constraints (§7); Q7 model context window and rate limits
(multimodal confirmed); Q8 the `GLASS` data error; Q9 encoding-corrupt cells.
Each provisional point is implemented behind a config switch so an answer
changes a value, not a module.

---

## 11. Where everything is

| | |
|---|---|
| `docs/00`–`05` | brief, dataset contract, decision log, architecture, build standards, security |
| `docs/06`–`08` | office runbook, judges' guide, portal submission |
| `specs/*.md` | one spec per module, with acceptance criteria and DoD |
| `config/*.yaml`, `config/prompts/*.md` | every threshold, weight, pattern and prompt |
| `src/nimo/` | the code, one package per stage; `contracts.py` at the root |
| `tests/` | mirrors `src/nimo/` exactly; fixtures are scrubbed real pages |
| `data/registry/` | the resolved-product memory and its audit log (committed) |
| `data/calibration/` | labelled pairs and the fitted curve (committed) |
| `data/gold/` | hand-labelled URLs and pairs, frozen sample |
| `data/cache/` | search, pages, model answers, images (gitignored; carried by zip) |
| `data/out/` | artifact trees, traces, submissions, explorer pages (gitignored) |
| `PROGRESS.md` | the live "you are here" for the next session |
