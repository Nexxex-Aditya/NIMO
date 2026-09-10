# specs/registry.md — P6: Canonical Entity Registry & blocking

Authority: `03-architecture.md` §1a, §4 stage `[1]`, §6 L6. Security:
`05-security-safety.md` §4 (registry write audit log), §5 (registry
poisoning). Build standards: `04-build-standards.md`, and this phase is one
of the HARD-20% areas `04` §13 singles out for extra rigor — a wrong merge is
the one error in this design that corrupts every future row rather than one.

Depends on P2 (`RawRow`), P3 (`DescTokens`). Independent of P5 and of
everything downstream. **No network, no LLM.**

Every number below was measured against the real 412-row `dev` and `qa`
sheets before the spec was written. The most important measurement is a
negative one — §4.

---

## 1. What this phase builds

Four things, and one thing it deliberately does not:

1. **Block-key computation** — `BlockKey` from a row (`03` §4 stage 1 step 1).
2. **Tier 0 / Tier 1 lookup** against a persisted registry, producing
   `RegistryLookupResult`.
3. **A Union-Find match graph** over confirmed-same rows, so "these N rows
   are one product" is computed by disjoint-set union rather than learned.
4. **A persisted, audit-logged store** of `CanonicalEntity` records.

**Not built here: the write-back decision.** `03` §4 stage 4 places
registry write-back inside the matcher, gated on a hard GTIN accept or
`calibrated_prob ≥ τ_merge` — both of which are P9/P10 artifacts that do not
exist yet. P6 supplies the mechanism (`merge`, `upsert`, the audit log) and
the thresholds file entry; P9 decides when to call it. Building the decision
here would mean inventing a confidence signal to gate it on.

## 2. Blocking — measured

Block key, per `03` §4 stage 1:

- clean, non-corrupt `barcode` → `BlockKey(key=barcode, method="exact_gtin")`,
  for Tier 0
- **additionally**, whenever a size was parsed →
  `BlockKey(key=fingerprint(brand, size_ml_equiv, size_g_equiv, count),
  method="fingerprint")`, for Tier 1

**A row gets both keys where it has both.** `03` §4 stage 1 step 1 originally
said "clean barcode when present, *else* a fingerprint", and that `else` was
measured to be a real defect during this phase: `qa` carries a clean barcode
on 412 of 412 rows, so under an either/or rule no `qa` row ever receives a
fingerprint key and **Tier 1 is unreachable for the whole evaluation set** —
while 0 of those GTINs appear in `dev`, so Tier 0 misses all 412 too. The
cascade would have degraded to "always Tier 2" on the only sheet that gets
submitted, and the 61.8% figure below — cited by `01` §14, `03` §1a and `04`
§1's gate alike — would have been unreachable in the real pipeline. `03` §4
stage 1 has been corrected.

A row with **no size at all gets no fingerprint key and is not blocked.**
Measured: 225 of 412 `dev` rows and 220 of 412 `qa` rows carry a parsed size.
Blocking the other 187 on `brand + count` alone would put every unsized
Colgate row into one block — over-broad blocking is the failure this design
is most exposed to (`03` §1a), so an unsized row simply misses to Tier 2.
That is a real coverage limit, stated rather than papered over.

Measured on the real sheets:

| | value |
|---|---|
| sized `dev` rows | 225 |
| distinct `dev` fingerprint blocks | 130 |
| blocks holding more than one row | 29 |
| `dev` rows that repeat an earlier `dev` row | 95 |
| blocked `dev` pairs | 379 |
| **sized `qa` rows blocking against a `dev` fingerprint** | **136 / 220 = 61.8%** |

That 61.8% is `04` §1's block-hit-rate gate number and it reproduces `01`
§14's independently measured ceiling exactly.

Block sizes are long-tailed like everything else here: 101 blocks hold one
row, and the largest holds 14 (`('SENSODYNE', 75.0, None, 1)`).

## 3. Tier 0 — correct, and structurally dead on this dataset

Tier 0 is an exact clean-GTIN match against the registry. Measured:

| | value |
|---|---|
| clean `dev` barcodes | 35 |
| clean `qa` barcodes | 412 |
| barcodes shared between `dev` and `qa` | **0** |
| duplicate barcodes **within** `qa` | **0** (412 clean, 412 distinct) |

**Tier 0 has zero opportunities to fire anywhere in this dataset in a single
pass.** Not "rarely" — zero. `03` §1a already established that the apparent
dev/qa overlap was a rounding artifact (`01` §14); this measurement completes
that picture from the barcode side.

