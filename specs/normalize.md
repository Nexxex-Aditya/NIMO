# specs/normalize.md — P3: Description Normalizer

Authority: `03-architecture.md` §4 stage `[0]` (rules), `03` §3 (`DescTokens`,
`ProductQuery`). Read both before writing code — this spec assumes them.

Depends on P1 (contracts) and P2 (loader — `RawRow` is the input). Every
number and pattern below was **measured against all 824 real `dev`+`qa` rows**
via the committed P2 loader, not inferred from the three example strings in
`03` §4. Where those examples and the real data disagree, the data wins and
this spec says so explicitly.

## Scope

`RawRow` → `ProductQuery` (`RawRow` + `desc_clean` + `tokens: DescTokens`).

Deterministic and rule-based. **No LLM** — `03` §4 stage `[0]` requires
reproducibility and cheapness, and the stage-1 block key depends on this
output.

Out of scope: anything touching a URL, a page, or the registry.

## 0. Measured ground truth this spec is built on

Across 824 `dev`+`qa` rows, produced by `nimo.loader.load_rows`:

| Signal | Measurement |
|---|---|
| Rows with a size token | 456 (368 have none — `size_value=None` is the common case, not an error) |
| Volume tokens | `ml` 524, `l` 6, `mls` 2, `litre` 1, `cl` 0 |
| Mass tokens | `g` 42, `gm` 3, `gms` 1, `mg` 1, `kg` 0, `oz` 0 |
| Rows volume / mass / both / **mass-only** | 421 / 40 / 5 / **35** |
| `pack of N` | **122 rows — the dominant count pattern** |
| `N pack`/`N pk` | 26 |
| `N count`/`N ct` | 48 |
| `N s` (e.g. `2s`) | 27 |
| `N 's` (e.g. `10's`) | 9 |
| `x N` | 12 |
| `N x` | 10 |
| `twin pack` | 3 (`triple pack`: 0) |
| Rows matching **more than one** count pattern | **53 — precedence is required, not optional** |
| Rows with a `%` token | 12 |
| Rows whose trailing tokens match their own `RETAILER` | **824 / 824 (100%)** |
| `unit \d+` fragments | 40 |
| Brand repeated inside the description | 62 |
| Same size token appearing twice | 94 |

## 1. Junk removal — order is fixed and matters

`desc_clean` is `desc_raw` with the classes below removed, in this order.
Every removal is appended to `DescTokens.stripped_junk` verbatim — `03` §4:
"Strip, never delete silently."

### 1a. Trailing retailer-derived tokens — data-driven, not a hardcoded list

**This is the single largest junk class and it is fully systematic.** Measured:
**824 of 824 rows** end in at least one token that also appears in that same
row's `RETAILER` value. Examples, each with its own row's `retailer_raw`:

    "aquafresh whitening pump 100ml unit 00000012 e0028"   RETAILER "E0028 (GB) WAITROSE"
    "macleans confidence mouthspray 15ml e00n3"            RETAILER "E00N3 (GB) CWS CENSUS"
    "... toothpaste 119g|119.00 g (pack of 1) amazon"      RETAILER "AMAZON (GB)"
    "nûby all natural toddler training clear toothpaste 6m+ 45g brandbank"  RETAILER "BRANDBANK (UK)"

**Rule:** tokenize `retailer_raw` and `retailer` into a lowercase alphanumeric
set. Pop tokens from the *end* of the description while the popped token,
lowercased and stripped of non-alphanumerics, is in that set. Stop at the
first token that isn't.

**Do not hardcode a junk-token list.** A static list (`e0028`, `intouch`,
`amazon`, `brandbank`, …) would be a 50-entry table that silently rots the
moment a retailer is added, and it would risk stripping a token that is
legitimate content for a *different* row — `boots` is junk on a Boots row and
could be brand content elsewhere. Keying off the row's own retailer is
self-limiting by construction: it can only ever remove something that row's
retailer actually contains.

Only strip from the tail. A retailer token appearing mid-description is left
alone — it may be genuine content, and 1a has no way to tell.

### 1b. `unit \d+` fragments — 40 rows

`\bunit\s+\d+\b`, removed anywhere in the string. Real:
`"aquafresh whitening pump 100ml unit 00000012 e0028"`.

### 1c. Unit-of-sale codes

Standalone tokens only, from `config/normalize.yaml: unit_of_sale_tokens`:
`each` (48 rows), `ea` (13), `sgl` (17), `std` (15), `u` (18), `pmp` (2).

**Explicitly NOT junk, despite looking like it:** `free` (43 rows) and `extra`
(31). Both are load-bearing product content here — `alcohol free`,
`fluoride-free`, `sugar-free`, `extra soft`, `extra hard`. Stripping them
would destroy exactly the variant signal `03` §4 stage 4 scores on. This is
called out because both appear in the same frequency band as the real junk
above and are easy to sweep up by accident.

