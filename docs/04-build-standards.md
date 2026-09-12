# 04 — Engineering Standards & Build Order

Version 0.7 — 2026-09-10. Binding on all implementation. If a rule here blocks
something the architecture requires, that is a decision-log entry, not a
judgement call at the keyboard.

Read §1 (Build order) to know *what* to build next. Read §2–§10 for *how*.
Read §11 before claiming any module is done.

---

## 1. Build order

Strictly sequential. Do not start a phase before the previous one's Definition
of Done (§11) passes. Each phase ends in a commit.

**The `Status` column is the coarse, phase-level progress marker** — which
phases are done, at a glance. It is not the mechanism for resuming mid-phase
work after an interruption; that's `PROGRESS.md`, §1a below. Update the
relevant row's status when a phase's gate passes, in the same commit as the
phase's final code. Values: `not started` | `in progress` | `done`.

| # | Phase | Deliverable | Gate | Status |
|---|---|---|---|---|
| P0 | Scaffold | Repo layout, deps, config, logging, CI | `make check` green on empty repo | done |
| P1 | Contracts | `contracts.py` — every model in `03` §3, no logic | Models instantiate; round-trip to JSON | done |
| P2 | Loader | Dataset ingest, all 7 acceptance criteria in `01` §10 | Corruption counts match `01` §3 exactly | done |
| P3 | Normalizer | `RETAILER_DESC` → `DescTokens` | 30 hand-written cases from real dev rows pass | done |
| P4 | **Gold set** | ~50 hand-labelled URLs, stratified by module | Committed as `data/gold/urls.jsonl` | done — infrastructure complete, **6 of 50 labelled** (5 correct, 1 ambiguous). Partial by design: `specs/gold.md` forbids inventing entries to reach the target, since a fabricated URL miscalibrates P9/P10 undetectably. Frozen sample in `data/gold/sample.txt` makes the remaining 44 resumable |
| P5 | Module baseline | Text-only module classifier, no URL — `src/nimo/classify/`, char-4-gram TF-IDF nearest centroid over P3's `desc_clean` | Per-module stratified accuracy reported for all 27 `dev` modules. **Gate wording corrected: the classifier reads `RETAILER_DESC` only, not `RETAILER_DESC` + `BRAND`** — including BRAND was measured to cost 7.5 points overall and 3.5 macro, because brand does not predict module (ORAL-B makes manual brushes, electric brushes, refill heads and toothpaste). `specs/classify.md` §3c | done — leave-one-out over all 412 `dev` rows: **80.3% overall (331/412), 49.7% macro**. Macro is the headline; overall alone would rate a head-only classifier at 76.9%. Reproduce with `uv run python -m nimo.classify` |
| P6 | **Registry & blocking** | `CanonicalEntity` store, exact-key blocking, Union-Find merge, audit log — `src/nimo/registry/` | Tier-1 block hit rate **and** within-block precision, on a content fingerprint. **Gate wording corrected: a row gets BOTH a GTIN key and a fingerprint key**, not one or the other — `qa` has a clean barcode on 412/412 rows, so the original either/or rule made Tier 1 unreachable for the whole evaluation set while Tier 0 missed all 412 (`specs/registry.md` §2) | done — **block hit rate 136/220 sized `qa` rows (61.8%)**, reproducing `01` §14's ceiling. **Within-block precision: ~4 of 379 blocked `dev` pairs are genuinely the same product**, the quantified form of "blocking key, not a match key". Tier-1 at `τ_ann=0.75`: 3/4 true positives, 0/14 true negatives on 20 hand-adjudicated pairs. **Tier 0 fires 0/412 in a single pass and 412/412 on a re-run** — its value is warm-start, not within-run |
| P6a | **Batch runner & orchestration** | `src/nimo/run/` — per-row stage driver, `RowFailure` capture at one choke point, `row_uid`-keyed artifact skip/resume, trace.jsonl, `RunSummary`, CLI | Runs all 412 dev rows; a deliberately failing row is recorded as a typed `RowFailure` and does **not** abort the run or emit a partial output row (`04` §4); killing mid-run and restarting resumes without redoing completed rows | done — **412/412 rows in 3.6s cold, 0.1s and zero work on resume**, 412 artifacts per stage, 412 trace records. Failure attribution tested per stage; the failed row leaves no artifacts at all. `test_only_one_broad_except_exists_in_src` pins the runner as the single sanctioned `except Exception` site in `src/` |
| P7 | SearxNG + retrieval | Self-hosted instance (pinned by digest), 5 query strategies, canonicalization, merge, engine rotation + per-engine circuit breaker + early exit at the fetch budget + wait-for-cooldown + cache-first + candidate-quality signal — `src/nimo/retrieval/` | Recall@20 measured on gold set | **the full `qa` run completed on free engines: 412/412 rows, 0 failures, 107 minutes, zero cooldown waits** (2026-09-11; google cse and brave each circuit-broke 7 times and duckduckgo carried those windows). The Recall@20-on-gold gate stays open as written — 5 gold URLs cannot measure it — and is replaced by the product-level number the GTIN rule gives on `qa`: **111/412 rows (26.9%) fetched a page publishing the record's GTIN**; only 154 rows fetched any GTIN-publishing page, so the instrument's ceiling is JSON-LD availability (30% of retailer pages, `specs/fetch.md`), and given such a page was fetched the right product was among them 72% (111/154). Earlier figures — "20 candidates/row" and "8 rows per window" — are both superseded (`specs/retrieval.md` §5a.5b, §5a.7). **2026-09-12: about-shaped candidates (site roots, listings, directories) no longer fill the early-exit budget and are fetched last (`specs/retrieval.md` §5a.8) — S2 had been answering with brand homepages on rows whose barcode no engine indexes, and those stopped the cascade before S3; 94 of 412 qa selections were homepages. qa re-harvested under the rule** |
| P8 | Fetch + extract | Cached fetcher, JSON-LD-first extractor — `src/nimo/fetch/`, `src/nimo/extract/` | Frozen HTML fixtures for 10 retailers | **done.** 10 real retailers captured and scrubbed; extraction cascade, SSRF guard, robots.txt, per-domain rate limiting, content-addressed cache with separate failure TTL, and **manual per-hop redirect re-validation** (`05` §2) — 72 tests, zero network. Verified end to end: chemist-4-u fetched with GTIN `5011309895612` extracted, Tesco's 403 recorded without retry, both served from cache on the second pass. Key measurement: **JSON-LD Product on only 3 of 10 pages**, Amazon has neither JSON-LD nor OpenGraph, 4 of 10 are bot walls (`specs/fetch.md` §1) |
| P9 | Matcher | Layer A features + hard rules + registry write-back — `src/nimo/match/` | Precision@1 on gold set | **done — with the gate's limits stated.** The five adversarial cases `04` §8 names all pass, and that is the real gate for the hard rules, because **zero of the six gold rows have a usable GTIN** — Precision@1 on the gold set can never exercise the rule that carries all 412 `qa` rows. Weighted path, live, end to end: **URL@1 = 1/5, n=5, and unstable between runs** because free-engine availability changes the candidate list (`specs/match.md` §1). Write-back fires on GTIN accept only; `calibrated_prob` mirrors `raw_score` and a test forces P10 to break that deliberately. 25 tests. **2026-09-12: `site_root` URL-shape flag (`specs/match.md` §2a) — 94 of 412 qa selections were a brand's homepage, demoted like a listing; paired with the retrieval change above** |
| P10 | Calibration + abstention | Isotonic fit (hand-written PAV), harvest, reliability report, persisted curve, `tau_abstain` — `src/nimo/calibrate/` | Calibration curve reported | **curve FITTED and reported.** Interim, on the running `qa` harvest: **93 labelled pairs from 195 rows (73 correct, 20 not), ECE 0.051**; raw text score ≥ 0.60 → 97.6% correct, 0.28-0.45 → 45%. `data/calibration/curve.json` is committed and loaded by `--live` (`calibrated_prob` follows it; a GTIN accept bypasses it). Selection bias stated in every report: pairs come only from GTIN-publishing pages. Abstention stays OFF (`tau_abstain: 0.0`, `[PROVISIONAL — Q3]`), wired and tested; the abstention trade-off table is what turning it on buys (tau 0.5: precision 0.78 → 0.91 on 69/92 selected). **Refit on the full 412-row harvest when it completes** — the yield was 1 in 8 rows with S1 first and is ~1 in 2 with S2 first |
| P11 | LLM adjudication | Top-k tiebreak, schema-constrained — `src/nimo/llm/` (shared client: cache, budget abort, JSON validation with one retry, prompt files, untrusted-content delimiting) + `src/nimo/match/adjudicate.py` | Measurable delta over P9 alone | **built and fixture-tested; delta NOT measured — needs the NIQ network.** The endpoint is RFC1918-only (`config/models.yaml`), so the gate procedure in `specs/adjudicate.md` §8 has not run; the Azure adapter (~30 lines, one file) is the only unverified code. Structural defences pinned by 53 tests, zero network: the answer schema has no URL field, an index outside the pack is refused, page text cannot close its delimiter, a GTIN accept is never adjudicated, write-back ignores the model, budget breach aborts the run. `05` §1's injection fixture class is in `tests/match/test_adjudicate.py`. **Executed on the NIQ network 2026-09-12:** the adapter works (after two measured fixes — the model rejects `temperature=0`, and it reasons before it writes so a 64-token cap came back empty); 60 of 412 `qa` rows were adjudicated, 0 verdicts rejected. **Delta still NOT measured:** the office network served error pages for 94% of fetches, so the A/B ran without evidence; measure on the second trip with the page cache (`specs/adjudicate.md` §8) |
| P12 | Characteristics | Applicability gate + per-char extraction — `src/nimo/characteristics/` (gate, per-`&`-component validator, one-call-per-row extractor through `nimo.llm`, evaluation), runner stage 7, write-back moved after it so entities carry module + values | Per-characteristic accuracy on dev | **built and fixture-tested; validator and applicability MEASURED on dev; per-characteristic accuracy NOT measured — needs the NIQ network.** Validator against dev's own ground truth: **1,719 closed values accepted, exactly the 2 `GLASS` rows rejected, 187 `&`-joined values** — `01` §11's counts, pinned. Applicability under P5's held-out module predictions: **precision 0.955, recall 0.928, exact null pattern on 359/412 rows (87.1%)** — the ceiling a wrong module imposes. Gate-only mode keeps the artifact tree complete off-network. 28 tests incl. `05` §1 injection fixtures; 683 pass. **First measurement 2026-09-12 (office): model view 68.6% (354/516) over the 92 `dev` rows that ran — effectively record-only, since the office network failed 94% of page fetches.** Worst three were the guideline-vs-practice divergence (FLUORIDE 22.6%, ORAL_CARE_FUNCTION 28.6%, FLAVOUR 31.6%), fixed by measured practice defaults (`specs/characteristics.md` §2a). Also found and fixed: 111 registry-hit rows in the submission carried NO values (gate-only rebuild + hit path), and 3 rows failed on transient gateway errors with no retry. The gate re-runs on the second trip with the page cache |
| P13 | Reasoning | Grounded synthesis — `src/nimo/reason/`, a deterministic composer over the row's typed record (identity, module, characteristics, evidence used), each clause tagged with the field it came from; runner stage 8 | Groundedness fixture tests pass | **done.** Composed, not generated (`specs/reason.md` §0): `03` §4 stage 7's anti-hallucination rule holds by construction, and the fluoride fixture, a numeric-provenance check (every number in the text is a field's string form), a coded-value check and a body-text-never-quoted check all pass. Registry hits, GTIN accepts, weighted wins, Tier 3 verdicts and abstentions each have their own sentence shape. Byte-identical on re-run, `max_chars`-bounded by dropping whole sentences. Runs off-network. 17 tests; 704 pass |
| P14 | Assembly | qa-schema output + trace — `src/nimo/assemble/`: one validated `OutputRow` per sheet row from the eight artifact trees, passthrough columns from the workbook's own bytes, blank output columns for a failed row, `submission_<sheet>.csv` + `.xlsx` + a report | Byte-identical on re-run | **done.** Measured: both files byte-identical across two writes — after two rounds of pinning, because openpyxl stamps the zip entry mtime AND re-stamps `dcterms:modified` inside `save()` regardless of the property set; both are rewritten in a deterministic repack. `EXTERNAL_CODE`/`NAN_KEY`/`ITEM_CODE` are text cells (`@`) read back through openpyxl. Header asserted equal to the live `qa` header; MODULE and every characteristic re-validated on assembly and a violation raises. `[PROVISIONAL — Q2]` `PRODUCT_URL` is a config switch. 13 tests over a tree the real offline runner built; 717 pass |
| P15 | Demo | Prototype UI/CLI walkthrough — `uv run python -m nimo.demo --sheet qa --rows 10 [--live] [--html]`: drives the ordinary runner, renders one card per row from the eight artifact trees (every line names its stage), a summary with the tier distribution, and a self-contained HTML page | Runs end-to-end on 10 sample rows | **done offline; live run on `qa` pending the harvest finishing** (the demo must not write the artifact tree a running harvest is writing). Decides nothing, computes nothing new; prints the warm-start caveat every time (Tier 0 fires on a re-run). 4 tests over a runner-built tree; 727 pass |
| P16 | Interactive interface | `uv run python -m nimo.ui [--live]` — a local web page over the same composed pipeline (`run/compose.py`, shared with the CLI): run any row on demand, run it again to show the Tier 0 warm-start, resolve an ad-hoc product typed by a person, watch the registry | Runs the pipeline for a typed product and for a sheet row; the second run of a GTIN-confirmed row is a registry hit | **done.** Verified live: `qa:0` in 0.2 s from cache, `qa:9` as `tier0_exact`, an ad-hoc barcode the registry knows in 0.03 s, a new product through live search in 18 s. 10 tests through FastAPI's test client, zero network; 754 pass |
| P17 | Results explorer | `uv run python -m nimo.site --sheet qa --out-dir D` — one self-contained HTML file over a run: every complete row's card (the live UI's renderer, shared), search and filters, failures, the registry, the run's numbers and the operator's notes. For evaluators who will not run the pipeline and cannot be given a hosted one (the model is NIQ-internal; the rows are NIQ's data) | Opens from a local path with no server; every complete row present; self-contained; a `</script>` in the data cannot break it | **done.** Verified in a browser on the first office run: 409 rows, 3 failures listed, 112 entities, 2.5 MB. 3 tests, zero network; 796 pass |
| P18 | Bring-your-own product list | `--input FILE` on `nimo.run`, `nimo.assemble` and `nimo.site` — any `.xlsx`/`.csv` with `RETAILER_DESC` + `BRAND` (barcode, retailer, country, keys optional) read as text and turned into `RawRow`s by the loader's own field parsers (`src/nimo/loader/input.py`), keyed `<file-stem>:<index>` and never `dev`/`qa`/`adhoc`; `assemble_input_rows` produces the same validated 23-column `OutputRow`s with the file's own passthrough | The three CLIs run end to end on a file of products not in the dataset; a `qa.csv` cannot masquerade as the evaluation sheet; an absent column is a stated default, never a guess | **done.** Offline end to end on a three-row xlsx of products not in the dataset (2026-09-12): 3/3 rows through run → assemble → site; then live (SearxNG up): 3/3 rows in 31 s — and the live check found the site-root defect (P7/P9 rows above): two typed barcodes no engine indexes filled the fetch budget with brand homepages. 9 tests (loader + assembly), zero network |


**P4 before P7 (retrieval) is deliberate.** Building retrieval before you can
measure it produces confident, unmeasurable code. If P4 feels like a detour,
re-read `01` §6 — there is no URL ground truth in the dataset, so if we don't
make it, it doesn't exist.

**P5 before P7 is also deliberate.** The text-only module baseline may capture
most of the module signal for free, and it is the fallback when retrieval
fails. Knowing its accuracy changes how much effort P7–P11 deserve.

**P6 (registry) before P7 (retrieval) is deliberate too.** The registry's
tier-0/1 short-circuit only pays off if it exists before the expensive tiers
do — building retrieval first and bolting a registry on after means re-plumbing
every downstream stage to check it. The registry's own gate (the 40-row dev/qa
overlap, `03` §1a) needs nothing from P7 to pass.