This is not a reason to delete Tier 0, and the distinction matters:

- **Within one run**, Tier 0 cannot fire, because no two rows in this dataset
  share a clean GTIN.
- **Across runs**, it fires on everything. `03` §5's warm-start property says
  the registry persists to `data/registry/`, so a second pass over `qa` after
  a first pass resolved it hits Tier 0 on **412 of 412 rows**, skipping
  stages 2–4 entirely.

So the honest demonstration of `03` §1a's efficiency claim on this data is a
**re-run**, not a single pass, and the P6 gate reports it that way. In
production, where the same catalog is re-audited, the re-run case is the
normal case — which is exactly what the registry exists for.

## 4. Tier 1 — the negative result, and why `τ_ann` is set the way it is

Tier 1 scores a row against other entities *inside its block* and merges above
`τ_ann`. `03` §4 stage 1 step 3 specifies the identity signal: **brand +
variant terms + size + count, never page content.** Within a block, brand,
size and count are equal by construction — so what actually discriminates is
the variant text, and Tier 1's whole accuracy rests on it.

### 4a. A block is overwhelmingly *not* one product

`01` §14 and `03` §1a both say the fingerprint is a blocking key and not a
match key. Measured, the effect is much larger than those documents imply.
The `('SENSODYNE', 75.0, None, 1)` block holds 14 rows:

    daily care gel · pronamel active enamel shield · (bare "sensodyne 75ml")
    pronamel intensive enamel repair · sensitivity & gum whitening
    pronamel whitening intensive repair · cool gel · white deep clean
    junior new groove · clinical repair deep clean · whitening
    repair & protect whitening · proenamel daily protection
    whitening sensitive daily care

Fourteen different Sensodyne products that happen to share a tube size. Of
**379 blocked `dev` pairs, roughly 4 are genuinely the same product** — an
order of magnitude below the 98.7% figure a `MODULE`-only check suggests,
because `MODULE` can only prove a pair *different*, and the interesting bad
merges (Aquafresh Extra Care vs Intense Clean) are same-module.

So Tier 1's job is to find ~4 needles in 379, and the cost of a false
positive is unbounded (`03` §1a Risk, `05` §4).

### 4b. Hand-adjudicated pairs — the measurement instrument

`data/gold/pairs.jsonl`, 20 blocked `dev` pairs read in full and labelled
`same` / `different` / `ambiguous` with written evidence. Same discipline as
P4's URL gold set, and for the same reason: `τ_ann` is the threshold `03` §4
stage 1 says must be *tuned, not hand-picked*, and there was nothing to tune
it against. `ambiguous` is a real answer here — two retailer strings can be
genuinely undecidable without a product page, and recording a guess would
corrupt the instrument.

Distribution: 4 `same`, 2 `ambiguous`, 14 `different`.

### 4c. Three similarity functions, all measured, none separable

| pair (label) | variant Jaccard | char-4gram over variants | char-4gram over desc |
|---|---|---|---|
| `dev:140`/`dev:386` — same | 1.000 | 1.000 | 0.855 |
| `dev:168`/`dev:370` — same | 1.000 | 1.000 | 0.474 |
| `dev:223`/`dev:366` — same | 0.750 | 0.787 | 0.729 |
| `dev:2`/`dev:36` — same | **0.250** | 0.629 | 0.733 |
| `dev:107`/`dev:147` — **different** | 0.500 | **0.723** | 0.777 |
| `dev:366`/`dev:404` — different | 0.556 | 0.549 | 0.596 |
| `dev:164`/`dev:174` — different | 0.500 | 0.576 | 0.683 |

**Every one of the three has a true positive scoring below a true negative.**
Two rows are responsible and both are instructive:

- **`dev:2` / `dev:36`** — `macleans confidence mouthspray 15ml` and
  `macleans confidence mouth spray 15ml mcleans 15.00 ml`. The same product.
  Variant-term Jaccard scores it 0.250 because `mouthspray` and
  `mouth spray` are different tokens. Char n-grams repair most of that
  (0.629) — the same effect that bought P5 eight points — but the duplicated
  retailer tail dilutes the rest.
- **`dev:107` / `dev:147`** — Sensodyne Pronamel Intensive Enamel Repair
  *Extra Fresh* versus the *Whitening* variant in *Cool Mint*. Genuinely
  different SKUs that differ by two words in a fifteen-word description.
  **No bag-of-features similarity can rank this pair low**, because the pair
  really is textually near-identical; the discriminating token (`whitening`)
  carries hard identity weight that a similarity measure has no way to know.