### 1d. Duplicated size suffix — 94 rows

When the *same* normalized size token appears more than once, keep the first
occurrence and strip the rest. Real:
`"mumtaz after eat 300gmumtaz after eat300g"`,
`"...toothpaste 119g|119.00 g (pack of 1)"`.

### 1e. Brand repeated mid-string — 62 rows

When the parsed `brand` (from `RawRow`, already encoding-repaired) occurs more
than once in the description, keep the first and strip later occurrences.
Real: `"wisdom mouthwash chlorhexidine digluconate 0.2% original alcohol free
300ml wisdom chlorhexidine mouthwash"`.

### 1f. Whitespace

Collapse to single spaces and trim, after all of the above. Note P2 already
did this once on `desc_raw`; removals here can reintroduce doubled spaces.

## 2. Size parsing — two dimensions, never interconverted

Feeds `size_value`, `size_unit`, `size_ml_equiv`, `size_g_equiv`
(`03` §3; `size_g_equiv` added 2026-09-10, see `02-decision-log.md`).

| Source unit | Normalized `size_unit` | Field | Factor |
|---|---|---|---|
| `ml`, `mls` | `ml` | `size_ml_equiv` | ×1 |
| `l`, `ltr`, `litre`, `litres` | `ml` | `size_ml_equiv` | ×1000 |
| `cl` | `ml` | `size_ml_equiv` | ×10 |
| `g`, `gm`, `gms` | `g` | `size_g_equiv` | ×1 |
| `kg` | `g` | `size_g_equiv` | ×1000 |
| `mg` | `g` | `size_g_equiv` | ×0.001 |
| `oz` | `g` | `size_g_equiv` | ×28.349523125 |

