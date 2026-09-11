# NIMO — The Product Truth Agent

Given a retail product record (retailer description, barcode, brand, country,
retailer), NIMO finds the webpage that is that product's true digital
representation, classifies the product into its NielsenIQ module, extracts the
module's characteristics from page evidence, and explains its reasoning —
every claim traceable to a recorded field.

Built for the NielsenIQ Innovation Portal hackathon (oral-care dataset,
UK-centric). It is a **deterministic pipeline with the model as a bounded
component**, not an agent loop: every stage writes a typed artifact, every
run is resumable, and a warm re-run is byte-identical.

## The pipeline

```
row ─► normalize ─► registry lookup ─► retrieve ─► fetch ─► match ─► classify ─► characteristics ─► reason
        (P3)         (P6: Tier 0/1)    (P7)        (P8)     (P9-11)   (P5)        (P12)              (P13)
                          │ hit ───────────────────────────────────────────────────────────────────────┘
                                                            assemble (P14) ─► submission_qa.xlsx
```

- **Registry** — a persistent store of resolved products (`data/registry/`).
  A row whose barcode has been resolved before skips retrieval, fetch, match,
  classification and extraction. Cost per row falls as the registry warms.
- **Retrieval** — self-hosted SearxNG, free engines only, engineered to run
  unattended: one engine per query, early exit at the fetch budget,
  per-engine circuit breaker, wait-for-cooldown, content-addressed cache.
- **Match** — hard rules first (GTIN equality decides; a conflicting GTIN
  rejects; size/count/refill/listing demote), then a weighted text score,
  then an isotonic calibration fitted on GTIN-confirmed pages, then an LLM
  tiebreak (Tier 3) only when the top candidates are close.
- **Characteristics** — the applicability gate is ours, before and after the
  model; closed values are validated per `&` component against the
  organizers' vocabulary; the model sees only the applicable guidelines.
- **Reasoning** — composed from the recorded fields, never generated, so it
  cannot assert what the evidence does not contain.

The design authority is `docs/03-architecture.md`; the engineering rules are
`docs/04-build-standards.md`; every decision and every measurement is in
`docs/02-decision-log.md`. Read `docs/01-dataset-contract.md` before trusting
the dataset — three of its columns are silently corrupted by a spreadsheet
number format, and the pipeline is built around that.

## Running it

Prerequisites: Python 3.12, [`uv`](https://docs.astral.sh/uv/), Docker.

```bash
uv sync
cp .env.example .env            # then fill SEARXNG_SECRET (and CIS_LLM_API_KEY on the NIQ network)
docker compose up -d searxng     # the meta-search instance, pinned by digest
```

Gate — must be green before any commit (`make check`, or the four commands):

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src tests && uv run pytest
```

The submission run, resumable, no model needed:

```bash
uv run python -m nimo.run --sheet qa --live          # retrieve, fetch, match, classify, gate, reason
uv run python -m nimo.calibrate                      # refit the calibration curve from the harvest
uv run python -m nimo.assemble --sheet qa            # data/out/submission_qa.xlsx (+ .csv, report)
```

On the NIQ network (the CIS model endpoint is internal-only), follow
`docs/06-office-runbook.md` — in short, verify the model with `uv run python -m nimo.llm --ping`, then add it:

```bash
uv run python -m nimo.run --sheet qa --live --adjudicate --characteristics
```

The interactive interface — run any row, run it again to watch the registry
warm-start, or type a product of your own:

```bash
uv run python -m nimo.ui --live          # http://127.0.0.1:8765
```

The batch demo — ten rows, every stage's record, and an HTML page:

```bash
uv run python -m nimo.demo --sheet qa --rows 10 --live --html
```

Run it twice with a fresh `--out-dir` to watch the registry warm-start: Tier 0
fires on the re-run, not the first pass.

Measurements that need no network: `uv run python -m nimo.classify` (module
baseline, leave-one-out), `uv run python -m nimo.characteristics`
(applicability under predicted modules), `uv run python -m nimo.calibrate`.

## Where the numbers are

`docs/04-build-standards.md` §1 is the build-order table; each phase's gate
row states what was measured and what was not. Gate rows that say "NOT
measured — needs the NIQ network" mean exactly that: the machinery is
fixture-tested here and the number is taken on-network.

## Layout

```
config/         thresholds, weights, prompts, engine and fetch settings — no magic numbers in code
data/raw/       the dataset, read-only        data/registry/   resolved products, committed
data/gold/      hand-labelled URLs and pairs   data/calibration/ labelled pairs and the fitted curve
docs/           00 brief · 01 dataset contract · 02 decision log · 03 architecture · 04 standards · 05 security
specs/          one spec per module, written before the code
src/nimo/       contracts.py + one package per stage      tests/   mirrors src/nimo, zero network
```
