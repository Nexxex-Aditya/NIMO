# 06 — Office-laptop runbook

The only thing this project cannot do off the NIQ network is call the CIS
model. Everything else — retrieval, fetching, matching, the registry,
calibration, reasoning, assembly — has already run on all 412 `qa` rows and
all 412 `dev` rows at home, and its results are cached. This runbook is the
ordered list of what to do on a machine that can reach
`llm-api-cis.azure-intlsd-np.nielsencsp.net`.

**What the first trip (2026-09-12) taught, and this page now assumes:** the
office network answers retail websites with an error page — 94% of page
fetches failed there against 12% at home. So the office laptop must never
fetch a page; it must find every page in the cache. **`data/cache/pages/`
is required, not optional.** With all four caches present the office run
touches no website and no search engine; it only calls the model.

Each step says what it produces and what "good" looks like. Stop at the
first step that does not look good; the later ones depend on it.

## 0. What to carry over (do this on the home machine first)

1. `git push` — the code, docs, registry, calibration curve and gold data
   are all in the repo. On the office laptop: `git pull`.
2. **`.env`** is gitignored. Copy it by hand (USB/OneDrive, not chat/email):
   it holds `CIS_LLM_API_KEY` and `SEARXNG_SECRET`. Put it at the repo root.
3. **`data/cache/`** — all four, zipped together (~1 GB):
   - `data/cache/search/` (~2 MB) — every search query for `qa` AND `dev`.
     With it the office run needs no SearxNG and no Docker.
   - `data/cache/pages/` (~900 MB) — every fetched page. **Required**: the
     office network cannot fetch them (above). Pages expire 30 days after
     they were fetched (2026-09-11 → 2026-10-11); if the trip is later,
     say so before leaving and the home machine refreshes them first.
   - `data/cache/llm/` — the model's answers so far. Small. A re-run of an
     already-answered prompt is free and byte-identical.
   - `data/cache/images/` — the pack shot of every selected page, harvested
     at home (the office cannot fetch those either). Without it the runs
     still work; the model just sees no images and `image_sha256` stays
     empty on every row.
   Unzip into place so the paths read `data/cache/search`, `data/cache/pages`,
   `data/cache/llm`, `data/cache/images`.
4. Do **not** copy `data/out/` — the office run writes a fresh artifact
   tree (below). If an older office tree exists there from the first trip,
   leave it; the commands below use new folder names.

## 1. Set up (10 minutes)

```bash
git pull
uv sync
uv run pytest -q          # expect: all passed (793+). No network is used by tests.
```

If `uv sync` fails on a corporate proxy, `uv` honours `HTTPS_PROXY`.

## 2. The model call (1 minute)

```bash
uv run python -m nimo.llm --ping
```

Good:

```
resolves : ['10.249.224.116']
key      : present
... [info] llm_call completion_tokens=M model=... prompt_tokens=N reasoning_tokens=R
call     : OK  ok=True  model_seen='...'
```

Verified working on 2026-09-12 after two fixes (the model rejects
`temperature=0`; it reasons before it writes, so the cap is 4096). If it
fails now, the symptom table at the end has every case seen so far.

Then the image probe — new since the first trip, and the one thing on this
page that has never run on the network:

```bash
uv run python -m nimo.llm --ping-image
```

Good: `image : OK colour='red' shape='square' (as expected)` and a `tokens`
line — the prompt figure is what one image costs per row. The organizer
said the model accepts images; this is the check. If it says `FAILED` with
a 400 naming `image_url` or `content`, the gateway does not take image
input: set `use_image_evidence: false` in `config/characteristics.yaml` and
carry on — everything below runs from text, as the first trip did.

## 3. The dev gate — the P12 number (about 1 hour, unattended)

This is the measurement the project is missing: per-characteristic
accuracy against `dev`'s 412 labelled rows, **with page evidence**. It
needs the `dev` search cache (complete since 2026-09-12) and the page cache.

```bash
uv run python -m nimo.run --sheet dev --live --characteristics --out-dir data/out/office2
uv run python -m nimo.characteristics --evaluate data/out/office2/artifacts/dev
```

Good, run: `rows: 412  succeeded: 412  failed: 0`, `page-cache hit/miss:
N/0` or nearly — **a large miss count means the page cache is not in
place; stop and fix that before spending model calls.** Model calls ~412,
tokens ~1M.

Good, evaluate: a per-characteristic table ending in two `micro accuracy`
lines that AGREE (submission view = model view, because every row ran).
The first trip measured 68.6% over 92 rows with no page evidence; there is
no target number, but FLUORIDE, FLAVOUR and ORAL_CARE_FUNCTION should have
moved a great deal (the practice-default fix). Copy the whole table.

Optional, cheap, and the honest baseline for the report — the same run
from the record alone, no page evidence (note the flag set: no `--live`):

```bash
uv run python -m nimo.run --sheet dev --characteristics --out-dir data/out/office2-record
uv run python -m nimo.characteristics --evaluate data/out/office2-record/artifacts/dev
```