## 1a. Resumability contract — `PROGRESS.md`

**The problem this solves, precisely:** a build session can be cut off
by a token or time limit at any point, with no warning, mid-task — not just
between phases. Recovery has to work when the user's entire next message is
"continue." That means the state needed to resume can't live in conversation
(none persists) and can't live only at phase granularity (`04` §1's `Status`
column tells you *which phase*, not *which line of that phase's spec you were
on when the tokens ran out*). `PROGRESS.md`, at repo root, is that finer state.

**Relationship to the `Status` column:** `Status` is coarse, updated at phase
boundaries, for a human glancing at overall progress. `PROGRESS.md` is fine,
updated continuously *within* a phase, and is what actually gets read to
resume. Keep both — they answer different questions.

**Mechanics.** `PROGRESS.md` is imported by the session brief, so it loads
automatically at the start of every session — before the user has typed
anything. It is **overwritten in place, not appended to** (unlike
`02-decision-log.md`, which is a history; this is a single "you are here"
marker with no value in old entries). Format:

```markdown
# PROGRESS.md — current build state

## Right now
Phase: P2 (loader) — IN PROGRESS
Last completed milestone: P1 (contracts), gate passed.
Next milestone: P2 (loader), spec: specs/loader.md.

## Verified state (re-check on resume, don't trust blindly)
Last `make check`: PASS, as of the P1 milestone commit.
Last milestone commit: <hash> "<message>"

## Do NOT re-do
- P0, P1: done, gates passed, committed.
```