That second case is the phase's central finding: **text similarity is the
wrong instrument for the last step of identity resolution, and no threshold
fixes it.** It is also precisely why `03` §4 stage 4 puts hard rules (GTIN
equality, size, count) *above* the weighted score, and why `03` §1a insists
the fingerprint is a blocking key.

### 4d. `τ_ann` = 0.75, and what it costs

Given no separating threshold exists, the choice is which error to take.
`03` §1a is unambiguous — a wrong merge poisons every future row that blocks
against it, a missed merge costs one row's retrieval budget — so this is
tuned for precision and the recall loss is accepted and stated.

Using char-4-gram cosine over variant terms (the best of the three: its
worst true positive is 0.629, versus 0.250 for Jaccard):

- highest **proven-different** pair: **0.723** (`dev:107`/`dev:147`)
- lowest **proven-same** pair *above* it: **0.787** (`dev:223`/`dev:366`)
- **`τ_ann = 0.75`**, the midpoint of that 0.064-wide window.

On the labelled set that is **3 of 4 true positives admitted, 0 of 14 true
negatives admitted**. Across all 379 blocked `dev` pairs it fires on 4 —
the three proven-same pairs plus `dev:108`/`dev:378` at 0.848, which is
labelled *ambiguous* rather than proven wrong.

**The two honest caveats, which belong in the phase report and not just
here.** First, the window is 0.064 wide and rests on four positive examples;
one more labelled pair could close it, and if it does, the answer is a
stricter `τ_ann` and more Tier-2 traffic, not a looser one. Second, `τ_ann`
buys its precision by giving up `dev:2`/`dev:36` at 0.629 — a real duplicate
that Tier 1 will miss forever. That is the intended trade, not an oversight.

### 4e. Two hard safety rules

- **A row with no variant terms can never produce a Tier-1 hit.** Its
  identity vector is empty, so cosine is 0 and it falls below any positive
  `τ_ann` — but this must be an explicit, tested rule rather than emergent
  arithmetic, because it is the difference between "no evidence" and "merge
  freely". Measured: 0 blocked `dev` pairs have both sides empty, 13 have one
  side empty. `sensodyne 75ml` is a real row and must never merge into
  anything.
- **`τ_merge` > `τ_ann`, always**, asserted at config load. `03` §4 stage 4
  requires it and `05` §4 explains the consequence of getting it backwards.
  P6 ships `τ_merge = 0.95`: only near-identical descriptions may be written
  back as a confirmed same-entity merge. P9 tunes it properly against the P4
  gold set; until then, strict.

## 5. Union-Find, and `entity_id`

`03` §1a specifies disjoint-set union over confirmed-same rows: no training,
`O(n·α(n))`, correct at n=412 and unchanged as the catalog grows.

Implementation notes that are requirements, not preferences:

- Union by size, with path compression. The representative of a merged set
  is chosen **deterministically** — the smallest `row_uid` by (sheet, index),
  never whichever happened to be inserted first — so the same inputs in any
  order produce the same components (`04` §5).
- `entity_id` is `sha256` of the block key, hex, truncated to 16 characters,
  prefixed by method: `gtin:...` or `fp:...`. **Never a uuid**, never
  time-seeded (`03` §3 says so explicitly). The same product resolved on two
  different days in two different runs must land on the same id.
- A merge is only ever *additive* here. Splitting a wrongly merged entity is
  not implemented, and that is why the audit log below exists — `05` §4's
  stated purpose is that a bad merge caught by L6 is traceable and reversible
  rather than requiring registry reconstruction.

## 6. Persistence and the audit log

`data/registry/` — persisted, **not** gitignored (`04` §2): this is
derived-but-valuable state, unlike `data/cache/`.

- `entities.jsonl` — one `CanonicalEntity` per line, sorted by `entity_id` on
  write so the file is diffable and a re-run is byte-identical (`04` §5).
- `audit.jsonl` — **append-only**, one record per registry write:
  `entity_id`, the `row_uid`s merged, the confidence, the tier, and the
  `run_id`. `05` §4 requires this and it is a Definition-of-Done item for any
  registry-writing path (`05` §6).

Timestamps (`created_at`, `updated_at`) are supplied by the caller, never
read from the clock inside the store — `04` §5 forbids `datetime.now()` in
logic, and a store that stamps its own times cannot produce a byte-identical
re-run.

## 7. What the gate reports

`04` §1's P6 gate is "Tier-1 block hit rate **and** within-block precision".
Both, plus the numbers that make them interpretable:

