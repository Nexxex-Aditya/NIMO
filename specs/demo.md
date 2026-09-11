# Spec — P15 demo (`src/nimo/demo/`)

Authority: `04` §1 P15 ("Prototype UI/CLI walkthrough — runs end-to-end on
10 sample rows"), `03` §1 (per-stage transparency), `03` §5 (report the tier
distribution — the efficiency evidence), `specs/registry.md` §3 (Tier 0
fires on a re-run, not a first pass).

## 1. What it is, and is not

`uv run python -m nimo.demo --sheet qa --rows 10 [--live] [--out-dir D] [--html]`

It drives the ordinary runner over the first N rows — the same code path
as a submission run, resumable, so rows already processed cost nothing —
then renders **what the eight stages recorded**: one card per row, a run
summary, and optionally a self-contained HTML page (`demo_<sheet>.html`, no
external assets). It decides nothing and computes nothing new. Every line
of a card names the stage it came from, which is `03` §1's transparency
claim shown rather than asserted.

## 2. The card

`[normalize]` cleaned description, size, count, hints, barcode state ·
`[registry]` tier, entity on a hit · `[retrieve]` candidate count by
strategy and `brand_signal_rate` · `[fetch]` fetch statuses and pages
carrying a GTIN · `[match]` host, score, gap, the hard-rule features,
calibrated probability, Tier 3 flag, URL · `[classify]` module, source,
confidence, nearest example · `[characteristics]` source, applicable and
coded counts, every coded value · `[reason]` the composed text. A failed
row shows its stage and error.

## 3. The summary — and the one honest caveat it prints every time

Complete/failed counts, the tier distribution, pages confirmed by GTIN,
registry size before → after, mode. And, every time: *Tier 0 fires on a
RE-RUN against a warm registry, not on a first pass* — the demonstration of
`03` §1a's efficiency claim is running the same rows twice with a fresh
`--out-dir` and watching the second pass skip stages 2–6.

## 4. Gate

`04` §1: runs end to end on 10 sample rows. Offline it always does; live it
needs SearxNG up and free-engine budget (`specs/retrieval.md` §5a.7). Tests
build a card from a tree the real runner wrote and check the rendering
names every stage, escapes HTML, and embeds no external asset.
