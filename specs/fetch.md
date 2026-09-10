# specs/fetch.md — P8: Fetch & extract

Authority: `03-architecture.md` §4 stage `[3]`. Network discipline: `04` §6.
Security: `05` §2 (SSRF — **this phase owns it**), `05` §1 (untrusted content),
`05` §5 (cache staleness, aggregate domain block), `05` §6 (extra DoD items —
this is a fetch module, so all of them apply).

Depends on P7 (`CandidateURL`). Produces `CandidateEvidence` (`03` §3) for P9.

---

## 1. What the web actually gives us — measured before designing

Ten real UK oral-care product pages, one request per domain, 4s apart,
identifying UA. Captured to `tests/fixtures/pages/` (scrubbed, §6).

| retailer | status | usable? | structured data |
|---|---|---|---|
| chemist-4-u | 200 | ✅ | JSON-LD Product **nested in `@graph`**, 5 OG tags |
| pharmazondirect | 200 | ✅ | JSON-LD Product, 11 OG tags |
| wholedent | 200 | ✅ | JSON-LD Product, 11 OG tags |
| aquafresh (brand) | 200 | partial | 5 JSON-LD blocks, **one malformed**, no Product, 6 OG |
| amazon.co.uk | 200 | text only | **0 JSON-LD, 0 OG** on a 1.4 MB page |
| vita-point | 404 | — | (URL was stale; kept as a 404 fixture) |
| boots | 200 | ❌ | 6 KB JS shell, no content |
| ocado | 202 | ❌ | **0 bytes** |
| tesco | 403 | ❌ | bot wall |
| weldricks | 403 | ❌ | bot wall |

**Three findings that shape this phase and the ones after it:**

1. **JSON-LD `Product` is available on 3 of 10 pages.** `03` §4 stage 3 ranks
   it first, and that ordering is right — when present it carries `gtin13`,
   `brand`, `name`, `offers` in one place. But the *availability* assumption
   underneath P9's "GTIN hard rule" is 30%, not the near-universal thing the
   architecture reads as. P9 and P12 must work without it on most rows.

2. **Amazon — the largest retailer in the dataset — publishes neither JSON-LD
   nor OpenGraph.** 1.4 MB of HTML and nothing structured. For Amazon rows,
   evidence is body text and images only.

3. **Bot walls and JS shells are the majority failure mode**, not network
   errors: 4 of 10 returned 403 or an empty shell. `03` §4 stage 3 already
   says "a page that fails extraction gets `fetch_status` set and stays in the
   record. Do not drop it — a systematic block on one retailer is a finding,
   not noise." That is now empirically the *common* case, so the failure
   statuses are first-class output, not an error path.

**This is also direct evidence for Q6.** P4 found Tesco blocking a browser;
P8 finds Tesco, Weldricks, Boots and Ocado all unusable to a polite fetcher.
Whatever the organizers permit, roughly half of large UK retail is not
scrapable this way, which caps achievable coverage regardless of effort.

## 2. Fetch — `05` §2 is this phase's responsibility

P7 dropped candidates whose host was a private IP *literal*. P8 owns the rest,
and it needs the HTTP client's redirect chain to do it:

1. **Scheme allow-list** — `http(s)` only, re-checked here rather than trusted
   from P7.
2. **Resolve the hostname and reject private/reserved ranges before
   connecting.** A hostname that resolves to `127.0.0.1`, `169.254.169.254`
   (the cloud metadata endpoint `05` §2 names), or any RFC1918 address is
   refused. P7 could not do this without resolving every candidate it never
   fetches.
3. **Re-validate after every redirect hop.** `05` §2: "A page can return a 302
   to an internal address; checking only the candidate URL and trusting the
   redirect chain defeats the whole control." Redirects are therefore followed
   manually, one hop at a time, with the check applied to each `Location`.
4. **Max response size**, enforced while streaming — an unbounded or
   slow-drip response is a resource-exhaustion vector, not just a slow one.
5. **Hard connect and read timeouts**, both halves (`04` §6).

**Scoped, never global.** The CIS LLM endpoint is itself an RFC1918 address
(`10.249.224.116`, `config/models.yaml`). This validation applies to fetching
untrusted candidate URLs and must never become an outbound-traffic check, or
it blocks the pipeline's own model. Recorded here because P8 is where a global
check is most tempting.

## 3. Politeness — `03` §4 stage 3, and Q6 is unresolved

- **`robots.txt` honoured**, fetched once per host and cached. A disallowed
  path is `fetch_status="blocked"`, recorded, never fetched.
- **Per-domain rate limit** and a concurrency cap of 1 per host.
- **Identifying User-Agent** naming the project.
- **Retries:** exponential backoff with jitter, max 3, on 5xx/timeout only.
  **Never on 404 or 403** — they fail identically every time, and a 403 from a
  bot wall retried three times is three times the rudeness for the same
  answer.

## 4. Cache — content-addressed, TTL-bounded

