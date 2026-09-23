# Office laptop — demo and final run (no Docker)

The office laptop cannot run Docker, so search goes through the **Brave
Search API** instead of SearxNG. Every query the home harvest already asked
(all 412 qa rows) is answered from the carried cache and costs **no Brave
credit**; only a product nobody has searched before is paid for, capped at
150 calls per run.

## 1. Set up (once, ~10 minutes)

```powershell
git pull
uv sync
```

1. **`.env`** — copy it from the home laptop by hand (USB/OneDrive, not
   chat/email). It must contain `CIS_LLM_API_KEY=...`, `BRAVE_API_KEY=...`
   and `SEARXNG_BASE_URL=http://localhost:8080` (unused here, but required).
2. **Caches** — copy `nimo-cache-2026-09-23.zip` and unzip it **at the repo
   root**, replacing the old `data/cache/`. The paths must read
   `data/cache/search`, `data/cache/pages`, `data/cache/llm`,
   `data/cache/images`. The oldest cached searches and pages expire on
   **2026-10-11**; after that date, re-harvest at home first.

## 2. Two checks (1 minute)

```powershell
uv run python -m nimo.llm --ping
uv run python -m nimo.retrieval --ping
```

The first must print a model answer; the second `OK: Brave Search API
answered 5 results` (costs 1 credit). If the Brave ping fails with a
certificate error, add `NIMO_SYSTEM_CERTS=1` to `.env` and run it again —
it makes Python trust the company certificate store.

## 3. The demo (what to record)

```powershell
uv run python -m nimo.ui --live --characteristics
```

Open http://127.0.0.1:8765 and:

1. **A dataset row** — click `qa:0` (Brilliant charcoal whitening kit), press
   **Run**. Point at: the paint pages and the tutoring site the word
   "Brilliant" pulled in, and the Superdrug product page the matcher chose
   (calibrated 0.93); the module and its cited nearest example; the
   characteristics the model coded; the reasoning, with a source for every
   clause. No Brave credit — it is cached.
2. **Memory** — click `qa:9` (Pärla toothpaste tabs), **Run**: it comes back
   as `tier0_exact`, answered from the registry, search skipped.
3. **A new product** — type a description and brand into *Try any product*
   (e.g. `listerine total care stain remover mouthwash 500ml`,
   `LISTERINE (KENVUE)`), press **Resolve**. This searches live through
   Brave (2–4 credits). The office network blocks most retailer pages, so
   the fetch lines will show `http_error`; the answer is then ranked from
   the page URLs. If you want the full page evidence on camera, record this
   step on the home laptop instead (same command without
   `--characteristics`).
4. **The results explorer** — open `data/out/site_qa.html` (or the one from
   step 4 below) and show search, the filters, and a GTIN-confirmed row.

## 4. The final submission run (optional, ~1 hour, unattended)

Everything is cached; this spends model calls, not Brave credits.

```powershell
uv run python -m nimo.run --sheet qa --live --characteristics --out-dir data/out/final
uv run python -m nimo.assemble --sheet qa --out-dir data/out/final
uv run python -m nimo.site --sheet qa --out-dir data/out/final --title "NIMO — The Product Truth Agent"
```

The run's last lines print `search backend: Brave Search API — N paid
call(s)`; N should be 0 or close to it. Outputs:
`data/out/final/submission_qa.xlsx` and `data/out/final/site_qa.html`.

## What to submit

- `presentation/NIMO_Hackfest_2026.pptx`: the deck on the required Hackfest 2026 template
  (rebuild with `uv run --no-project python presentation/template/fill_template.py`)
- the recorded MP4
- `submission_qa.xlsx` and `site_qa.html` from step 4 (or the existing ones)
- the repository link: https://github.com/Nexxex-Aditya/NIMO