**Update discipline — milestone cadence, not session cadence.** Update
`PROGRESS.md` when a phase's gate passes — P0 done, P1 done, and so on —
not at every sub-step, and not at every session boundary. A session that
starts, does part of P2, and ends without finishing P2 does **not** touch
`PROGRESS.md`. This is a deliberate change from an earlier
version of this section, which required sub-step-level updates — logged in
`02-decision-log.md` along with why: reduce bookkeeping overhead during a
long autonomous run where many sessions may pass within a single phase.

**The tradeoff this accepts, and what covers it:** between milestones, the
resumability signal is **git history**, not `PROGRESS.md`. This means commit
hygiene matters more now, not less — commit at the smallest coherent unit
(one file, one function, one passing test), with a commit message specific
enough that `git log --oneline` alone tells a resuming session roughly how
far into the current phase things got. A vague message like "wip" defeats
the whole point; `"loader: EXTERNAL_CODE parsing + corruption regression
test (specs/loader.md §2)"` doesn't.

**On every session start, including a bare "continue":** read `PROGRESS.md`
for the last *completed* milestone — that narrows things to "which phase is
in progress." Then read `git log` since that milestone's commit to find how
far the in-progress phase actually got — that narrows further. Then verify
with `make check` and by actually opening the files git log points to,
rather than trusting either source blindly. Resume from there. Do not ask
the user what to continue, and do not wait for a reply before proceeding —
see the escalation-policy change below.

