# specs/retrieval.md — P7: Candidate generation

Authority: `03-architecture.md` §4 stage `[2]`. Network discipline: `04` §6.
Security: `05` §2 (URL validation), `05` §5 (aggregate domain block).

Depends on P2, P3, P6a. **This is the first phase that touches the network**,
so `04` §6 becomes live: zero network calls in tests, one HTTP client wrapper,
timeouts always set, backoff with jitter, cache-first.

Reached only on a stage-1 registry miss (`03` §4 stage 2). On a cold registry
that is every row, which the P6a runner already reports honestly as
`tier2_retrieval: 412`.

---

## 1. Gate status — the number is void, and why matters more than the number

`04` §1's P7 gate is "Recall@20 measured on gold set". **It has now been run
against a live index, and the result must not be reported as a recall rate.**

### 1a. What the live run actually measured

SearxNG came up (Docker 29.7.2, image pinned by digest) and the full path
worked end to end: queries built, index queried, results canonicalized,
merged, capped. The first few queries returned exactly what they should —
`aquafresh whitening pump 100ml` yielded four real retailer product pages.

Then the results turned to noise: massage services, `cisa.gov`, `zhihu.com`,
a Hyderabad shopping mall. SearxNG's own response said why:

    unresponsive_engines: [["duckduckgo", "CAPTCHA"],
                           ["google", "Suspended: CAPTCHA"]]

**Two of three engines were CAPTCHA-blocked after a few dozen queries from a
single IP**, and the third (Bing) was returning `instagram.com` for
`curaprox aligner care foam`. The measured "Recall@20 = 1/5" is a measurement
of rate limiting, not of retrieval, and is recorded here only so nobody
re-derives it and believes it.

### 1b. The three findings that came out of it, which are worth more

1. **The client ignored `unresponsive_engines`.** SearxNG answers HTTP 200
   with a full-looking `results` list while blocked, reporting the fact only
   in that field. A degraded run was therefore indistinguishable from a
   healthy one — `05` §5's "aggregate domain block" exactly: every request
   succeeds, the systemic pattern is invisible. Now: all engines blocked
   raises `SearchError`; partial degradation logs a named warning.
2. **S3 omitted the product-type noun**, on 171 of 412 `dev` rows. §2a.
3. **A YAML boolean had silently disabled a stopword.** §2a.

### 1c. What this means for the architecture, and it is not small

`03` §4 stage 2 assumes SearxNG can serve candidate generation for 412 rows.
Measured, a single IP gets CAPTCHA-blocked by Google and DuckDuckGo within a
few dozen queries. **412 rows × 3–5 strategies is 1200–2000 queries.** At the
observed block rate that run cannot complete against those engines, and the
`min_interval_s: 0.25` politeness delay is nowhere near enough.