`03` §4 stage 3: "Content-addressed disk cache. Key: canonical URL. Re-runs
must never re-crawl. This is non-negotiable — it makes stages 4–8 iterable in
seconds."

Same shape as P7's search cache and for the same reasons. `05` §5 forbids an
infinite TTL ("a retailer updates a listing; the cache keeps serving the old
page forever"), so entries expire and `content_hash` makes a change visible.

**Failures are cached too**, with a shorter TTL. Re-requesting a 403 bot wall
on every run is pure rudeness for a known answer.

## 5. Extract — the cascade, and what the measurements change

`03` §4 stage 3's priority order stands. What the measurements add:

1. **JSON-LD `schema.org/Product`** — highest value.
   - **Must traverse `@graph`.** chemist-4-u's Product is nested inside an
     `ItemPage`/`WebPage` `@graph`; a top-level `@type == "Product"` check
     finds nothing there.
   - **Must tolerate a malformed block among good ones.** aquafresh has 5
     blocks and one fails to parse. One bad block is a parse warning, not a
     failed page.
   - `@type` may be a **list** (`["ItemPage","WebPage"]`), not a string.
2. **Microdata / RDFa** — measured absent on all 10, kept because `03`
   requires it and its absence here is a sample of ten, not a proof.
3. **OpenGraph** — present on 4 of 10 and the most reliable single source of
   title and image.
4. **Boilerplate-stripped body text** via `trafilatura` — the only evidence
   for Amazon.
5. **Image URLs** — primary pack-shot heuristic: largest, in-gallery,
   non-icon.

Every parse problem appends to `parse_warnings` rather than raising: a page
that yields partial evidence is more useful than one discarded, and `03` §3
gives the field for exactly this.

## 6. Fixtures — `04` §8, and the scrubbing `04` §9 requires

`tests/fixtures/pages/` holds all ten pages **including the bot walls and the
empty shell**, because a fixture set containing only the pages that worked
would misrepresent what the fetcher faces. `manifest.json` records the URL,
status and captured/committed sizes for each.

**Scrubbed in two passes, and the second was necessary.** Stripping every
`<script>` except `ld+json` removed tracking and cut 3.0 MB to 2.1 MB. A
verification pass then found **live Amazon session ids and CSRF tokens
surviving in data attributes, JSON blobs and hidden inputs** — 45 copies of
one session id. Key-targeted patterns kept missing copies, so redaction is
**shape-based**: the session-id format, long base64 blobs, request ids. Final
state: zero session ids, zero base64 blobs, 410 redaction markers, 1.9 MB.

`04` §9 is absolute on this ("no credentials, API keys, cookies, or session
tokens in the repo, in fixtures, in logs"), and near-miss is miss.

## 7. Files

```
config/fetch.yaml                timeouts, rate limits, size cap, cache TTLs, UA
src/nimo/fetch/guard.py          SSRF: scheme, DNS, private ranges, per-hop
src/nimo/fetch/robots.py         robots.txt fetch + cache + check
src/nimo/fetch/cache.py          content-addressed page cache
src/nimo/fetch/client.py         the fetcher — manual redirects, size cap
src/nimo/extract/jsonld.py       @graph traversal, malformed-block tolerance
src/nimo/extract/page.py         the cascade -> CandidateEvidence
tests/fetch/, tests/extract/     mirrors; fixtures only, zero network
```

## 8. Acceptance criteria

1. A URL resolving to a private/reserved range is refused **before connecting**.
2. A redirect to a private address is refused **at that hop**, not after.
3. A response exceeding the size cap is abandoned mid-stream.
4. `robots.txt` disallow ⇒ `fetch_status="blocked"`, no request to the path.
5. 404/403 are never retried; 5xx/timeout are, with jitter, max 3.
6. A cache hit issues no request; entries expire.
7. JSON-LD Product is extracted from **`@graph`-nested** markup (chemist-4-u).
8. A malformed JSON-LD block among valid ones yields a `parse_warning`, not a
   failure (aquafresh).
9. A bot wall yields `CandidateEvidence` with `fetch_status` set and the
   record retained (tesco, weldricks).
10. Amazon's fixture yields body text with no JSON-LD and no OG, and that is a
    success path, not an error.
11. **Zero network in tests** (`04` §6); fixtures only.
12. `data/raw/` never written.

## 9. Definition of Done

`04` §11, plus **all of `05` §6** (this is a fetch module):

- [ ] Untrusted content delimited/labelled wherever it reaches a prompt — not
  yet applicable, no LLM call in this phase, but `body_text` becomes prompt
  input at P11 and must carry that framing then
- [ ] Fetcher rejects non-http(s) and private ranges, **including after
  redirects**
- [ ] Cache TTL is finite (`05` §5)
- [ ] Per-domain success rate available for the run summary — the aggregate
  domain block in `05` §5 is now measured fact, not hypothesis
- [ ] Decision-log entry for the coverage findings in §1