## 2. Environment & layout

- **Python 3.12**, pinned. `uv` for dependency management, `uv.lock` committed.
- No global installs, no `pip install` in scripts, no notebook-only code paths.

```
NIMO/
├── docs/                  00..04, this file
├── specs/                 per-module build specs (authored web-side)
├── config/                *.yaml — retailers, thresholds, models, prompts
├── data/
│   ├── raw/               dataset xlsx — READ ONLY, never written
│   ├── gold/              hand-labelled URL set
│   ├── registry/          CanonicalEntity store — persisted, backed up, NOT gitignored
│   ├── cache/             fetch + LLM cache — gitignored
│   └── out/               predictions, traces — gitignored
├── src/nimo/
│   ├── contracts.py       pydantic models, zero logic
│   ├── loader/            P2
│   ├── normalize/         P3
│   ├── classify/          P5
│   ├── registry/          P6 — blocking, Union-Find, tier 0/1 lookup
│   ├── retrieval/         P7
│   ├── fetch/             P8
│   ├── extract/           P8
│   ├── match/             P9–P11  ← hard-20%, authored web-side
│   ├── characteristics/   P12
│   ├── reason/            P13
│   ├── assemble/          P14
│   └── run/               batch runner, CLI
├── tests/                 mirrors src/nimo/ exactly
│   └── fixtures/          frozen HTML, frozen LLM responses
└── Makefile
```

