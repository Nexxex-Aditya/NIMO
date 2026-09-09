# 04 — Engineering Standards & Build Order

Version 0.1 — 2026-09-09. Binding on all implementation. If a rule here blocks
something the architecture requires, that is a decision-log entry, not a
judgement call at the keyboard.

Read §1 (Build order) to know *what* to build next. Read §2–§10 for *how*.
Read §11 before claiming any module is done.

---

## 1. Build order

Strictly sequential. Do not start a phase before the previous one's Definition
of Done (§11) passes. Each phase ends in a commit.

| # | Phase | Deliverable | Gate |
|---|---|---|---|
| P0 | Scaffold | Repo layout, deps, config, logging, CI | `make check` green on empty repo |
| P1 | Contracts | `contracts.py` — every model in `03` §3, no logic | Models instantiate; round-trip to JSON |
| P2 | Loader | Dataset ingest, all 7 acceptance criteria in `01` §10 | Corruption counts match `01` §3 exactly |
| P3 | Normalizer | `RETAILER_DESC` → `DescTokens` | 30 hand-written cases from real dev rows pass |
| P4 | **Gold set** | ~50 hand-labelled URLs, stratified by module | Committed as `data/gold/urls.jsonl` |
| P5 | Module baseline | Text-only module classifier, no URL | Per-module stratified accuracy reported |
| P6 | SearxNG + retrieval | Self-hosted instance, 5 query strategies | Recall@20 measured on gold set |
| P7 | Fetch + extract | Cached fetcher, JSON-LD-first extractor | Frozen HTML fixtures for 10 retailers |
| P8 | Matcher | Layer A features + hard rules | Precision@1 on gold set |
| P9 | Calibration + abstention | Isotonic/Platt fit, threshold config | Calibration curve reported |
| P10 | LLM adjudication | Top-k tiebreak, schema-constrained | Measurable delta over P8 alone |
| P11 | Characteristics | Applicability gate + per-char extraction | Per-characteristic accuracy on dev |
| P12 | Reasoning | Grounded synthesis | Groundedness fixture tests pass |
| P13 | Assembly | qa-schema output + trace | Byte-identical on re-run |
| P14 | Demo | Prototype UI/CLI walkthrough | Runs end-to-end on 10 sample rows |

**P4 before P6 is deliberate.** Building retrieval before you can measure it
produces confident, unmeasurable code. If P4 feels like a detour, re-read
`01` §6 — there is no URL ground truth in the dataset, so if we don't make it,
it doesn't exist.

**P5 before P6 is also deliberate.** The text-only module baseline may capture
most of the module signal for free, and it is the fallback when retrieval
fails. Knowing its accuracy changes how much effort P6–P10 deserve.

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
│   ├── cache/             fetch + LLM cache — gitignored
│   └── out/               predictions, traces — gitignored
├── src/nimo/
│   ├── contracts.py       pydantic models, zero logic
│   ├── loader/            P2
│   ├── normalize/         P3
│   ├── retrieval/         P6
│   ├── fetch/             P7
│   ├── extract/           P7
│   ├── match/             P8–P10  ← hard-20%, authored web-side
│   ├── classify/          P5
│   ├── characteristics/   P11
│   ├── reason/            P12
│   ├── assemble/          P13
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

- Every LLM call: `temperature=0`, fixed seed where supported, response cached
  by `sha256(model + prompt + params)`.
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
- [ ] `make check` green

`make check` = `ruff check && ruff format --check && mypy --strict && pytest`.

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

## 13. When to escalate instead of deciding

Stop and raise it rather than choosing:

- A spec in `specs/` conflicts with `03-architecture.md`.
- A rule here blocks something the architecture requires.
- A `[PROVISIONAL — Qn]` point needs an answer to proceed.
- A dataset defect appears that is not documented in `01`.
- A design change would alter a contract in `contracts.py`.

Escalation = a decision-log entry describing the conflict, plus flagging it in
the session. Do not implement around a conflict and mention it later.
