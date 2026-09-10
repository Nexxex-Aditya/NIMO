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

## 1. Gate status — read this before trusting a recall number

`04` §1's P7 gate is "Recall@20 measured on gold set". **That measurement is
blocked here, for two independent reasons, and neither is fixable by writing
more code.**

1. **No live SearxNG.** `03` §4 stage 2 requires a self-hosted instance and
   forbids public ones ("rate limits and non-reproducibility"). Docker CLI
   29.7.2 and Compose v5.3.1 are installed on this machine, but the daemon is
   not running (`failed to connect to the docker API at
   npipe:////./pipe/dockerDesktopLinuxEngine`). `docker-compose.yml` and a
   pinned SearxNG config ship with this phase, so bringing it up is one
   command — but it has not been run, and no recall number has been produced.
2. **The gold set is 6 rows, 5 with URLs** (P4, partial by design). Recall@20
   over 5 URLs is not a measurement; it is an anecdote with a percentage sign.
   `specs/gold.md` is explicit that fabricating entries to reach a round
   number is worse than a missing one, and that reasoning applies just as
   hard to the phase that consumes them.

So this phase ships **everything that is verifiable without a live index** —
query construction, URL canonicalization, candidate merging, the client
wrapper against frozen fixtures — with the strategy-coverage measurements
below, which are real and were taken against all 824 rows. The recall number
is deferred, not estimated. Running it needs: `docker compose up -d searxng`,
then more gold rows labelled.

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
