# 07 — For judges: how to see it, run it, and check it

NIMO answers one question per retail product record: *which web page is
this product, what module is it, and what are its characteristics — and
why?* This page is the shortest route to seeing that answer being made, on
three levels of effort.

## Level 0 — ten minutes, nothing to install

Two files, both produced by the pipeline and carried out of the run:

- **`submission_qa.xlsx`** — the 412-row deliverable in the organizers'
  own column order. `PRODUCT_URL`, `MODULE`, the 13 characteristic columns,
  and `REASONING` — which is composed from the evidence record, never
  generated, so every sentence names the field it came from (an EAN
  match, a size, a page element, a coded value).
- **`demo_qa.html`** — one self-contained page: ten rows, one card each,
  every stage's record in order (registry → retrieve → fetch → match →
  classify → characteristics → reason), then the run's tier distribution.
  Opens in any browser.

Both live under `data/out/<run>/` after a run (`docs/06-office-runbook.md`
step 4). `docs/04-build-standards.md` §1 is the build-order table; every
phase's gate row says what was measured and what was not, in the same words.

## Level 1 — the live demonstration (on the NIQ network)

The model endpoint is internal to NIQ, so the live demo runs on the office
network — the presenter's laptop or a judge's; either works.

```bash
uv run python -m nimo.ui --live --characteristics      # then open http://127.0.0.1:8765
```

A five-minute script that shows each claim being made rather than stated:

1. **Pick any `qa` row → Run.** The card fills in stage by stage: the
   candidates retrieved, which pages were fetched and what each yielded, the
   matcher's features per candidate and why one won (or was demoted — a
   search listing, a barcode directory, a wrong pack count), the module with
   the labelled row it most resembles, the coded characteristics with what
   the validator refused, and the reasoning composed from all of that.
2. **Run again (warm).** The same row comes back as a `tier0_exact`
   registry hit in milliseconds: retrieval, fetch and match are skipped
   because a previously resolved product is *remembered*, not recomputed.
   That is the efficiency claim (`03` §1a), shown.
3. **Type a product of your own** into the ad-hoc form — a description, a
   brand, a barcode if you have one. It goes through the loader's own
   parsers (a rounded barcode is refused exactly as a sheet's would be),
   then live search, fetch, match, classify and extraction. A barcode the
   registry already knows resolves instantly; a new one takes ~20 s.
4. **The registry panel** — the entities resolved so far, each with the
   rows folded into it and the audit trail of every write.
5. **Pick an adjudicated row** (the card says `tier3_llm`): the matcher
   could not separate its top candidates, so the model was shown a fixed
   pack of them and asked to point at one — it can only answer with an
   index into that pack, never a URL of its own, and the card shows which
   evidence it cited.

What to look for: nothing on the card is a summary of something hidden.
Every number is a field the pipeline wrote; the trace file
(`data/out/<run>/trace.jsonl`) has the same records, one per row.

## Level 2 — run it yourself, end to end

```bash
git clone https://github.com/Nexxex-Aditya/NIMO.git && cd NIMO
uv sync
cp .env.example .env         # CIS_LLM_API_KEY = your CIS key; SEARXNG_SECRET = anything
uv run pytest -q             # 793 tests, no network — the correctness gate
```

Then unzip the cache bundle (`nimo-cache-<date>.zip`, ~300 MB, from the
team) into the repo so `data/cache/{search,pages,llm,images}` exist. With
it, no Docker and no search engine are needed — every query and page the
412 rows require is already there, and a run only calls the model. Without
it, `docker compose up -d searxng` starts the pinned meta-search instance
and the pipeline fetches live (about two hours for 412 rows on free
engines; the retailer bot walls it meets are recorded, not hidden).

```bash
uv run python -m nimo.llm --ping                      # one model call
uv run python -m nimo.llm --ping-image                # one call with an image
uv run python -m nimo.run --sheet qa --live --characteristics --out-dir data/out/judge
uv run python -m nimo.assemble --sheet qa --out-dir data/out/judge
```

Three checks worth making on the result:

- **Determinism.** Run the last two commands again with the same
  `--out-dir`: the runner skips every completed row and the xlsx is
  byte-identical (`04` §5). It was byte-identical across two different
  laptops on 2026-09-12.
- **Accuracy where it can be measured.** `dev` has module labels and
  characteristic values; `qa` has neither.
  `uv run python -m nimo.run --sheet dev --live --characteristics --out-dir data/out/judge`
  then `uv run python -m nimo.characteristics --evaluate data/out/judge/artifacts/dev`
  prints per-characteristic accuracy against the organizers' labels;
  `uv run python -m nimo.classify` prints the module classifier's
  leave-one-out accuracy (80.3% overall, 49.7% macro over 27 modules).
- **Honesty of the confidence.** `uv run python -m nimo.calibrate` prints
  the calibration curve and its held-out error: the matcher's confidence
  is a probability fitted against 236 barcode-confirmed pages, not a score.

## What NIMO deliberately is not

A deterministic pipeline with the model as a bounded, schema-validated
component — not an agent loop. `docs/03-architecture.md` §1 and §7 say why
(reproducibility across 412 rows, per-stage debuggability, cost, and the
brief's own transparency criterion), and `docs/02-decision-log.md` records
every design decision with the measurement behind it, including the ones
that were tried and rejected.