`tests/` mirroring `src/` is enforced: a module without a matching test
directory fails CI.

## 3. Typing and contracts

- `mypy --strict` passes. No `Any` outside a documented boundary. No
  `# type: ignore` without a comment naming the reason.
- **Every inter-module value is a pydantic model from `contracts.py`.** No bare
  dicts crossing module boundaries. A dict is fine inside a function; it is not
  fine as a return type.
- Contracts are versioned by the decision log. Changing a field is a decision
  entry — silent schema drift is the failure mode that costs a day of debugging.
- `Literal` types over free strings for every enum-like field (`fetch_status`,
  `size_match`, etc.).

## 4. Error handling — fail loud

The default for anything unexpected is **raise**. Silent degradation is the
single most expensive bug class in a pipeline like this because it produces
plausible wrong answers instead of visible failures.

Rules:

- **No bare `except:`. No `except Exception:` without re-raise or an explicit,
  logged, typed failure record.**
- **No default fallback values that mask a failure.** `size = parsed or 100.0`
  is forbidden. If parsing failed, the field is `None` and downstream must
  handle `None` explicitly.
- **No `try/except` around a whole function.** Wrap the single line that can
  fail, with the specific exception type.
- Per-row failures in the batch runner are caught at exactly one place — the
  runner — recorded as a typed `RowFailure` with stage, exception type, and
  message, and the row continues as a failure, not as a partial success.