This is direct evidence for **Q6** ("Is scraping permitted, and are there
rate/robots constraints for the demo?") and it needs an answer before P7's
gate can be closed honestly. The options, none of which is free:

- **A paid search API** (Brave, Serper, Bing Web Search). Costs money, but is
  the only option that reliably serves 2000 queries and is designed to be
  queried automatically.
- **Engines that tolerate automation** — SearxNG can be configured toward
  sources that do not CAPTCHA. Lower result quality, unknown coverage of UK
  retail.
- **Drastically reduced scope for the demo** — `04` §1's P15 gate is "runs
  end-to-end on 10 sample rows", which ~30 queries can serve. This works for
  the demo and does not scale to a full `qa` submission.
- **A long crawl with heavy backoff**, hours rather than minutes, checkpointed
  through the P6a runner's resume path (which exists and works).

**Resolved in §5a, and the answer was engineering rather than spend.** A
measured engine portfolio, a per-engine circuit breaker, early exit on a
full candidate cap, and a cache-first client take a full `qa` run from
"blocked within a few dozen queries" to ~42 minutes cold and effectively
free thereafter. The paid API stays as insurance against all three
portfolio engines correlating in a block — not as the plan. `03` §7's
"rejected alternatives" still does not mention paid APIs, and now does not
need to.

### 1d. The other blocker, unchanged

**The gold set is 6 rows, 5 with URLs.** Recall@20 over 5 URLs is not a
measurement even with healthy engines. Worse, the live run showed the metric
itself is questionable: for `dev:410` retrieval surfaced
`vita-point.co.uk/eucryl-toothpowder-...-freshmint-50g` and
`pharmazondirect.com/products/eucryl-toothpowder-freshmint-flavour-50g` — both
apparently the correct product — while the gold label names
`chemist-4-u.com`. **Scoring "did we find *the* labelled URL" penalises
finding an equally valid page on a different retailer**, which `01` §5 already
hinted at when the organizers' own reference answer resolved a GB item to
Amazon.in. Whatever replaces this gate should score *the product*, not the
URL string.

## 2. Query strategies — measured coverage

`03` §4 stage 2's five strategies, and how often each can actually fire:

| # | Strategy | Query shape | `dev` | `qa` |
|---|---|---|---|---|
| S1 | Barcode exact | `"5014697056627"` | **18** (4%) | **412** (100%) |
| S2 | Barcode + brand | `5014697056627 aquafresh` | 18 | 412 |
| S3 | Brand + variant + size | `aquafresh whitening pump 100ml` | 225 | 220 |
| S4 | Site-restricted | `site:boots.com aquafresh whitening 100ml` | 223 (54%) | 256 (62%) |
| S5 | Desc verbatim | `desc_clean` | 412 | 412 |

**S1/S2 use `barcode_valid`, not merely "not corrupt", and the difference is
most of the strategy on `dev`.** 35 `dev` rows survive the rounding defect, but
`01` §3 measured that only **18** of those are valid GTIN lengths — the other
17 are 6–7 digits (`266611`, `1071580`) and are not GTINs at all. Searching a
non-GTIN as if it were one returns unrelated results with no error anywhere,
which is a latent failure (`05` §5), so the strategy is gated on
`nimo.loader.barcode_valid`.

**The dev/qa asymmetry is the thing to design around, and it is severe.**
`03` §4 stage 2 already warns "do not tune retrieval on dev alone — it will
over-fit to the no-barcode path and silently regress on qa where barcodes are
clean." Measured, that warning is stronger than it reads: the single most
decisive strategy is available on **4% of `dev` and 100% of `qa`**. Any
tuning done against `dev` is tuning the fallback path exclusively.

S4 needs a retailer→domain mapping. `config/retailers.yaml` maps **28 of 50**
retailers to a domain; the rest are marketplaces, panels or aggregators with
no single product domain, and `03` §4 stage 2 says unmapped retailers skip S4.
That is why S4 reaches only ~54–62% of rows.

## 2a. Two defects the live run exposed in query construction

**S3 omitted the product-type noun.** P3 extracts `toothpaste`, `mouthwash`,
`toothbrush`, `foam`, `spray` into `format_hints`, not `variant_terms`, so an
identity phrase built from brand + variants + size drops the single most
search-relevant word. Measured: 252 of 412 `dev` rows carry at least one hint
and **171 had one silently omitted** from their query. Live, before the fix:

    dev:68  "ultradex one go mouthwash on the go liquid sachets, 10 x 15ml"
            -> S3 "ULTRADEX one go on liquid 15ml"        (no "mouthwash")
    dev:92  "curaprox aligner care foam 40 ml"
            -> S3 "CURAPROX aligner care 40ml"             (no "foam")

The first returned Stack Overflow and Server Fault results, because
"one go on liquid" is not a product query. `_identity_phrase` now includes the
hints. `dev:37`'s gold URL moved from rank 3 to rank 1 as a result.

**A YAML boolean had disabled a stopword since P3.** `config/normalize.yaml`
listed `- on` unquoted, and **YAML 1.1 parses bare `on` as the boolean
`True`** (as it does `off`, `yes`, `no`). `vocab.py` stringified it to
`"true"`, so the stopword set contained `"true"` and the word `on` was never
stripped — visible in `dev:68`'s variant terms as `['one','go','on','liquid']`.

This is `05` §5's "type coercion across a serialization boundary" — the same
class as the `EXTERNAL_CODE` rounding defect — occurring in our own config
rather than the organizers'. Two fixes, because the value alone is not enough:
the entry is quoted, **and** `vocab.py` now raises on a non-string entry
rather than stringifying it, so the next one fails at load instead of
degrading silently. A scan of every `config/*.yaml` found no other instance.

## 3. URL canonicalization

`03` §4 stage 2: "Canonicalize URLs before dedup: lowercase host, strip
`utm_*`, `gclid`, fragments, trailing slash, session params."

Implemented exactly, plus one addition `01` §13 requires: **normalize
lookalike Unicode characters**, because `sample_output`'s `PRODUCT_URL`
contains a `U+2011` non-breaking hyphen. A canonicalizer that treats it as a
literal character silently produces a URL that resolves nowhere and dedups
against nothing.

Rules, in order:
1. NFKC-normalize, **then explicitly fold the dash family to ASCII `-` and
   delete invisible formatting characters.** NFKC alone is not enough, and
   this was found by testing rather than assumed:
   `unicodedata.normalize("NFKC", "‑")` yields `‐` (HYPHEN), not
   ASCII `-`. The whole `U+2010..U+2015` range, `U+2212` MINUS SIGN and
   `U+00AD` SOFT HYPHEN all survive NFKC as non-ASCII, so the `U+2011` `01`
   §13 actually found would still produce a URL that resolves nowhere. Only
   `U+FE63` and `U+FF0D` fold to ASCII on their own. Invisible characters
   (`U+00AD`, `U+200B`–`U+200D`, `U+FEFF`) are **deleted** rather than folded —
   they carry no meaning in a URL and survive copy-paste from rendered pages,
   and folding them to a visible character would corrupt the path.
2. Reject non-`http(s)` schemes outright (`05` §2).
3. Lowercase scheme and host; strip a leading `www.`; drop the default port.
4. Drop the fragment entirely.
5. Drop tracking and session parameters: `utm_*`, `gclid`, `fbclid`, `msclkid`,
   `mc_cid`, `mc_eid`, `_ga`, `ref`, `sessionid`, `sid`, `phpsessid`.
   **Kept:** every other query parameter, because on real retailer sites
   `?variant=`, `?sku=` and `?size=` are the difference between two products,
   and stripping them would merge a 75ml and a 100ml listing into one
   candidate — the same identity error the whole matcher exists to avoid.
6. Strip a trailing `/` from a non-empty path.
7. Sort the surviving query parameters, so two orderings of the same URL dedup.

## 4. Candidate safety — scoped, not global

`05` §2's controls belong to the fetcher (P8), which re-validates after every
redirect hop. What P7 owns is the cheap front gate: a candidate URL that is
not `http(s)`, or whose host is an IP literal in a private/reserved range, is
dropped **at the point it enters the pipeline** rather than carried to P8.

**This check is scoped to candidate URLs from search results and must never
become a global outbound-address check.** The CIS LLM endpoint is itself an
RFC1918 address (`10.249.224.116`, `config/models.yaml`), so a global guard
would block the pipeline's own model. That interaction is already recorded in
`02-decision-log.md`; it is repeated here because P7 is where the tempting
place to put a global check first appears.

Hostname resolution and post-redirect re-validation stay in P8: they need the
HTTP client's redirect chain, and doing DNS at query time would mean resolving
every candidate before deciding to fetch it.

## 5. The SearxNG client

- **Self-hosted, pinned image tag**, via `docker-compose.yml`. Never a public
  instance (`03` §4 stage 2).
- One `httpx` client wrapper, per `04` §6: connect and read timeouts always
  set, max 3 retries with exponential backoff and jitter, retry only on
  5xx/timeout, never on 4xx.
- Base URL comes from `SEARXNG_BASE_URL` in `.env`, validated present at
  startup (`04` §9) — `settings.py` already requires it.
- Results are parsed into `CandidateURL` (`03` §3) carrying `source_query`
  (which strategy produced it) and `engine`, because `03` §4 stage 2 merges
  results across strategies and the provenance is what makes a bad strategy
  visible later.

## 5a. Making free engines work as primary — measured

`03` §4 stage 2 assumes SearxNG can serve candidate generation for 412 rows.
The first live run showed it cannot, naively: Google and DuckDuckGo
CAPTCHA-blocked a single IP within a few dozen queries (§1a). A paid search
API is the obvious escape, and it is the *backup*, not the answer. Four
engineering changes make the free path work, each measured.

### 5a.1 Engine portfolio, chosen by measurement not reputation

Four real product queries per engine, paced 2s apart so the probe would not
cause the blocking it was measuring:

| engine | blocked | results/query | relevant |
|---|---|---|---|
| **brave** | 0/4 | 20.0 | **95%** |
| ~~startpage~~ | — | — | **does not exist in this build** — the 91% recorded here was the default fallback set, see §5a.5c |
| ~~bing~~ | 0/4 | 10.0 | 25% — **removed, see §5a.5b: answers a different query entirely** |
| mojeek | 0/4 | 0.0 | — (enabled; returns nothing for UK retail) |
| duckduckgo | **4/4** | — | CAPTCHA |
| qwant | **4/4** | — | CAPTCHA |
| google | **4/4** | — | Suspended: CAPTCHA |

Google, DuckDuckGo and Qwant are excluded regardless of their reputation for
result quality. **An engine that stops answering partway through a 400-row run
is worse than one that never answered, because the run looks like it worked.**
Bing earns its place on independence, not relevance. Mojeek was enabled in the
instance specifically for index diversity and measured at zero results — kept
in the record rather than silently dropped.

**No single free engine is reliable, and that is the design constraint.** In a
later probe Brave — the best-scoring engine here — began CAPTCHA-ing after
about six queries. What kept that run producing candidates was Startpage and
Bing continuing. Hence a portfolio with a breaker, not a preference list.

### 5a.2 Per-engine circuit breaker

`04` §6 already required one ("N consecutive failures on a domain → stop
hitting it, record the fact, continue with other domains"); the unit that gets
blocked is the **engine**. Three consecutive CAPTCHAs opens that engine's
circuit for 15 minutes while the others carry the run. A success clears the
streak, so a flaky engine is not confused with a blocked one, and recovery is
half-open so one failure after a cooldown does not immediately re-open it.

A CAPTCHA is not a transient error — it means "come back later" — so this
cooldown is minutes, unrelated to the sub-second retry backoff for a flaky
response. When **every** engine is broken the client raises: "no engine
answered" and "no results exist" are different facts and only one is about the
product (`04` §4).

### 5a.3 Early exit once the candidate cap is full

The largest lever on budget. Stop issuing strategies for a row once the
candidates that will actually be consumed are collected — every further
strategy spends a query on candidates that would be discarded anyway.
**Superseded in one detail by §5a.7:** the threshold is `fetch_budget`, not
`max_candidates`, because under strategy-major ordering the fetched set is
fixed once that many exist.

Cross-row query deduplication was measured and **deliberately not built**:
1904 of 1904 `qa` queries are distinct, because S5 is the verbatim description
and S3 carries per-row variant terms. It would have bought nothing. Measuring
before building saved that work.

### 5a.4 Cache-first (`04` §6)

Content-addressed by (query + engine set), TTL-bounded because `05` §5 forbids
an infinite one. A hit issues no request, so it cannot be blocked, rate
limited, or fail partway. The engine set is part of the key deliberately: the
same query against `[brave, startpage]` and `[bing]` are different questions,
and serving one for the other would make a degraded run look like a healthy
cached one.

### 5a.5 What it adds up to — measured on 12 real `qa` rows

    strategy calls made : 37   (naive, all strategies: 51)
    candidates collected: 240  = 20.0/row — the cap filled on EVERY row
    cold wall time      : 72.4s
    warm wall time      : 5.3s (7%), byte-identical candidates
    engines broken      : brave x1, and the run continued on the other two

Full 412-row `qa` projection: **~1270 queries, ~42 minutes cold, then
effectively free.** The saving is short of the ideal because Brave dropped out
partway and fewer results per query means more strategies are needed to fill
the cap — the portfolio and early exit interacting as designed.

**42 minutes for a run that completes, caches and resumes is the answer.** The
second run costs 7% of the first, so iterating on the matcher and running the
demo are both effectively free.

### 5a.5b Correction — that measurement was counting the wrong thing

**"240 candidates, 20.0/row, the cap filled on every row" was reported as
success. It was not.** Inspecting the cached candidate lists afterwards showed
them dominated by Stack Overflow, VAT-lookup directories, court records,
Wikipedia and adult sites — 30-44% obviously junk across every strategy.

The cause was **Bing returning results for an entirely different query** while
reporting as perfectly healthy:

    "sensodyne pronamel toothpaste 75ml"  -> news.mit.edu/topic/artificial-intelligence
    "CURAPROX aligner care foam 40ml"     -> bilibili.com/video/BV1e2421L73V
    '"5014697056627"'                     -> en.akinator.com
    "aquafresh whitening pump 100ml"      -> support.microsoft.com/fix-bluetooth-problems

No CAPTCHA, no error, no unresponsive-engine entry — so the circuit breaker
could not see it, and with early exit filling a 20-candidate cap, Bing's noise
crowded out Brave's genuine results and stopped the cascade before it reached
a text strategy. **A silently-wrong engine is worse than a blocked one.**

Two things follow, and the second matters more than the first:

1. **Bing is removed.** The probe had already scored it 25% relevant and it
   was kept "on index independence". 25% relevance should have been read as
   75% noise, not as a diversity benefit.
2. **The success metric was quantity, and quantity cannot see this.** A count
   of candidates is satisfied equally by twenty product pages and twenty
   Bluetooth support articles. `brand_signal_rate` (`search.py`) is the cheap
   replacement: the fraction of candidates whose URL or title mentions the
   brand. It does not establish that a candidate is the right *product* —
   that needs P8's page evidence and P9's matcher — but
   `support.microsoft.com/fix-bluetooth-problems` scores 0 for an `AQUAFRESH`
   row and no amount of threshold tuning rescues it.

**Also learned about the budget, the hard way.** After this round of probing,
Brave and Startpage both returned zero results — the measurement activity
itself exhausted them. The free portfolio has a real daily budget, not just a
per-minute rate. That reinforces the cache (a warm run costs nothing) and the
long-pacing choice, and it is the honest argument for keeping a paid API
available: not because free engines return bad results, but because there are
only two of them left and they are exhaustible.



### 5a.6 The paid API is the backup, and the seam is already there

`merge_candidates` takes a `SearchFn` — `(SearchQuery, int) -> list[
SearchResult]` — so a paid backend is a new implementation of that callable
plus a key in `.env`, not a change to query construction, canonicalization,
merging or the cap.

**No paid backend is implemented, deliberately.** There is no key to test
against, `04` §6 forbids network in tests, and a client written against
documentation rather than a live endpoint is precisely the class of
fabricated-but-plausible code that produced the invented Docker tag earlier in
this project. `config/retrieval.yaml` records the four steps to add one.

### 5a.5c Correction — `startpage` was never an engine

There is no engine called `startpage` in this SearxNG build. SearxNG does not
error on an unknown engine name; it **silently falls back to its default
set**, Bing included. So the "startpage: 91% relevant" row above measured the
fallback set and recorded it under the wrong name, and for the whole time it
was configured the pipeline queried `[brave] + defaults`. That is why Bing's
junk survived being removed from config.

Fixed structurally: `_assert_engines_honoured` raises if any result carries
an engine tag that was not requested. Re-measured with tags verified:
**`google cse` 87% (60/60 tagged), `duckduckgo` 82% (40/40)**, brave
suspended from probing, mojeek 0%. `engines: [google cse, duckduckgo, brave]`.

### 5a.7 Making the free portfolio carry a full `qa` run — no paid key exists

**Measured 2026-09-11, after the P10 harvest:** 8 rows per cooldown window
before all three engines circuit-broke, then the remaining 404 rows failed at
`retrieve` in 137 seconds. And there is no paid search key — that option is
closed, not deferred. So the free path has to carry the submission run, and
three things about the 2026-09-11 design were spending the budget badly.
Each was measured from the 8 rows' own artifacts before anything changed:

**1. Half of every row's queries bought candidates that were never fetched.**
The candidate list is ordered `(strategy order, rank)` and capped at 20, and
the runner fetches the first 8. Under strategy-major ordering, **once 8 safe
unique candidates exist, no later strategy can enter the fetched set** — its
results sort after every earlier strategy's. Measured: S3 and S5 ran on all 8
rows, produced 86 candidates, and **0 of the 86 were fetched**. The early-exit
threshold is therefore `fetch_budget`, not `max_candidates`: that is the
exact point past which a further query provably cannot change the outcome,
not a heuristic. `fetch_budget` moves from a constant in `run/__main__.py`
into `config/retrieval.yaml` (`04` §9), and `max_candidates` stays as the hard
cap on the recorded list.

What that gives up: on `qa`, S3/S5 rarely run. The artifacts say that is
cheap — their unfetched candidates were `elle.com`, `sec.gov`,
`pmc.ncbi.nlm.nih.gov`, `kinoteater.ee`, `worldradiohistory.com`: the
retailer-abbreviation soup from §2a producing junk text queries, as logged.
The four UK pharmacies S3 found for `qa:6` are the real loss and are
recorded here rather than hidden. `early_exit: false` still forces every
strategy for a recall experiment.

**2. Every request hit all three engines at once, so all three exhausted in
lockstep.** The unit that gets rate-limited is the engine, per IP, per time.
`engine_mode: rotate` sends each query to **one** engine, cycling through the
available ones, so each engine sees a third of the request rate for the same
`per_strategy_limit: 8` results per query — one engine returns 8-10, and the
limit was already 8.

The rule that makes rotation safe rather than lossy: **an empty answer from
one engine is not evidence about the others, so on empty the next available
engine is tried.** Measured: bare-barcode (S1) results come from `google cse`
11 times in 13; DuckDuckGo indexes few of them. Without the rule, rotation
would hand S1 to DuckDuckGo on two rows in three and lose the strategy that
produced the only GTIN hit (`qa:5`). With it, per engine the worst case
(every engine asked once) costs exactly what the portfolio costs today, and
the common case costs a third. Empties are cached per engine so a re-run
does not re-ask.

The cache key stays `(query, engine set)`; under rotation the set is one
engine, and a lookup consults every configured engine's entry so a warm
re-run hits regardless of which engine happened to answer.

**3. A fully-broken portfolio failed the rest of the run in seconds.** Right
for a foreground run; wrong for an unattended one, and unattended is the only
way 412 rows get done on free engines. `wait_for_cooldown: true` makes the
client sleep until the earliest engine reopens, then continue. Bounded:
`max_cooldown_waits` consecutive waits with **no successful query in between**
raises, and every later call raises immediately — a portfolio that has been
silent for an hour is a run to stop and look at, not to keep waiting on. The
sleep is injected like the clock (`04` §5), so the wait is tested without
sleeping.

**4. S1 moves last — found by the live check of (1)-(3).** Two fresh rows
through the rotated, early-exiting client: `qa:9` resolved in one query (S2
on DuckDuckGo → `romystore.co.uk`, JSON-LD GTIN equal → write-back, the
second registry entity). `qa:8` (`HTC` dental floss) went S1 → Brave → **8
pages that merely contain the digit string** (`callchecker.co.uk/prefix/
0750006`, `eveandersson.com/pi/digits/1000000`), which filled the fetch
budget and stopped S2 from running. Measured from the search cache over all
10 rows: S2 returned brand-bearing results on every row it ran; S1 was empty
on 5, returned 1-2 on 3 (all also in S2's list, including the `qa:5` GTIN
page it had only "owned" by provenance order), and returned junk on 1. S1 is
dominated by S2 and is now last: `strategy_order: [S2, S3, S4, S5, S1]`.
`03` §4 stage 2 corrected.

**Projection, to be replaced by measurement:** (1) roughly halves queries per
row; (2) triples per-engine budget; together ~6x rows per window, i.e. 412
rows in ~10 windows (~2.5 hours) rather than ~52. The number that matters is
rows per window *measured from the trace of the next full run*, and until it
exists this section is a projection — the same status the "~42 minutes"
projection had before it was measured and found wrong.

## 6. Merging and the candidate cap

`03` §4 stage 2: "Target 10–20 unique candidates. Cap hard; more costs fetch
budget for no gain."

Strategies run in order S1 → S5 and results merge, deduplicated by canonical
URL. **First strategy to produce a URL owns its provenance** — a URL found by
both S1 and S5 is recorded as S1's, because that is the stronger signal and
the one worth knowing about when a candidate turns out right.

Rank is preserved per strategy and the merged list is ordered by (strategy
order, rank within strategy), so a barcode-exact hit outranks a verbatim-text
hit regardless of what the engine thought.

## 7. Files

```
docker-compose.yml                pinned SearxNG, JSON format enabled
config/searxng/settings.yml       instance config
config/retrieval.yaml             cap, per-strategy limits, timeouts, retries
src/nimo/retrieval/queries.py     S1..S5 construction — pure
src/nimo/retrieval/canonical.py   canonicalization + candidate safety — pure
src/nimo/retrieval/client.py      the one HTTP wrapper (`04` §6)
src/nimo/retrieval/search.py      strategy orchestration, merge, cap
tests/retrieval/                  mirrors the above; fixtures, zero network
```

## 8. Acceptance criteria

1. Every strategy's coverage matches §2 on the real sheets.
2. S1/S2 fire only when `barcode_valid`, never on the 17 short non-GTINs.
3. Canonicalization is idempotent: `canonical(canonical(u)) == canonical(u)`.
4. Every dash in `U+2010..U+2015` and `U+2212` folds to ASCII `-`, and the
   result is ASCII; invisible characters are deleted.
5. `?variant=` survives canonicalization; `?utm_source=` does not.
6. Private-range and non-http(s) candidates are dropped at the gate.
7. The merged candidate list is capped, deduped by canonical URL, and ordered
   by strategy then rank.
8. **Zero network calls in any test** (`04` §6).
9. `data/raw/` never written.

## 9. Definition of Done

`04` §11, plus `05` §6's items for a network-touching module, plus:

- [ ] `04` §1's P7 row states the gate is **deferred with reasons**, not met —
  no recall number is reported until a live index and a larger gold set exist
- [ ] Decision-log entry recording the blocker and the `barcode_valid` gating