- **Block hit rate: 136 / 220 sized `qa` rows = 61.8%.**
- **Block-as-match precision: ~4 of 379 blocked `dev` pairs (~1%).** This is
  the quantified form of "the fingerprint is a blocking key, not a match
  key", and it is the number that justifies Tier 1 existing at all.
- **Tier-1 precision at `τ_ann = 0.75`: 3/3 on the labelled set (100%),
  recall 3/4 (75%)**, firing on 4 of 379 blocked pairs (the fourth is an
  `ambiguous`-labelled pair, not a known false merge).
- **Tier-0 hit rate: 0/412 on a first pass, 412/412 on a re-run.**

## 8. Files

```
config/thresholds.yaml         tau_ann = 0.75, tau_merge = 0.95 (was 0.0 TODO)
data/gold/pairs.jsonl          20 hand-adjudicated blocked pairs
src/nimo/registry/__init__.py  public surface only
src/nimo/registry/block.py     fingerprint, block_key — pure
src/nimo/registry/similarity.py identity_text, identity vectors, tier-1 score
src/nimo/registry/unionfind.py  disjoint-set, deterministic representatives
src/nimo/registry/store.py      CanonicalEntity persistence + audit log
src/nimo/registry/lookup.py     tier 0/1 -> RegistryLookupResult
src/nimo/registry/pairs.py      load the gold pair set
tests/registry/                 mirrors the above (`04` §2)
```

The TF-IDF primitives come from `nimo.classify.features`, which are generic
text-vector functions with no classifier state. Duplicating them to avoid a
sibling import would risk the two copies drifting, which is worse than the
naming awkwardness.

## 9. Acceptance criteria

1. `block_key` returns `method="exact_gtin"` for a clean barcode and
   `method="fingerprint"` otherwise, and returns `None` for a row with no
   size — never a degenerate brand-only key.
2. `entity_id` is reproducible: same block key → same id, across processes.
3. Tier-1 scoring reproduces the table in §4c on the real rows, and
   `τ_ann = 0.75` admits 3 of the 4 proven-same pairs and none of the 14
   proven-different pairs.
4. **A row with no variant terms never produces a Tier-1 hit.**
5. `τ_merge > τ_ann` is asserted at config load and raises otherwise.
6. Union-Find components are identical regardless of the order unions are
   applied in.
7. Every registry write appends exactly one audit record (`05` §4).
8. Writing the store twice from the same entities produces byte-identical
   files (`04` §5).
9. Block hit rate over the real sheets is 136/220; `dev` blocked pairs 379.
10. Zero network, zero LLM, `data/raw/` never written.

## 10. Tests

Beyond `04` §11 and `05` §6:

- **The gold pair set is a regression fixture**: every `same` pair scores
  above every... no — *specifically not that*, because §4c proves it false.
  Assert instead the exact measured relationship: `dev:2`/`dev:36` (same)
  scores **below** `dev:107`/`dev:147` (different), so that anyone later
  claiming to have "fixed" the similarity has to confront the pair that makes
  it unfixable. This test is written to fail loudly if the inversion
  disappears, because that would mean the measurement changed.
- **`τ_ann` admits exactly 4 of 379 blocked `dev` pairs**, pinned, and 0 of
  the 14 proven-different ones.
- **Empty variant terms → no hit**, on a constructed row and on the real
  `sensodyne 75ml` row.
- **`τ_merge ≤ τ_ann` raises** at config load.
- **Union-Find determinism**: same unions in shuffled order → identical
  components and identical representatives.
- **Audit log append-only**: a second write does not truncate the first.
- **Round-trip**: entities written and re-read compare equal, and the file is
  byte-identical on a re-write.
- **`01` §14 regression**: a `CanonicalEntity`'s `member_row_uids` are
  `row_uid`s; assert no `nan_key`-shaped integer ever reaches the store. This
  bug has been introduced twice in this project already.

## 11. Definition of Done

`04` §11's full checklist, plus `05` §6's registry items, plus:

- [ ] `GoldPair` in `03` §3 and `contracts.py`; `specs/contracts.md` updated
- [ ] `config/thresholds.yaml` carries real, derived `tau_ann`/`tau_merge`
  values with the derivation in a comment, not `0.0 TODO`
- [ ] Decision-log entry covering the non-separability finding, the `τ_ann`
  derivation, and Tier 0 being structurally dead on this dataset
- [ ] The phase report states both gate numbers **and** the two caveats in
  §4d — a 0.064-wide window on four positives, and one known duplicate given
  up on purpose
