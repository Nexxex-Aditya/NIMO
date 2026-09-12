# 08 — The portal submission: what goes in each field

The NIQ Innovation Council form (team *Matrix Slayers*, problem *The Product
Truth Agent*) has: Title (100 chars), Description (5000 chars), up to 5
supporting links, and up to 5 attachments (PDF/DOC/DOCX/PPT/PPTX/XLS/XLSX/
MP4, 50 MB each) — **at least one PPTX and one MP4 are required**, and the
PPTX must follow the organizers' template (download it from the form).

Everything below is a draft to copy from, not a script to obey. Numbers
marked `<…>` are filled from the final run (`docs/06-office-runbook.md`);
do not submit a number that was not measured.

## Title

    NIMO — the Product Truth Agent: a deterministic, memory-backed pipeline that finds, proves and explains a product's true page

(96 characters.)

## Description (≤ 5000 characters)

NIMO takes one retail record — a retailer's description, brand, barcode,
country — and answers four things with evidence: which web page is this
product, what module is it, which characteristics apply and what are their
values, and why. It was built to be scored, not to impress on a good day:
every stage writes a typed record, the final reasoning is composed from
those records rather than generated, and a re-run with a warm cache is
byte-identical — verified across two different laptops.

**How it works.** A deterministic eight-stage pipeline with the model as a
bounded, schema-validated component, not an agent loop. (1) The description
is normalized — brand, size, pack count, variant words — with every stripped
token recorded. (2) A persistent Canonical Entity Registry is consulted
first: a product resolved before is answered from memory in milliseconds
(Tier 0 by barcode, Tier 1 by identity similarity within a block), and the
expensive stages are skipped. (3) On a miss, candidate pages come from a
self-hosted meta-search layer over five query strategies, engine-rotated
with a per-engine circuit breaker — a full 412-row run completed on free
engines in 107 minutes with zero failures. (4) Pages are fetched through
one polite client (robots, per-domain pacing, SSRF re-validation on every
redirect hop) and parsed JSON-LD-first. (5) A hard-rule matcher decides
identity — an exact GTIN accepts, a conflicting GTIN rejects, wrong size or
pack count demotes, listing and directory pages demote — and only then a
weighted score, calibrated against 236 barcode-confirmed pages into a real
probability (held-out ECE 0.068). Ties go to the model, which can only
point at one of the fixed candidates, never invent a URL. (6) The module
comes from a character-n-gram classifier over the description (80.3% /
49.7% macro on the labelled set, leave-one-out); adding page text was
measured and found to hurt, so it was not added. (7) Characteristics: the
applicability gate is ours and runs before and after the model; values are
validated per component against the organizers' vocabulary; where the
written guideline's default and the coders' practice differ, the labelled
data decides, with the measurement shown to the model; the pack shot is
attached as image evidence for the visual characteristics. (8) Reasoning is
composed from the fields — EAN, size, page element, coded value — each
clause tagged with its source, so a claim cannot appear that no stage
recorded.

**What was measured, honestly.** The dataset's barcodes, item codes and
keys are rounding-corrupted in most `dev` rows (documented and worked
around, never keyed on); the candidate pages the brief promised were not in
the data, so retrieval was built. 111 of 412 evaluation rows resolved to a
page publishing the record's own GTIN. Module accuracy and per-
characteristic accuracy are reported against `dev`'s labels — <fill from
the final run: micro accuracy, best and worst characteristic>. Where a
number could not be measured, the build table says "not measured" rather
than estimating it.

**What evaluators can use.** A self-contained results explorer — one HTML
file, every row's card with every stage's record, searchable, no install —
plus the live interface shown in the video: run any row, run it again to
watch the registry answer from memory, type a product of your own. The
repository carries the full decision log: every design choice with the
measurement behind it, including the ones that were tried and rejected.

(Count the characters after filling `<…>`; the draft above is ~3,300.)

## Supporting links (up to 5)

| Link title | URL |
|---|---|
| Results explorer (open in a browser) | a SharePoint/OneDrive link to `site_qa.html` — inside NIQ, not public |
| Repository | `https://github.com/Nexxex-Aditya/NIMO` |
| For judges: how to see it, run it, check it | the repo's `docs/07-judges-guide.md` |
| Decision log | the repo's `docs/02-decision-log.md` |

Why the explorer is a link to a file and not a website: no free host can
run the pipeline (the model is NIQ-internal), and the rows are NIQ's data —
a public site would publish them. The file opens from a download exactly
as from a server.

## Attachments (up to 5, 50 MB each)

1. **PPTX** — on the organizers' template (required). Suggested slide order:
   the problem in one line and what the data actually contained; the
   pipeline (the eight stages, one diagram); the registry and what "memory"
   buys; identity by hard rules, then calibration; characteristics (the
   gate, the vocabulary, practice defaults, image evidence); the numbers
   table copied from `docs/04-build-standards.md` §1; what evaluators can
   open; what was tried and rejected.
2. **MP4** — the live session (required; storyboard below). Keep it under
   5 minutes and under 50 MB (1080p, ~4 Mbps is ~150 MB for 5 min — record
   at 720p or trim to 3 minutes).
3. **`submission_qa.xlsx`** — the deliverable (allowed type).
4. Optional: a PDF export of `docs/07-judges-guide.md`.

## The video, storyboard (3–5 minutes, office laptop, NIQ network)

Record with Xbox Game Bar (`Win+G`) or OBS at 720p. No narration is
needed if the cursor moves slowly; captions in the deck cover the rest.

| # | Show | Say (or caption) |
|---|---|---|
| 1 | `uv run python -m nimo.llm --ping` then `--ping-image` | "The model is reachable; it sees images." |
| 2 | `uv run python -m nimo.ui --live --characteristics`, open `http://127.0.0.1:8765` | "The interface drives the same pipeline the batch run uses." |
| 3 | Pick a `qa` row that is new to the registry → **Run**; wait for the card | "Every stage writes its record: candidates, pages, why this page won, the module, the characteristics, the reasoning composed from them." |
| 4 | **Run again (warm)** | "The same row, from memory: a registry hit, stages 2–4 skipped, milliseconds." |
| 5 | Type a product in the ad-hoc form (a real toothpaste, with its barcode if you have one) → **Resolve** | "A product nobody typed before goes through live search, fetch, match, classify and extraction." |
| 6 | Filter to an adjudicated row; show the model's rationale on the card | "When the matcher cannot separate candidates, the model points at one of them — it cannot name a URL of its own." |
| 7 | Open `site_qa.html`; search a brand; open a card; the numbers panel | "This is what evaluators receive: every row, every stage, one file." |

Rows that make good examples are the ones the explorer's filters find:
*identity → GTIN-confirmed* for step 3, *adjudicated* for step 6.