- **Never write a partial output row.** A row either has a complete validated
  result or is recorded as failed. Half-filled rows in the submission are worse
  than blanks.
- Assertions on invariants, enabled in production. `assert len(out) == 412` is
  cheap and catches the class of bug that silently drops rows.

## 5. Determinism

Non-negotiable, because `03` §5 depends on it:

- Every LLM call: `temperature=0` **where the model accepts it**, fixed seed
  where supported, response cached by `sha256(model + prompt + params)`. The
  pinned CIS model rejects `temperature=0` (measured 2026-09-12: HTTP 400,
  "only the default (1) value is supported"), so for it the parameter is
  omitted (`config/models.yaml`: `llm_temperature: null`) and byte-identical
  re-runs rest on the cache alone — a warm re-run issues no call. Cold-cache
  first calls may differ on genuinely ambiguous rows; `data/cache/llm/` is
  therefore carried between machines like the registry (`06` §6).
- No `random` without a seeded generator passed in explicitly. No
  `random.seed()` at module level.
- No wall-clock or `datetime.now()` in logic — only in logging and metadata.
- Dict iteration order is stable in Python but do not rely on set ordering;
  sort before serializing.
- **Acceptance test:** run the full pipeline twice with a warm cache; output
  files must be byte-identical. This is a CI test, not a manual check.

## 6. Network discipline

- **Zero network calls in tests.** Any test that touches the network fails CI.
  Use frozen fixtures.
- All HTTP goes through one client wrapper: timeouts (connect + read, always
  set), per-domain rate limiting, exponential backoff with jitter, max 3
  retries, retry only on 5xx/timeout.
- Cache-first. A cache hit must not issue a request. Cache is content-addressed
  and inspectable.
- `robots.txt` honored. Identifying User-Agent. Concurrency cap per domain.
- Circuit breaker: N consecutive failures on a domain → stop hitting it, record
  the fact, continue with other domains.

## 7. LLM usage discipline

