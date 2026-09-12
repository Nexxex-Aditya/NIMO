# specs/site.md — the static results explorer (P17)

Authored 2026-09-12, under the shared-authority rule
(`02-decision-log.md` 2026-09-10). Authority: `03` §1 (transparency is a
scored criterion), `03` §4 stage 8 (the trace is "the demo artifact"),
`specs/demo.md` (a renderer over the artifacts, never a second pipeline),
`specs/ui.md` (the live page and its card).

## 0. The problem this solves

Evaluators will not clone a repository and run commands. They also cannot be
given a hosted, running NIMO: the model endpoint is inside NIQ's network and
the search layer is a Docker container, so no free public host can run the
pipeline — and the rows are NIQ's dataset, which a public host would publish.
What evaluators *can* be given is everything the pipeline produced, in a
form that needs no server and no install and stays wherever NIQ keeps its
files: **one HTML file**.

## 1. What it is

`uv run python -m nimo.site --sheet qa --out-dir data/out/<run> [--title T]
[--note "..."]...` writes `<out-dir>/site_<sheet>.html`. The file embeds,
as JSON, one card per complete row of the run — **the same card the live UI
renders** (`nimo.ui.service.card_to_dict`) — plus the run's failures, the
registry, a summary, and any `--note` lines verbatim. The browser does the
rest: search, filters, a card per row, the registry table.

Nothing is computed here that the pipeline did not record. The summary
counts are counts over the embedded cards, so a reader can check any of
them by filtering.

## 2. The page

- **The run** — rows resolved / failed; tier distribution; identity
  confirmed by GTIN; rows sent to Tier 3 and, separately, rows the model
  *decided* (on the rest it saw no fit and Layer A's pick was kept — the
  two numbers differ and the page says why); pack shots examined; coded
  cells over applicable cells; modules; registry entities. Then the notes.
- **Rows** — a search box over row id, brand, description, module, URL and
  retailer; filters for tier, module, and identity (GTIN-confirmed,
  adjudicated, pack shot examined, failed). Failed rows are listed with
  their stage and error, never dropped (`04` §4).
- **The card** — rendered by the UI's own `renderCard` (`nimo.ui.page`
  `CARD_JS`), so the exported page and the live page cannot drift apart.
  A row is addressable by URL fragment (`#qa:74`).
- **Registry** — every entity: brand, barcode, module, page, member rows
  (each a link to its card).
- **How to read a card** — one paragraph of stage glossary.
- Footer: sheet, generation time, `config_hash` (`05` §5), characteristics
  sources.

## 3. Rules

- **Self-contained.** No `<script src>`, no `<link>`, no `@import`, no
  fonts, no images fetched: the file opens from a USB stick or a SharePoint
  download exactly as from a web server. Tested.
- **The data block cannot be broken by the data.** `</` inside the JSON is
  written as `<\/` — a page title or body text containing `</script>` would
  otherwise end the data block early. Tested with a hostile note.
- **Failures are this sheet's, still-incomplete rows only.** `failures.jsonl`
  is append-only across sheets and resumes; a row that failed once and
  succeeded on a resume is a success. Tested.
- **Schema drift fails loudly.** An artifact tree written under an older
  contract is refused by the same validation the pipeline uses (the first
  office tree needed a one-off migration for `image_sha256`); the explorer
  never papers over a field it does not recognise.
- **Where the file goes is the owner's decision.** The page carries the
  dataset rows. It renders identically from a SharePoint download, a local
  path, or GitHub Pages; publishing NIQ data publicly is not a choice this
  module makes.

## 4. Tests (`tests/site/`)

Over a tree the real offline runner built: every complete row is embedded
in sheet order and the summary matches; the page is self-contained and the
title is escaped; a `</script>` in a note cannot end the data block; failed
rows are listed, a resume turns a failure into a success, and another
sheet's failures are excluded. Zero network.

## 5. Definition of Done

- [x] `uv run python -m nimo.site --sheet qa --out-dir data/out/office`
      writes one file; opened in a browser, search/filter/card/registry work
      (verified 2026-09-12 on the first office run: 409 rows, 2.5 MB).
- [x] The card renderer is shared with the live UI, not copied.
- [x] `04` §11 gate green.
