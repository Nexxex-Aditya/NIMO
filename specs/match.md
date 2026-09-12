# specs/match.md — P9: Matcher (Layer A + hard rules + write-back)

Authority: `03-architecture.md` §4 stage `[4]`, §1a (registry write-back).
Build standards: `04-build-standards.md` — and `04` §13 names this one of the
**HARD-20%** areas: "core algorithmic components — registry merge logic,
calibration, matching". More tests, more explicit reasoning, flagged for
careful review.

Depends on P3 (`DescTokens`), P6 (registry), P8 (`CandidateEvidence`).
**No LLM** — that is P11's Layer B. **No calibration** — that is P10.

---

## 1. The gate cannot measure the most important rule, and that has to be said first

`04` §1's P9 gate is "Precision@1 on gold set". Measured before building:

| | rows with a usable GTIN |
|---|---|
| **gold set** | **0 of 6** |
| `dev` | 18 of 412 |
| `qa` | **412 of 412** |

**Every gold row's barcode is corrupt.** So the GTIN hard rule — the single
strongest signal in `03` §4 stage 4, and the one that carries all of `qa` —
**cannot be exercised by the gate at all.** Precision@1 on the gold set
measures the weighted-feature path exclusively.

This is the dev/qa asymmetry biting for the third time (P6's Tier 0 could not
fire; P7's S1 covered 4% of `dev` and 100% of `qa`; now this). The response is
not to weaken the rule but to test it where it can be tested:

- **Hard rules → hand-built adversarial cases.** `04` §8 already requires
  exactly this: "same brand different size; same product different multipack
  count; refill vs complete pack; a page with a conflicting GTIN; a page with
  no structured data at all. The brief's success criterion is 'distinguish the
  correct product from similar or misleading matches' — **these tests *are*
  that criterion**." They need no gold set and they test what the gate cannot.
- **Weighted features → Precision@1 on the gold set**, 5 URLs, reported with
  n stated every time.
- **Product-level agreement** where evidence allows: chemist-4-u and
  pharmazondirect both publish GTIN `5011309895612` for the same product
  (`specs/fetch.md`), so a matcher that ranks both highly for that row is
  right even though the gold label names a third retailer.

### 1a. What the gate measured, live

Run end to end — retrieval → fetch → extract → match — over the five labelled
gold rows, twice, through the real client stack (robots, SSRF, cache, breaker):

| row | run 1 top | run 2 top | gold |
|---|---|---|---|
| `dev:37` | superdrug (**URL hit**) | superdrug (**URL hit**) | superdrug |
| `dev:68` | amazon, the gold page, demoted `travel` | dailychemist; gold at rank 3 | amazon |
| `dev:92` | twicedaily, same product | amazon, same product | wholedent |
| `dev:410` | savers (no GTIN) over chemist-4-u (GTIN) | **zero candidates** | chemist-4-u |
| `dev:205` | amazon, demoted `count` | same | caretobeauty — never retrieved |

**URL@1 = 1/5. PRODUCT@1 = 0/5** (most pages carry no GTIN to agree on).

Four things this shows, none of which a single number would:

1. **The results are not stable between runs.** Brave circuit-broke during
   run 1, so those queries were cached under `[startpage]`; run 2 had Brave
   back, a different engine set, a different cache key, and fresh — different —
   results. `dev:410` went from a ranked list to *zero candidates*. Free
   search is a moving target and the cache makes *warm* re-runs identical, not
   runs that span a breaker event. This is a property of the retrieval layer,
   recorded here because it is where it becomes visible in a score.
2. **The URL metric is blind to `dev:92`.** twicedaily, amazon and wholedent
   all sell the same Curaprox aligner foam; the matcher ranked a valid page
   first both times and the metric called it wrong both times. None of the
   three carries a GTIN, so the product-level check cannot rescue it either.
3. **A page's own GTIN is currently worth nothing when the query has none.**
   `dev:410`: savers (no structured data) outranked chemist-4-u (JSON-LD, GTIN
   `5011309895612`) because the query barcode is corrupt and
   `barcode_exact` is therefore `None`. A page that publishes a GTIN is at
   least a *real product page* rather than a listing — that is evidence, and
   the weighted sum ignores it. Not changed here: one row is not grounds for
   altering a HARD-20% scoring function. Recorded for P10.
4. **`CandidateEvidence.url` must be the canonical candidate URL, not the
   redirect landing.** The first gate run reported 0/5 because evidence carried
   the fetcher's `final_url` (with `www.`) while gold was canonical (without).
   A script bug — but the P6a runner will wire P7→P8→P9 next, and it must
   carry the canonical URL as identity or every downstream comparison breaks
   the same way.

## 2. Hard rules — evaluated first, and they override the weighted sum

`03` §4 stage 4, in order:

| rule | condition | outcome |
|---|---|---|
| GTIN accept | page `gtin` == query `barcode`, **both valid** | accept, score 1.0, stop |
| GTIN reject | page `gtin` != query `barcode`, **both valid** | reject outright |
| size mismatch | both sizes confidently parsed and different | hard demotion |
| count mismatch | single vs multipack | hard demotion |
| negative flags | `refill`/`travel`/`sample`/`bundle`/`gift set` present on page, absent from query | hard demotion |

**"Both valid" is load-bearing on both GTIN rules.** `01` §3 is an entire
document about an identifier silently reshaped by a spreadsheet; comparing a
rounded `5000000000000` against a real page GTIN would reject every correct
candidate for that row. The query side uses `barcode_valid` **and**
`not barcode_corrupt`; the page side must be a plausible GTIN length. Either
side unusable ⇒ `barcode_exact = None`, meaning *cannot evaluate* — which is
why `03` §3 gave that field three states instead of two.

**Demotion, not rejection, for size.** `03` §4 stage 4 is explicit:
"retailer pages sometimes list a range". A demoted candidate can still win if
nothing better exists, which matters when 4 of 10 pages are bot walls with no
evidence at all.

**Multipack count is a hard identity attribute** (`03` §4 stage 0). A 2-pack
and a single are different products; P3 already treats count that way and this
must not soften it back into fuzzy text similarity.

### 2a. URL-shape flags — pages *about* the product, not *of* it

Four negative flags need only the URL, never the page text
(`url_shape_flags`), and each was added from a measurement over real
selections rather than from a list of things that might go wrong:

| flag | shape (`config/match.yaml`) | measured |
|---|---|---|
| `listing_page` | search/listing markers: `/s?k=`, `/search?`, `/collections/`, `/product-collections/`, `_nkw=`, … | 2 of the first 5 live rows were Amazon search listings (2026-09-11) |
| `directory` | barcode directories and price aggregators by host suffix | 70 of 412 qa selections (17%) |
| `non_commerce` | encyclopedias, social, video by host suffix | 3 of 412 |
| `site_root` | an empty path, a single locale segment (`/en-gb`), or a single segment equal to the brand token (`superdrug.com/colgate`) | **94 of 412 qa selections (23%)**, 18 of 412 dev (2026-09-12) |

All four are **demoted, never rejected** — when nothing else was fetched
the page still wins and the reasoning says it was demoted — and among equal
scores `rank_candidates` sorts them last (`ABOUT_FLAGS`): identifier first,
page type second, URL third.

**Why `site_root` was the largest and the last to be found.** A brand's
homepage carries the brand, a plausible title, no size to mismatch and no
negative word, so the weighted score likes it — at 0.4-0.75 — exactly when
the product's own page is missing from the pack, and nothing checked the
URL's shape. It surfaced through P18: a typed product whose barcode no
engine indexes got brand homepages from S2, and those filled the fetch
budget before S3 ran (`specs/retrieval.md` §5a.8). Re-scoring the existing
qa tree under the flag alone moved 99 selections, 95 of them to the *next*
about-page in the same pack (`colgate.com/en-gb/products`,
`oralb.co.uk/en-gb/support/…`) — the pack never contained the product. The
flag is therefore paired with the retrieval change: it is what lets
about-shaped candidates be recognised before they are fetched.

## 3. Comparing query to page — the same normalizer on both sides

The page gives a title and body text; the query gives `DescTokens`. Comparing
them needs both sides in the same shape, so **P3's parser runs on the page
title too**: `parse_size`, `parse_count`, `extract_variant_terms`.

Reusing P3 rather than writing a second parser is the point. A separate
page-side parser would drift from the query-side one, and then "size mismatch"
would sometimes mean "the two parsers disagree" — a difference invisible in
the output and impossible to debug from a score. It also means P3's measured
fixes (the `N x` claim-word guard, spelled-out units, Unicode tokenizing) apply
to page text for free.

## 4. Weighted features — `04` §9, every weight in config

`03` §4 stage 4's list: brand match, variant token overlap, format
consistency, retailer domain match, market signal.

**Market is a scored feature, never a filter.** `01` §5: the organizers' own
`sample_output` resolves a `FR,GB` item to an Amazon.in page, so a country
hard-filter rejects their reference answer. `04` §12 lists it as a forbidden
pattern. **[PROVISIONAL — Q4]**

Weights are config values with names (`config/match.yaml`), not literals in a
scoring function. They are **not yet tuned** — there is no instrument to tune
them against until the gold set grows, and inventing a fit against 5 URLs
would produce numbers that look measured and are not. They are set from the
stated ordering of evidence strength in `03` §4 stage 4 and marked as
untuned in the config.

## 5. `calibrated_prob` is NOT calibrated at P9, and that is dangerous unless stated

`03` §4 stage 4: "Raw scores are meaningless as confidence. Fit a calibration
map (isotonic or Platt) on the hand-labelled URL gold set so `calibrated_prob`
is an actual probability." That is P10.

Until then `calibrated_prob` **mirrors `raw_score`**. A field named
`calibrated_prob` holding an uncalibrated number is precisely the
plausible-wrong-value shape `05` §5 exists to name, so:

- a test asserts the two are **equal** at P9, which forces P10 to change that
  test deliberately rather than letting the fields quietly diverge;
- `τ_abstain` stays `0.0` in `config/thresholds.yaml` and nothing reads it;
- `τ_merge` write-back (§6) is gated on the **GTIN hard rule only** at P9,
  never on the uncalibrated score.

## 6. Registry write-back — gated on hard evidence only, for now

`03` §4 stage 4: a confirmed match "creates or updates a `CanonicalEntity`:
union this row's `row_uid` into an existing entity sharing the block key
(Union-Find merge), or create a new one".

P6 built the mechanism — `UnionFind`, `write_entities`, `append_audit` — and
deliberately left the *decision* to P9. P9 makes it, and makes it narrow:
**write-back fires only on a GTIN hard-rule accept.** `03` §4 stage 4 offers
two triggers, GTIN accept *or* `calibrated_prob ≥ τ_merge`, and the second
does not exist yet (§5). Writing back on an uncalibrated score would poison
the registry with merges no later lookup can distinguish from confirmed ones —
`05` §4, and the failure `03` §1a calls worse than a wrong single-row answer.

Every write is audit-logged (`05` §4), recording `row_uid`s and never
`nan_key`.

## 7. Files

```
config/match.yaml              weights, thresholds, negative-flag vocabulary
src/nimo/match/features.py     query x evidence -> MatchFeatures — pure
src/nimo/match/rules.py        the five hard rules — pure
src/nimo/match/score.py        weighted sum, ranking, Selection
src/nimo/match/writeback.py    GTIN-accept -> CanonicalEntity + audit
tests/match/                   adversarial cases + real fixtures
```

## 8. Acceptance criteria

1. Page GTIN == query GTIN (both valid) ⇒ accept, score 1.0, ranked first.
2. Page GTIN != query GTIN (both valid) ⇒ rejected regardless of text
   similarity.
3. A corrupt query barcode ⇒ `barcode_exact is None`, **never** a comparison
   against the rounded value.
4. Same brand, different size ⇒ demoted below the size-matching candidate.
5. Same product, different multipack count ⇒ demoted.
6. `refill` page for a non-refill query ⇒ demoted.
7. A candidate with `fetch_status != "ok"` and no evidence still ranks,
   last — it is not dropped (`03` §4 stage 3).
8. Market never filters; a cross-market candidate can still win (`01` §5).
9. `calibrated_prob == raw_score` at P9, asserted.
10. Write-back fires **only** on a GTIN accept, and audit-logs every write.
11. Every weight comes from `config/match.yaml`; no numeric literal in a
    scoring function (`04` §9).
12. Zero network, zero LLM.

## 9. Tests — `04` §8's adversarial set is the gate here

Beyond `04` §11:

- **The five adversarial cases `04` §8 names, by name**, each as its own test.
- **A conflicting-GTIN page that is textually near-identical** — the rule must
  beat the text, which is the whole reason it is a hard rule.
- **A page with no structured data at all** (the Amazon fixture: 1.4 MB, no
  JSON-LD, no OpenGraph).
- **Two retailers, one product, agreeing GTINs** (chemist-4-u +
  pharmazondirect) — both must rank above an unrelated page.
- **Determinism**: identical inputs ⇒ identical ranking, ties broken by URL.
- **`calibrated_prob == raw_score`**, so P10 must break it on purpose.
- **No write-back on a merely-high score**, only on a GTIN accept.

## 10. Definition of Done

`04` §11, plus `05` §6's registry items (this module writes to the registry):

- [ ] Every registry-writing path audit-logged (`05` §4)
- [ ] `04` §1's P9 row states what the gate could and could not measure —
  n=5 on the weighted path, 0 gold rows for the GTIN rule
- [ ] Decision-log entry for the gate limitation and the write-back narrowing