- Prompts live in `config/prompts/*.md`, versioned, never inline f-strings
  buried in logic.
- Every LLM call returns a **schema-validated** object. Validation failure →
  one retry with the validation error appended → then typed failure. Never
  accept unvalidated free text into a data field.
- Closed-vocabulary fields are validated against `char_value_list`, not trusted
  to the prompt.
- Token and cost counters per call, aggregated per stage, printed at end of run.
- No chain-of-thought in output fields. `REASONING` is a deliberate, grounded
  artifact (`03` §4 stage 6), not a dump of model thinking.

## 8. Testing

Three tiers, all required:

1. **Unit** — pure functions, no I/O. Normalizer, feature computation, size
   parsing, URL canonicalization. Fast.
2. **Contract** — every model round-trips; every stage's output validates
   against the next stage's input. These catch schema drift.
3. **Golden/fixture** — frozen HTML per retailer, frozen LLM responses. Extractor
   output is asserted field-by-field against a committed expected JSON.

Additional required tests:

- **Every defect in `01` gets a regression test.** Barcode rounding detection,
  leading-apostrophe stripping, characteristic name normalization, qa header
  exactness. These are the known-sharp edges; they get permanent guards.
- **Adversarial matcher cases**, hand-built: same brand different size; same
  product different multipack count; refill vs complete pack; a page with a
  conflicting GTIN; a page with no structured data at all. The brief's success
  criterion is "distinguish the correct product from similar or misleading
  matches" — these tests *are* that criterion.
- Groundedness test: evidence record lacking a fact ⇒ reasoning must not assert
  that fact.

Coverage is not a target. Every public function in `contracts.py`, `match/`,
`normalize/`, and `characteristics/` having a test is a target.

## 9. Configuration & secrets

- All thresholds, weights, model names, rate limits, and paths in `config/`.
  **Zero magic numbers in code.** A weight in a scoring function is a config
  value with a name.
- Secrets in `.env`, gitignored, loaded once at startup, validated present at
  startup (fail immediately, not at first use).
- No credentials, API keys, cookies, or session tokens in the repo, in fixtures,
  in logs, or in trace files. Fixture HTML must be scrubbed before committing.

## 10. Logging & observability

- Structured JSON logs. No `print()` outside the CLI's user-facing output.
- One trace record per (row, stage) written to `data/out/trace.jsonl`,
  containing the stage's inputs, outputs, features, and timing.
- Log levels used honestly: `ERROR` means something needs fixing; `WARNING`
  means a recoverable anomaly worth counting; `INFO` is progress.
- Every run prints a summary: rows processed, rows failed by stage, LLM calls,
  tokens, cost, wall time, cache hit rate.

## 11. Definition of Done

A module is done when **all** of these hold. Claiming done without them is the
thing this document exists to prevent.

- [ ] Implements the committed spec in `specs/<module>.md` — no silent deviation
- [ ] `mypy --strict` clean
- [ ] `ruff check` and `ruff format` clean
- [ ] Unit + contract tests present and passing
- [ ] Fixture tests for any I/O boundary
- [ ] Regression test for any defect in `01` it touches
- [ ] No bare except, no masking fallback, no magic number (§4, §9)
- [ ] Deterministic: twice-run byte-identical
- [ ] No network in tests
- [ ] Trace output emitted for its stage
- [ ] Decision-log entry if any contract or design point changed
- [ ] For fetch, registry, or any LLM-call module: `05` §6 additional DoD items satisfied
- [ ] `make check` green