**Exactly one of `size_ml_equiv` / `size_g_equiv` is set** when `size_value`
is set; the other is `None`. Never coerce across dimensions — g→ml at density
1 would put a plausible wrong number where an honest `None` belongs
(`03` §3's size note).

Rules:
- First size token in `desc_clean` wins (5 rows carry both a volume and a mass
  token; the leading one is the pack size).
- **Percentages are concentration or promotion, never pack size** (12 rows):
  `0.2%` in `"chlorhexidine digluconate 0.2%"`, `50%` in `"75ml*75 ml*sgl*50%
  extra"`. A number immediately followed by `%` is not a size.
- A comma or period inside the number is a decimal separator (`119.00 g`).
- No size found → all four fields `None`. 368 of 824 rows. Not an error.

## 3. Count parsing — precedence is mandatory

`count: int | None`; **`None` means 1** (`03` §3). Multipack count is a *hard
identity attribute* (`03` §4): a 2-pack and a single are different products.

53 of 824 rows match more than one count pattern, so first-match-wins over an
explicit precedence order is required. Applied in this order, stopping at the
first match:

| # | Pattern | Regex sketch | Real example |
|---|---|---|---|
| 1 | `N x` | `\b(\d+)\s*x\b`, **skipped when the next word is a claim word** | `"10 x 15ml"` → 10; `"12x wisdom smokers..."` → 12 |
| 2 | `x N` | `\bx\s*(\d+)\b`, **not followed by a size unit, and not the integer part of a decimal** | `"listerine go tabs x8"` → 8 |
| 3 | `pack of N` | `\bpacks?\s+of\s+(\d+)\b` | `"...|1 count (pack of 4)"` → 4 |
| 4 | `N pack` | `\b(\d+)\s*[- ]?(?:pack|pk)s?\b` | `"1 pack"` → 1 |
| 5 | `twin pack` | `\btwin\s*pack\b` | → 2 |
| 6 | `N 's` / `N s` | `\b(\d+)'?s\b` | `"refills 2s"` → 2; `"10's"` → 10 |
| 7 | `N count` / `N ct` | `\b(\d+)\s*(?:count|ct)\b` | `"1 count"` → 1 |

**Why this order, from the measured collisions:**

- **The `x N` size trap.** `"dentex ... mouthwash twin pack x 250ml"` — a
  naive `\bx\s*(\d+)\b` captures **250** as the count. Rule 2's negative
  lookahead for a following size unit blocks that, and rule 5 then correctly
  yields 2. This trap was found by measurement, not review; it must have a
  named regression test.
- **`count` ranks last** because `N count` is Amazon listing boilerplate, not
  a multipack count. `"oral-b pro kids toothbrush heads..., pack of 4 count"`
  and `"...|1 count (pack of 4)"` both mean four heads; taking `1 count`
  first would return 1 and silently misidentify a 4-pack as a single. 48 rows
  carry `N count`, and it collides with `pack of N` on most of them.
- **Multiplier forms rank first** because they sit in the product title, ahead
  of the retailer's listing boilerplate:
  `"12x wisdom smokers extra hard brush toothbrush|1 count (pack of 1)"` is
  twelve brushes, and only rule 1 sees that.
- **The marketing-claim guard on rule 1** — found by enumerating all 11 real
  `N x` occurrences during implementation, not at design time. Exactly 3 are
  not multipacks at all but comparative claims: `"3x more effective"`,
  `"4x more effective"`, `"2x stronger enamel defence"`. Unguarded, rule 1
  ranks first and turns `"2x stronger enamel"` into a 2-pack. The remaining 8
  are genuine, and what separates them is the *following* word — a size
  (`10 x 15ml`, `2 x 150g`) or a product noun (`12x wisdom`,
  `2x replacement heads`, `1x usb cable`) versus a comparative. So rule 1
  skips a match whose next word is in
  `config/normalize.yaml: multiplier_claim_words`, and continues scanning.
  All three then fall through correctly to `1` from their
  `1 count (pack of 1)` boilerplate.
- **The decimal guard on rule 2** — `"bcsan 20 x 1.7 gr"`: without
  `(?!\.\d)`, rule 2 captures the `1` of `1.7`. Rule 1 happens to win on that
  row anyway, so the guard is belt-and-braces rather than load-bearing today;
  it is here because the failure would be silent if rule 1's guard ever
  changed.

A count of `1` is stored as `1`, not collapsed to `None`. `None` means "no
count expressed anywhere" — distinguishable in the trace from "explicitly one".

## 4. `format_hints`

Curated closed vocabulary in `config/normalize.yaml: format_hints` — this
feeds `MatchFeatures.format_consistent` (P9) and is a small, genuinely closed
set, unlike variant terms. Seeded from measured token frequencies: `pump`
(31 rows), `gel` (14), `tablets` (13), `rinse` (13), `powder`, `spray`,
`floss`, `strips`, `sachets`, `wipes`, `foam`, `paste`, `capsules`,
`lozenges`, `mouthwash`, `toothpaste`, `toothbrush`. Matched as whole tokens
against `desc_clean`, order-preserved, deduplicated.

## 5. `variant_terms` — derived, not curated

`variant_terms` is what remains of `desc_clean` after removing: brand tokens
(and `brand_owner` tokens), the size token, the count token, `format_hints`,
and stopwords (`config/normalize.yaml: stopwords` — `of`, `for`, `and`,
`with`, `the`, `to`, `de`, `each`, `pack`, `count`, `ml`, `g`).

**Derived rather than curated deliberately.** A hand-maintained variant
vocabulary would need to cover 1725 distinct residual tokens and would silently
drop every term nobody thought of — and `03` §4 stage 4 scores *variant token
overlap*, so a missing term is a silently weakened feature, not a visible
error. The residual-token approach has no vocabulary to rot. Measured top
residuals confirm it lands on the right material: `whitening` 93, `sensitive`
70, `white` 65, `fresh` 65, `mint` 94, `kids` 40, `fluoride` 38, `soft` 34,
`natural` 33, `enamel` 31, `charcoal` 13.

Order-preserved, deduplicated, lowercase.

## 6. Determinism

Same `RawRow` in, byte-identical `ProductQuery` out, every run. No wall clock,
no randomness, no set iteration leaking into output order (`04` §5).

## Error handling

Per `04` §4. A description that yields no size and no count is **not** an
error — 368 rows have no size. Raise only on genuine contract violations
(e.g. a numeric conversion that cannot happen given the matched regex, which
would mean the regex and the converter disagree). No masking fallback, no
`size = parsed or 100.0`.

## Acceptance criteria (P3 gate)

`04` §1 sets the gate at "30 hand-written cases from real dev rows pass".

1. **≥30 parametrized cases built from real `dev`/`qa` description strings**,
   each asserting the full expected `DescTokens`, each naming what it protects.
2. The `x N` size trap (`"twin pack x 250ml"` → count 2, size 250ml, **not**
   count 250) is a named regression test.
3. `pack of N` beats `N count` on the real colliding rows.
4. Percentage rows (`0.2%`, `50% extra`) yield those numbers as neither size
   nor count.
5. All 824 real rows normalize without raising, and `size_ml_equiv` /
   `size_g_equiv` are never both set on the same row.
6. Retailer-suffix stripping removes ≥1 token on all 824 rows (the measured
   100%), and never strips a token absent from that row's own `RETAILER`.
7. `free` and `extra` survive normalization as variant terms.
8. Twice-run byte-identical over the whole dataset.
9. `make check` green (or its four commands, `04` §11).
