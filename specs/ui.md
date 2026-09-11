# Spec — P16 interactive interface (`src/nimo/ui/`)

Authority: `04` §1 P15 ("prototype UI/CLI walkthrough"), `03` §1 (per-stage
transparency), `04` non-goals (no service, no auth, no scale-out).

## 1. What it is

`uv run python -m nimo.ui [--live] [--characteristics] [--adjudicate] [--port N]`

A local web page over the same pipeline the CLI runs — `run/compose.py` is
the one place the pipeline is composed, and both entry points call it. The
UI adds two things the CLI does not have:

- **Run one row on demand.** Resumable: a complete row costs nothing to
  show. `Run again (warm)` clears that row's artifacts and runs it again,
  which is how the registry warm-start is demonstrated — a GTIN-confirmed
  row comes back as a Tier 0 hit with the page and module carried.
- **Resolve an ad-hoc product.** A record typed by a person becomes a
  `RawRow` of the `adhoc` sheet through the loader's own field parsers
  (barcode rounding rule, brand/owner split, retailer table, countries) and
  runs the full pipeline. A barcode the registry knows resolves in
  milliseconds; a new product goes through search and fetch.

Everything the page shows is the pipeline's own record — the same `RowCard`
the P15 demo renders, as JSON — plus the registry's state. It computes
nothing.

## 2. Boundaries

- Binds to `127.0.0.1`; single user; no auth. It is a demo surface for a
  batch pipeline, not a service.
- Artifacts go under `data/out/ui/`, never the submission tree.
- Registry writes are real (a GTIN-confirmed lookup writes an entity,
  audit-logged) — the product working as designed, visible in the registry
  panel.
- The page is one HTML string with vanilla JS and no external assets, so
  it works offline and inside a corporate network.

## 3. Routes

`GET /` the page · `GET /api/status` mode, curve, registry size, model
counters · `GET /api/rows?sheet=` the sheet's rows with completion state ·
`GET /api/rows/{sheet}/{row_uid}` the card · `POST /api/run {sheet, row_uid,
force}` · `POST /api/lookup {desc, brand, barcode?, retailer?, country?}` ·
`GET /api/registry`. Service errors are 4xx with the message; nothing else
is caught.

## 4. Tests

`tests/ui/` through FastAPI's test client over an offline pipeline (zero
network): the page is self-contained; status reports the mode; rows list and
reject an unknown sheet; an unrun row 404s until run; a forced re-run is
deterministic; an unknown row is a 400; an ad-hoc lookup runs and is
idempotent by record; the ad-hoc row obeys the loader's rules (rounded
barcode nulled and flagged, retailer mapped, unknown retailer passed
through); the registry endpoint summarises.

Verified live (2026-09-12): `qa:0` through retrieval in 0.2 s from cache;
`qa:9` as a Tier 0 hit; an ad-hoc barcode the registry knows in 0.03 s; a
new product through live search and fetch in 18 s.