`make check` = `ruff check src tests && ruff format --check src tests &&
mypy --strict src tests && pytest` — scoped to `src`/`tests`, not `.`; an
earlier version of this targeted `.` and caused `ruff format` to rewrite
Markdown in `docs/`/`specs/` (`02-decision-log.md` has the record; the fix
that resolved it is in `specs/scaffold.md`'s `pyproject.toml`/`Makefile`).

**If `make` isn't installed on the machine**, running the four commands
above directly, in this order, with each exit code recorded, is a complete
and valid substitute for every phase's DoD — not a deviation to flag each
time. State plainly in the phase report that this is what was run instead of
`make check` verbatim; don't silently equate "I ran the four commands" with
"`make check` passed" without saying so.

## 12. Forbidden patterns

Quick-reference list. Each maps to a rule above.

| Forbidden | Why | Rule |
|---|---|---|
| `except:` / `except Exception:` without re-raise | masks real failures | §4 |
| `x = parsed or DEFAULT` | silent wrong data | §4 |
| Bare dict crossing a module boundary | schema drift | §3 |
| Magic number in a scoring function | untunable, untraceable | §9 |
| `print()` in library code | unstructured output | §10 |
| Network call in a test | flaky, slow, non-deterministic | §6, §8 |
| Inline prompt string in logic | unversioned, undiffable | §7 |
| Unvalidated LLM output into a data field | hallucinated values in submission | §7 |
| Writing to `data/raw/` | destroys the source of truth | §2 |
| Partial output row on failure | plausible wrong answer | §4 |
| `# type: ignore` with no reason | hides a real type error | §3 |
| Country hard-filter on candidate domains | contradicts reference answer | `03` §4 |
| Filling a non-applicable characteristic | scored as wrong | `03` §4 stage 5 |
| Fetched page content concatenated raw into a prompt | prompt injection surface | `05` §1 |
| Fetching a URL without scheme/private-IP/redirect validation | SSRF | `05` §2 |
| `model="latest"` or unpinned model string | silent output drift on upstream update | `05` §3 |
| Registry write with no audit-log entry | unrecoverable if a merge is later found wrong | `05` §4 |
| Infinite-TTL cache with no re-fetch path | serves stale content forever, no error | `05` §5 |

## 13. Decide-log-continue — the default, under full autonomy

**This section changed from an earlier "stop and wait" policy.** Logged in
`02-decision-log.md` along with why — this run operates with full autonomy
across many phases, reviewed at the end, not after every small decision. A
"stop and wait for a reply" policy doesn't work when no one is watching for
the stop.

**The default, when a spec conflicts with `03-architecture.md`, a `04` rule
blocks something a spec requires, an undocumented dataset defect appears, a
design change would touch a contract, or a new latent-failure mode surfaces
(the exact situations that used to trigger a stop):** investigate, decide,
document, continue. Concretely:

1. **Verify before deciding, the way the three P0 build-tooling defects were
   resolved** — reproduce the problem in isolation, test candidate fixes
   against the real behavior (real `uv`/`mypy`/`ruff`/library versions, real
   data), don't reason from memory about how a tool "should" behave. That
   verification *is* the rigor this policy relies on to be safe without a
   human in the loop for each call.
2. **Update whichever of `01`–`05`/`specs/*.md` the decision affects**, so
   the documents stay authoritative and internally consistent — this was
   always required, not new.
3. **Write a full decision-log entry** — Decision / Why / Affects / Status,
   same format as always, with enough detail that someone reviewing at the
   end can audit the reasoning, not just the outcome.
4. **Continue.** Do not pause, do not wait for a reply, do not treat the
   decision-log entry as a question.

**What still stops everything — genuinely rare:** evidence that the current
architecture is fundamentally unworkable for the problem, not just a spec
defect within it (e.g., a core assumption `03` depends on turns out to be
false in a way no config flag or contract fix can route around). That's not
a decision to make solo; flag it clearly at the top of the next report and
stop new work in that area specifically — everything else keeps moving.

**`[PROVISIONAL — Qn]` points are not a stopping condition.** They were
already designed to not block — implement behind the stated config interface
and continue, exactly as `03` specifies. An organizer's eventual answer
changes a config value, not a redesign.

**Extra rigor, not a stop, for the categories the project instructions
originally marked HARD-20%** (concurrent/shared state logic, core
algorithmic components — registry merge logic, calibration, matching — and
security-sensitive boundaries): more tests, more explicit reasoning in the
decision log, and flag these specifically in the final report as the areas
that most reward careful review — the original instructions' reason for
singling them out (highest cost if subtly wrong) still holds even though
delegation isn't the mechanism separating them anymore.