The evaluate output must say `412 from the model` — if it says `gate-only
tree`, the run was started without `--characteristics`.

## 4. The submission run (about 1 hour, unattended)

```bash
uv run python -m nimo.run --sheet qa --live --characteristics --out-dir data/out/office2
uv run python -m nimo.assemble --sheet qa --out-dir data/out/office2
```

Good: `rows: 412  succeeded: 412  failed: 0` (a transient gateway error
now retries three times; if a row still fails, re-run the same command —
it resumes and re-asks only that row), `registry: 112 entities`, and in
the assembly report **`GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS` filled on
412** — it applies to every module, so anything less means rows without
values (the first trip had 298: the 111 registry-hit rows were empty, fixed
since). `data/out/office2/submission_qa.xlsx` is the deliverable.

Then the explorer — the file evaluators open (`docs/07-judges-guide.md`):

```bash
uv run python -m nimo.site --sheet qa --out-dir data/out/office2 --title "NIMO — The Product Truth Agent" --note "Run of <date> on the NIQ network with the page and image caches; every row through the model."
```

`data/out/office2/site_qa.html`, ~3 MB, opens by double-click. Write the
`--note` in your own words — it is printed verbatim under the numbers.

If a judge hands over a product list of their own, the same three commands
take `--input FILE` in place of `--sheet qa` (`specs/input.md`) — but rows
the caches have not seen need live search and live retailer pages, which
the office network does not serve (§0). Run those at home, or from the
registry only (a barcode the registry knows resolves without a search).

Then the adjudication A/B — P11's gate, cheap because everything else is
cached (only the adjudication calls are new, ~60):

```bash
uv run python -m nimo.run --sheet qa --live --characteristics --adjudicate --out-dir data/out/office2-adj
uv run python -m nimo.assemble --sheet qa --out-dir data/out/office2-adj
```

Both submissions come back; the diff between them is the measured P11 delta.

## 5. Bring back

Zip and carry (USB/OneDrive):

- `data/out/` — every `office2*` folder: submissions, assembly reports,
  traces, artifacts, `site_qa.html`. This is the deliverable and its evidence.
- `data/cache/llm/` — the model's answers (small); they make any re-run
  here free and byte-identical.
- `data/registry/` — it will have gained characteristics on 111 entities.
- The `--ping-image` output line (the per-image token cost and whether it
  saw the colour).
- The terminal output of both `--evaluate` runs and each run summary
  (screenshots are fine).

Do not bring `.env` back on the same stick if it can be avoided; it is
already here.

## What can go wrong, and what it means

| Symptom | Meaning | Do |
|---|---|---|
| `--ping` times out | not on the network | VPN / office network |
| `--ping` 401/403 | auth shape | try removing the explicit `Authorization` header in `azure.py` (the SDK sends one already); send the line |
| `--ping` 400 mentioning `temperature` | old checkout | `git pull` (fixed 2026-09-12) |
| `LlmValidationError … input_value=''` | old checkout (64-token ping cap) | `git pull` (fixed 2026-09-12) |
| `LlmTruncated` | the model's reasoning ate the output cap | `llm_reasoning_effort: low`, else raise `llm_max_output_tokens` (`config/models.yaml`) |
| `--ping` 400 mentioning `max_tokens` | gateway wants the newer field name | `llm_max_tokens_param: max_completion_tokens` in `config/models.yaml` |
| `--ping-image` 400 naming `image_url` / `content` | the gateway does not accept image input | `use_image_evidence: false` in `config/characteristics.yaml`; the rest runs from text |
| `--ping-image` OK but colour is not red | the model got the image and misread a red square | send the line; leave images on |
| `pack_shot_unavailable` on most rows | image cache not in place | unzip `data/cache/images/`; harmless otherwise — rows run from text |
| rows fail at `retrieve` | search cache missing and no SearxNG | copy `data/cache/search/` (both sheets are in it) |
| `page-cache hit/miss` shows many misses | page cache not in place — the office network cannot fetch | stop; unzip `data/cache/pages/` into place; re-run (it resumes) |
| many `fetch http_error: HTTP …` warnings in the artifacts | same — the proxy answered instead of the retailer | same |
| `characteristic_rejected` on most rows | prompt/vocabulary mismatch | send the log |
| a row fails at `characteristics` or `match` with `ServiceResponseError`/`Timeout` | gateway hiccup that outlasted three retries | re-run the same command; it resumes |
| `LlmBudgetExceeded` | 412 rows with adjudication measured 1.02M of the 2M cap; a breach is pathological retries | send the log; do not raise the cap |
| assembly shows `PERCENTAGE_NATURAL_INGREDIENTS` filled < 412 | rows without values | old checkout — `git pull`, re-run (resumes, re-asks only those rows) |
| `--evaluate` says `gate-only tree` | the run was started without `--characteristics` | re-run with the flag |
| values look plausible but wrong | the real P12 finding | the `dev` accuracy table is the evidence; send it |
