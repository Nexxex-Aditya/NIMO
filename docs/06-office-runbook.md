# 06 — Office-laptop runbook

The only thing this project cannot do off the NIQ network is call the CIS
model. Everything else — retrieval, fetching, matching, the registry,
calibration, reasoning, assembly — has already run on all 412 `qa` rows and
its results are cached. This runbook is the ordered list of what to do on a
machine that can reach `llm-api-cis.azure-intlsd-np.nielsencsp.net`.

Each step says what it produces and what "good" looks like. Stop at the
first step that does not look good; the later ones depend on it.

## 0. What to carry over (do this on the home machine first)

1. `git push` — the code, docs, registry, calibration curve and gold data
   are all in the repo.
2. **`.env`** is gitignored. Copy it by hand (USB/OneDrive, not chat/email):
   it holds `CIS_LLM_API_KEY` and `SEARXNG_SECRET`.
3. **`data/cache/`** is gitignored and is what makes the office run cheap:
   - `data/cache/search/` (~2 MB) — every search query for `qa` (and `dev`,
     if the dev harvest finished) is cached here. **With it, the office run
     needs no SearxNG and no Docker.**
   - `data/cache/pages/` (~900 MB) — every fetched page. Optional; without
     it the runner re-fetches from the retailers (~1 hour, needs ordinary
     internet, no Docker).
   Zip `data/cache/` and copy it alongside.
4. Do **not** copy `data/out/` — the office run must produce a fresh
   artifact tree (below), and stale artifacts would make the runner skip
   rows.

## 1. Set up (10 minutes)

```bash
git clone https://github.com/Nexxex-Aditya/NIMO.git && cd NIMO
# install uv if absent: https://docs.astral.sh/uv/  (pip install uv works too)
uv sync
# put .env at the repo root; unzip data/cache/ into place
uv run pytest -q          # expect: all passed (744+). No network is used by tests.
```

If `uv sync` fails on a corporate proxy, `uv` honours `HTTPS_PROXY`.

## 2. The first live model call (1 minute) — the step that decides everything

```bash
uv run python -m nimo.llm --ping
```

Good:

```
resolves : ['10.249.224.116']
key      : present
call     : OK  ok=True  model_seen='...'
tokens   : prompt N, completion M
```

This is the first time `src/nimo/llm/azure.py` has ever executed against
its endpoint. If it says `FAILED — ServiceRequestTimeoutError`, you are not
on the network. If it says `FAILED — HttpResponseError ... 401/403`, the
key or the auth pattern is wrong — `config/models.yaml` documents the
double-pass the onboarding notebook used; try removing the explicit header
in `azure.py` (the SDK already sends `Authorization: Bearer`). Any other
error: send me the line.

## 3. Twenty rows with the model, watched (5 minutes)

```bash
uv run python -m nimo.run --sheet qa --live --characteristics --limit 20 --out-dir data/out/office
```

Good: `rows: 20  succeeded: 20  failed: 0`, `model: 20 calls`, and in the
log a few `llm_call` lines with token counts in the low thousands. Look
for `characteristic_rejected` warnings: a handful is normal (the validator
refusing a value outside the vocabulary and retrying once); every row
rejecting is a prompt problem — send me the log.

Then read what it coded:

```bash
uv run python -m nimo.demo --sheet qa --rows 10 --live --html --out-dir data/out/office
```

The `[characteristics]` line per row should say `llm: N applicable, M coded`
and list values like `GLOBAL_IF_WITH_FLUORIDE = WITH FLUORIDE`. If the
values read as nonsense against the product, stop and send me the cards.

Or look at them in the browser — the interactive UI runs the same pipeline:

```bash
uv run python -m nimo.ui --live --characteristics      # then open http://127.0.0.1:8765
```

Pick any row and press Run; press "Run again (warm)" on a GTIN-confirmed row
to watch it come back as a registry hit; type a product of your own in the
form. The UI writes under `data/out/ui/`, so it never touches the office
artifact tree.

## 4. The P12 gate — accuracy on `dev` (30–60 minutes, unattended)

This is the number the project is missing. Two forms, run the one you can:

**With page evidence** (needs the `dev` search cache — present if the dev
harvest finished at home; check `ls data/cache/search | wc -l` is well over
2000 — or Docker for SearxNG):

```bash
uv run python -m nimo.run --sheet dev --live --characteristics --out-dir data/out/office
uv run python -m nimo.characteristics --evaluate data/out/office/artifacts/dev
```

**Record-only** (no page evidence, no cache needed — a lower bound):

```bash
uv run python -m nimo.run --sheet dev --characteristics --out-dir data/out/office-record
uv run python -m nimo.characteristics --evaluate data/out/office-record/artifacts/dev
```

Good: the evaluate output ends with a per-characteristic table and a
`micro accuracy: H/T = P%` line. There is no target number — this is the
first measurement. Copy the whole table into the report back.

Budget: `config/models.yaml` caps a run at 5000 calls / 2M tokens; 412 rows
is ~412 calls and ~1.7M tokens. If the runner stops with
`LlmBudgetExceeded`, that is the abort working — tell me, do not raise the
cap.

## 5. The submission run (30–45 minutes, unattended)

```bash
uv run python -m nimo.run --sheet qa --live --characteristics --adjudicate --out-dir data/out/office
uv run python -m nimo.assemble --sheet qa --out-dir data/out/office
```

Good: `rows: 412  succeeded: 412`, then the assembly report showing the
13 characteristic columns filled (not 0) and
`data/out/office/submission_qa.xlsx` written. `--adjudicate` adds the LLM
tiebreak on rows where the matcher could not separate the top candidates;
`model: … verdicts rejected` in the summary counts the ones the schema
refused — a few is fine.

If step 3 or 4 showed problems, run step 5 without `--adjudicate` first;
adjudication is a refinement, the characteristics are the submission.

## 6. Bring back

- `data/out/office/submission_qa.xlsx` — the deliverable.
- `data/out/office/assembly_qa.txt` and the `--evaluate` output from step 4.
- `data/cache/llm/` (the model's cached answers — small, and they make a
  re-run free) and `data/registry/` (it will have gained characteristics).
- The run logs if anything looked wrong.

Commit `data/registry/` and `data/calibration/` if they changed; leave
`data/out/` and `data/cache/` uncommitted (gitignored).

## What can go wrong, and what it means

| Symptom | Meaning | Do |
|---|---|---|
| `--ping` times out | not on the network | VPN / office network |
| `--ping` 401/403 | auth shape | see step 2 |
| rows fail at `retrieve` | search cache missing and no SearxNG | copy `data/cache/search/`, or `docker compose up -d searxng` |
| rows fail at `fetch` en masse | no internet for retailers | check proxy; the page cache avoids this entirely |
| `characteristic_rejected` on most rows | prompt/vocabulary mismatch | send the log |
| `LlmBudgetExceeded` | pathological retries | send the log; do not raise the cap |
| values look plausible but wrong | the real P12 finding | the `dev` accuracy table is the evidence; send it |
