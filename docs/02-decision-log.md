# 02 — Decision Log

Append-only. Newest at the bottom. One entry per architectural decision.
This is the sync channel between build sessions and the design side — if a decision isn't here, the other side doesn't know about it.

Format:

    ## YYYY-MM-DD — <short title>
    **Decision:** one or two sentences.
    **Why:** the reason, including what was rejected.
    **Affects:** modules/files.
    **Status:** standing | superseded by <entry>

---

## 2026-09-09 — Candidate retrieval is in scope
**Decision:** Build a candidate-URL retrieval subsystem. SearxNG as the
meta-search layer.
**Why:** The brief promised candidate webpages in the dataset; the dataset has
none, and `PRODUCT_URL` is 100% null in both `dev` and `qa`.
**Affects:** new `retrieval/` subsystem; changes the whole pipeline shape from
"rank given candidates" to "generate then rank".
**Status:** standing

## 2026-09-10 — Canonical Entity Registry & compute cascade added
**Decision:** Add a persistent Canonical Entity Registry with blocking
(exact-key now; MinHash/LSH deferred as an upgrade path) and a Union-Find match
graph for merging confirmed-same entities. Retrieval/matching becomes a 4-tier
cascade — registry-exact → registry-ANN → web retrieval → LLM adjudication —
where each tier only runs on a miss from the one before. Pipeline gains a new
stage [1] (registry lookup & blocking); old stages [1]–[7] shift to [2]–[8].
**Why:** GNN and hyperbolic-RAG approaches were considered and rejected for
this dataset (too small, no multi-hop structure, a shallow enumerable
taxonomy — `03` §7). But "production-scale, time/resource-efficient" is a real
requirement the v0.1 pipeline didn't address: without a registry, cost per row
is constant no matter how many times the same physical product has already
been resolved. That repeat structure is not hypothetical — `dev` and `qa`
already share 40 identical `ITEM_CODE` values at n=412 (`01` §6). Union-Find
gives the graph-shaped answer the efficiency requirement calls for, honestly,
without a GNN's training-data requirement.
**Affects:** `03-architecture.md` — new §1a, §2 pipeline renumbered, §3 new
contracts (`BlockKey`, `CanonicalEntity`, `RegistryLookupResult`, `Selection`
gains `resolution_tier`), §4 new stage [1] spec + write-back added to stage
[4], §5 registry warm-start bullet, §6 new L6 metric, §7 GNN/hyperbolic bullets
tightened. New module `src/nimo/registry/`.
**Status:** standing

## 2026-09-10 — Registry gap closed; OutputRow contract finalized
**Decision:** `04-build-standards.md`'s build order and repo layout now
include the registry phase (P6, with P7–P15 shifted accordingly). The
`OutputRow` contract in `03` §3, previously a stub, is fully specified against
the verified `qa` header.
**Why:** closing the two items flagged pending in the entry above, plus a
review found `OutputRow` was never actually filled in — it blocked declaring
P1 (contracts) done under our own Definition of Done (`04` §11).
**Affects:** `04-build-standards.md` §1 build order, §2 repo layout, version
bumped to 0.2. `03-architecture.md` §3 `OutputRow`. The remaining real gap
before the implementation side can start: no files exist under `specs/` yet — that is the
actual precondition, not architecture completeness.
**Status:** standing

## 2026-09-10 — Security, safety, and latent-failure handling added
**Decision:** New document `05-security-safety.md`. Covers: trust boundary for
fetched content in LLM prompts (untrusted data, never instructions, with a
required injection-fixture test class), fetch-layer SSRF controls, LLM call
hardening (pinned model version, cost/token budget with hard abort, no secrets
in prompts), registry write audit-logging, and a named latent-failure taxonomy
(registry poisoning, calibration decay, cache staleness, silent schema drift,
model/provider drift, aggregate domain block, type coercion across
serialization boundaries, config/prompt version skew) with a guardrail and
owning module for each.
**Why:** `04` §4/§6/§7 cover ordinary error handling — exceptions, retries,
validation — but nothing covered failures that don't throw, or the specific
threat surface this design creates: arbitrary web content flows directly into
LLM prompts (stage 4, 6, 7), and candidate URLs come from search results we
don't control (stage 2/3). Both are properties of the architecture already
committed to, not speculative risks. The type-coercion failure mode isn't
hypothetical either — it's the same class as the barcode rounding defect
already found in the source data (`01` §3).
**Affects:** new `docs/05-security-safety.md`. `04` §11 (DoD gains a
conditional item for fetch/registry/LLM modules), §12 (five new forbidden
patterns), §13 (new escalation trigger), version bumped to 0.3. the session brief
required reading and repo-conventions note.
**Status:** standing

## 2026-09-10 — RawRow split from ProductQuery
**Decision:** `ProductQuery` in `03` §3 is now `RawRow` (loader/P2 output) plus
`desc_clean`/`tokens` (normalizer/P3 output), via inheritance —
`ProductQuery(RawRow)`. Stage `[0]` Normalize's input/output types stated
explicitly.
**Why:** found while drafting `specs/loader.md` — the original single
`ProductQuery` class included `desc_clean` and `tokens`, which the loader
cannot produce; only the normalizer can. A loader spec written against the old
contract would have claimed to build something it can't.
**Affects:** `03-architecture.md` §3, §4 stage `[0]`.
**Status:** standing

## 2026-09-10 — Barcode nulling-on-corrupt is a registry safety rule, not cosmetic
**Decision:** `RawRow.barcode` is `None` whenever `barcode_corrupt` is `True` —
the rounded value is never passed through as a usable identifier. The original
string is preserved separately in `barcode_raw` for audit/trace only. Also
corrected `desc_raw`'s scope: loader collapses whitespace only (`01` §10 #6);
all other junk-token stripping stays P3's job, as already specified.
**Why:** found while drafting `specs/loader.md`. If a rounded, corrupted
barcode like `5000000000000` were kept as `barcode` and used for Tier-0
registry lookup or the stage-4 GTIN hard-rule (`03` §1a, §4), two unrelated
products that happen to round to the same truncated value would be treated as
identical — a false-positive merge, which is exactly the registry-poisoning
failure mode `05` §4/§5 exists to prevent. Nulling at the source closes it
before it can occur, rather than relying on a downstream check to catch it.
**Affects:** `03-architecture.md` §3 (`RawRow.barcode_raw` added, `desc_raw`
comment corrected). `specs/loader.md` implements both rules directly.
**Status:** standing

## 2026-09-10 — Status column added as the disk-based resumability marker
**Decision:** `04` §1's build-order table gains a `Status` column
(`not started` | `in progress` | `done`), updated in the same commit as the
phase work it describes.
**Why:** build sessions can be interrupted with no warning and carry no
memory to the next one — this repo's own working agreement already says so.
Without a marker on disk, "where did we leave off" has no answer that survives
a session boundary. The build-order table already existed as the natural
place for it — adding a column, not a new file.
**Affects:** `04-build-standards.md` §1, version bumped to 0.4.
**Status:** standing

## 2026-09-10 — CharacteristicRule / CharacteristicGuideline added; JSON round-trip rule stated
**Decision:** Added `CharacteristicRule` and `CharacteristicGuideline` to `03`
§3 — flat, one-row-per-record models — for `char_value_list` and
`char_guidelines` respectively. Added a general rule to §3: every contract
must round-trip through JSON, which rules out `dict` keyed by anything but
`str` (a `(module, characteristic)` tuple key has no JSON object-key form).
`specs/loader.md` §7/§8 corrected to emit `list[CharacteristicRule]` /
`list[CharacteristicGuideline]` instead of the dict-of-tuple-keys shape they
previously described.
**Why:** found while drafting `specs/contracts.md`. `specs/loader.md`
referenced a `CharacteristicSchema` type that was never actually defined in
`03` §3 — a `specs/contracts.md` that said "transcribe everything in `03` §3"
would have silently omitted it, and P2 would have failed against a
nonexistent type. The dict-of-tuple-keys design it referenced also wouldn't
have satisfied P1's own JSON round-trip gate (`04` §1) — two compounding
errors caught before either was written into code.
**Affects:** `03-architecture.md` §3 (two new classes, general JSON rule
stated, version bumped to 0.3). `specs/loader.md` §7, §8, header.
**Status:** standing

## 2026-09-10 — PROGRESS.md added as the real interruption-recovery mechanism
**Decision:** New file `PROGRESS.md` at repo root, imported by the session brief and
read automatically at the start of every session. Overwritten in place (not
appended to), holding exactly: current phase/spec/step, the precise next
action, last-verified check state, and a "do not re-do" list. Update
discipline: at every sub-step boundary within a spec, not just at phase end.
Documented as `04` §1a.
**Why:** the earlier session-interruption design (git commit granularity, the
`04` §1 `Status` column) answered a different question than the one asked. The
actual requirement: a build session can be cut off by a token/time limit
mid-task with no warning, and the user's entire next message may be
"continue" — nothing else. Phase-level status doesn't say which line of which
spec a session was on when it stopped; only a continuously-updated,
finer-grained state file does. `Status` remains the coarse phase-level marker;
`PROGRESS.md` is what resumption actually reads.
**Affects:** new `PROGRESS.md`. `04-build-standards.md` new §1a, `Status`
column's framing corrected to "coarse marker, not the resumption mechanism",
version bumped to 0.5. the session brief — `@PROGRESS.md` added as the first thing
read (before the required-reading doc list), working agreement gains the
continue-behavior rule, stale "Current state" section replaced with a pointer
to `PROGRESS.md` instead of duplicating it.
**Status:** standing

## 2026-09-10 — Closed-characteristic validation: per-`&`-component, not whole-string
**Decision:** Closed characteristics are validated by splitting on `&` and
checking each component against `possible_values` independently, not by
matching the whole string. A generation is accepted if every component
validates.
**Why:** an independent verification pass found 189 of `dev`'s 412
ground-truth characteristic values fail whole-string validation. 187 are
`&`-joined combinations of 2–3 individually-valid values (123 two-component,
64 three-component), concentrated in `GLOBAL_ORAL_CARE_FUNCTION` (176) and
`GLOBAL_CONSUMER_LIFESTAGE_CLAIM` (11) — confirmed unambiguous, since no
individual `possible_values` entry anywhere contains `&`.
`sample_output` shows the identical pattern
(`'ANTI BACTERIAL & FRESHENING & WHITENING'`). Whole-string validation, as
originally specified, would reject the organizers' own reference answers —
a design that fails its own worked example. The remaining 2 of the 189 are a
genuine organizer data error, not a pattern to design around (logged as Q8
below).
**Affects:** `01-dataset-contract.md` §7, §10 (loader criteria), new §11.
`03-architecture.md` §4 stage 6 step 3. `05-security-safety.md` §1 (closed-field
immunity claim restated for component-wise checking — the immunity itself
still holds, the mechanism description didn't match what validation actually
needed to do).
**Status:** standing

## 2026-09-10 — Characteristic-name mapping corrected: both rule sheets are spaced-form
**Decision:** `char_value_list.characteristic` is spaced, uppercase form
(`"GLOBAL BRISTLE STRENGTH CLAIM"`) — not already underscored as previously
documented. Both `char_value_list` and `char_guidelines` need the same
normalization against `dev`/`qa`'s underscored columns, via one shared
function. The mapping additionally needs a one-entry hand-coded alias
(`"GLOBAL IF WITH INTERSPACE CLAIM"` → `"GLOBAL_INTERSPACE_CLAIM"`) — this one
name drops `"IF WITH "` entirely rather than transforming it, so a purely
mechanical space/slash→underscore rule produces
`GLOBAL_IF_WITH_INTERSPACE_CLAIM`, which isn't a real column.
**Why:** an earlier version of `03` §3 and `specs/loader.md` §7/§8 claimed
`char_value_list` already matched `dev`/`qa`'s naming, requiring
normalization only for `char_guidelines`. That claim was wrong. Combined with
assuming the mapping was purely mechanical, `specs/loader.md`'s "assert total
and bijective" requirement would have raised and halted P2 on the real file —
not a hypothetical, a predictable failure with an unobvious cause if hit
during implementation instead of before it.
**Affects:** `01-dataset-contract.md` §7, §8 (both rewritten). `specs/loader.md`
§7 (new, shared normalization + alias table), §8, §9 (renumbered), Tests
section (explicit alias-direction test added).
**Status:** standing

## 2026-09-10 — P6 gate restated: Tier-1 recall, not Tier-0 hit — the original claim was false
**Decision:** P6's gate (`04` §1) and `03` §1a's "checkable efficiency claim"
both changed from "Tier-0 hit on the 40 dev/qa `ITEM_CODE` overlap" to
"Tier-1 fingerprint-blocking recall on the same overlap."
**Why:** an independent verification pass checked the original claim against
the real file and found it can't be true. Tier 0 requires a clean barcode
match on both sides. Of the 102 `dev` rows carrying one of the 40 overlapping
`ITEM_CODE`s, only 4 have a usable barcode, and zero `ITEM_CODE`s have both a
clean `dev`-side and clean `qa`-side barcode that actually agree — the
barcode corruption defect (`01` §3) hits this exact overlap set. Tier 0
cannot fire here at all, not rarely. This was a design error stated with
confidence (`03` §1a called it "live, honest," "checked, not asserted") that
turned out to be neither — caught before it shipped as a spec the implementation side
would have implemented against and then failed to satisfy for a reason that
wouldn't have been obvious from the symptom alone. A 23-value `NAN_KEY`
overlap (`01` §9) is documented as a tighter alternative, not yet adopted.
**Affects:** `03-architecture.md` §1a (efficiency-claim section rewritten).
`04-build-standards.md` §1, P6 row.
**Status:** standing

## 2026-09-10 — Retailer name parsing redesigned: hand-reviewed table, not regex
**Decision:** `RETAILER` → `retailer` parsing changed from a regex to a
lookup into `config/retailers.yaml`, which changes shape from
`retailer_raw: domain` to `retailer_raw: {name, domain}`. `name` becomes a P2
precondition (all 50 entries), not deferred to P7 alongside `domain`.
Distinct-retailer count corrected: 50 across `dev`+`qa` combined, not 44
(that was a `dev`-only count).
**Why:** the obvious regex (`(?:[A-Z0-9]{4,6}\s+)?\([A-Z]{2,3}\)\s*(?P<name>.+)`)
was measured against all 50 real distinct values and fails on 21 (42%). Most
failures are loud (falls back to the unmodified raw string — `"AMAZON (GB)"`
keeps its country suffix because `AMAZON` itself satisfies the "code" group).
One fails silently and is genuinely dangerous:
`"BOOTS (GB) (HOMESCAN)"` matches successfully and captures `"(HOMESCAN)"` as
the retailer name, discarding `BOOTS` — the single largest retailer in the
dataset (49 rows) — with no exception raised anywhere. Given only 50 distinct
values total, a hand-reviewed table beats a cleverer pattern, and can share
the file already committed to for domain mapping rather than maintaining two
parallel 50-entry tables.
**Affects:** `01-dataset-contract.md` §2, §9, new §12. `03-architecture.md` §4
stage 2, S4. `specs/loader.md` §3 (brand no-owner-case reframed as common, not
rare, while already there), §4 (rewritten), Precondition section, Tests
section (`BOOTS`/`HOMESCAN` mandatory regression test). `specs/scaffold.md`
`config/retailers.yaml` stub. `05-security-safety.md` §5 latent-failure table
(new row: "parsing rule matches the wrong substring," using this as the
confirmed real instance).
**Status:** standing

## 2026-09-10 — Documentation corrections + new defect, from independent re-verification
**Decision:** Several prior claims corrected against direct re-inspection of
the real file: (1) `GLOBAL_INTERSPACE_CLAIM` is applicable to one module
(`TOOTHBRUSHES - MANUAL - INTERDENTAL`) and needed for 2 real `qa` rows — not
"never applicable," which was a misreading of `dev` simply having zero rows
of that module. (2) The applicability cross-check between `dev` and
`char_value_list` is now confirmed exact — zero violations in either
direction, once the corrected name-alias map is applied — resolving what was
previously flagged as an open risk. (3) `RETAILER_DESC` is not
whitespace-noisy in real `dev`/`qa` data (0 rows with double spaces or
leading/trailing whitespace, 412/412 lowercase) — the padded, mixed-case
example used elsewhere in this project came from `sample_output`, not real
data; the collapse step stays as a harmless no-op, but the noise
characterization was wrong. (4) `BRAND`'s no-owner-parenthetical case is
common (71/171 distinct brands, 42%), not a rare edge case. **New, previously
undocumented defect:** character-encoding corruption — `dev.BRAND` contains a
double-encoded-UTF-8 mojibake value (`'JASÃƒâ€“N'`, 3 rows, presumably
`JASÖN`); 10 `dev` and 13 `qa` `RETAILER_DESC` rows are non-ASCII, mixing
legitimate multilingual text with genuine corruption; `sample_output`'s
`PRODUCT_URL` carries a `U+2011` non-breaking hyphen. Minor related finding:
`GLOBAL_PERCENTAGE_NATURAL_INGREDIENTS` has 7 `dev` rows valued bare `'1'`
against the guideline's `99%`-style format expectation.
**Why:** an independent pass re-checked every claim in `01` against the
actual workbook, plus the cross-sheet consistency checks `01` itself had
flagged as unresolved. Nearly all prior numbers were exactly right; these
were the exceptions, and (1) specifically was actively harmful uncorrected —
`03` §4 stage 6 told the reader to treat this exact case as evidence of a
bug, when it's real and two live `qa` rows depend on it being handled
correctly.
**Affects:** `01-dataset-contract.md` §2, §6, §9, new §13.
`03-architecture.md` §4 stage 6 (stale bug-flag advice removed).
**Status:** standing

## 2026-09-10 — Three P0 build-tooling defects resolved, empirically verified
**Decision:** `specs/scaffold.md`'s `pyproject.toml`/`Makefile` fixed on all
three points the implementation side flagged as `FLAGGED — UNRESOLVED. Blocks P0.`
earlier the same day: (1) added `[build-system]` with `uv_build` as the
backend — `nimo` was never being installed by `uv sync`, so `import nimo`
failed everywhere including test collection; (2) added
`plugins = ["pydantic.mypy"]` to `[tool.mypy]`, project-wide, not a
per-line suppression on `settings.py` alone; (3) scoped the `Makefile`'s
`ruff` commands to `src tests` instead of `.` (primary fix), plus added
`extend-exclude = ["docs", "specs"]` to `[tool.ruff]` (defense in depth) —
`ruff format --check .` was rewriting Python code blocks embedded in
`docs/03-architecture.md` and two `specs/*.md` files.
**Why:** each was reproduced in an isolated sandbox against real `uv`
(0.11.7), `ruff` (0.16.6), `mypy` (2.3.1) before deciding the fix — not
reasoned from memory about expected tool behavior, per the verification
standard this project already required of the implementation side and now applies the
same way in reverse. On (2) specifically: chose the project-wide plugin over
a targeted suppression because it was verified to also be required for the
frozen+inheritance pattern P1's contracts actually use
(`ProductQuery(RawRow)`), not just for `settings.py` in isolation — a local
suppression would have fixed the symptom and left P1 to hit the same class
of failure. All four `make check` commands verified to exit 0 with this
content, from a clean `uv sync`, using the spec's exact test file content.
**Affects:** `specs/scaffold.md` `pyproject.toml`/`Makefile` blocks (rewritten
in full), acceptance criterion 1 (make-unavailable alternative added).
`04-build-standards.md` §11 (`make check` definition corrected to match the
scoped commands — it was still showing the unscoped `.` version), §1
(make-unavailable allowance formalized project-wide, not just P0-specific).
**Status:** standing — resolves the three `FLAGGED — UNRESOLVED. Blocks P0.`
entries in the build's P0 attempt report (build-system, mypy plugin, ruff
scope). Update those entries' own `Status:` lines to reference this one when
merging into the canonical log.

## 2026-09-10 — `encoding_suspect` gap resolved: RawRow fields + loader §2a added, via ftfy
**Decision:** `RawRow` gains `brand_encoding_suspect: bool` and
`desc_encoding_suspect: bool` (`03` §3). `specs/loader.md` gains a new §2a
implementing the repair, using `ftfy.fix_text()` rather than a hand-rolled
Latin-1/UTF-8 roundtrip, applied unconditionally before §3's brand-split and
§6's whitespace collapse. `01` §10 criterion 9 and §13 reworded to match:
repair happens, it's just never silent (the flag is always set when a change
occurred) — the earlier "flag, don't repair" wording undersold what was
actually being asked for.
**Why:** the implementation side correctly flagged this as unimplementable-as-written —
`01` §10 criterion 9 existed with no contract field and no spec section, an
authoring gap on the design side, not an implementation shortfall. Verified
`ftfy.fix_text()` directly against the real corrupted value before choosing
it: `ftfy.fix_text("JASÃƒâ€“N")` → `"JASÖN"` in one call (the corruption is
genuinely double-encoded; a single-pass hand-rolled fix would not fully
resolve it), and confirmed separately that it's a no-op on legitimate
multilingual text already in the data (`pärla`, `antibactérien`, `colgate®`
all pass through unchanged) — this is why unconditional application is safe,
no "does this look corrupted" branch needed first.
**Affects:** `03-architecture.md` §3 (`RawRow`, version bumped to 0.5).
`specs/loader.md` new §2a, §3/§6 (apply repair before their existing logic),
Tests section (the real corrupted value as a named regression test).
`01-dataset-contract.md` §10 criterion 9, §13 (both reworded), `ftfy>=6.2`
added to `specs/scaffold.md`'s dependency list, version bumped to 1.2.
**Status:** standing — resolves the `FLAGGED — UNRESOLVED. Blocks P2
completion.` entry regarding `01` §10 criterion 9 in the build's report.

## 2026-09-10 — `data/raw/` precondition: check the repo before assuming a manual copy is needed
**Decision:** `specs/scaffold.md`'s Precondition section rewritten: check
whether the dataset file is already committed elsewhere in the repo before
treating placement as a manual, outside-the-repo step; if found elsewhere,
`git mv` it to the canonical `data/raw/` path — never duplicate it.
**Why:** the build's P0 attempt found the workbook already committed at
`Project_info/product_truth_agent_dataset.xlsx`, contradicting the spec's
premise that it "lives... not in any location the implementation side can reach." Stale
premise, not a the implementation side error — flagged correctly rather than guessed
around (copying vs. moving have different consequences for whether the file
ends up committed twice).
**Affects:** `specs/scaffold.md` Precondition section. `specs/loader.md`'s
Precondition already deferred to scaffold's, unaffected.
**Status:** standing — resolves the `FLAGGED — UNRESOLVED. Blocks P2 start.`
entry regarding the stale `data/raw/` premise. The actual `git mv` (or
confirmation that no move is needed) still needs doing in the real repo —
not performed from here.

## 2026-09-10 — Full-autonomy mode: decide-log-continue replaces stop-and-escalate; PROGRESS.md moves to milestone cadence
**Decision:** For this run, the implementation side operates across all remaining phases
without stopping for a reply after each decision — review happens once, at
the end. Two mechanism changes follow: (1) `04` §13 changed from "stop and
raise it" to "verify, decide, document in the decision log, continue" for
spec conflicts, undocumented defects, contract changes, and new
latent-failure modes — the same verification standard just demonstrated
(reproduce and test, don't guess) is what makes this safe without a
per-decision human checkpoint. `[PROVISIONAL — Qn]` items remain
non-blocking as already designed. A narrow genuine-hard-stop is kept:
evidence the architecture itself is unworkable, not just a defect within it.
(2) `PROGRESS.md` and the session brief are now updated at milestone boundaries
(a phase's gate passing) only — not every sub-step, not every session. Git
commit granularity and message specificity become the resumability signal
between milestones instead.
**Why:** the previous policies (stop-and-escalate; sub-step-level
`PROGRESS.md` updates) were designed for a mode where a human was reviewing
after every phase or two. Under full autonomy across many phases reviewed
once at the end, "stop and wait" has no one to wait for, and sub-step
bookkeeping is overhead that doesn't serve its original purpose (surviving a
mid-phase cutoff via a precise pointer) as well as it costs in friction
across a long run. Traded some resumability precision for reduced overhead,
consciously — between-milestone recovery now relies on `git log` plus
verification rather than a fine-grained written pointer.
**Affects:** `04-build-standards.md` §1a (rewritten: format example,
update discipline, resumption procedure), §13 (rewritten, retitled
"Decide-log-continue"), version bumped to 0.7. the session brief "Read first"
section, "Repo conventions" (spec authorship no longer exclusively
web-side), "Working agreement" (both changed bullets rewritten).
**Status:** standing

## 2026-09-10 — `CandidateEvidence`'s two `dict` fields typed `dict[str, Any]`, verified against both alternatives
**Decision:** `CandidateEvidence.jsonld_product` becomes
`dict[str, Any] | None` and `.og` becomes `dict[str, Any]`, replacing the bare
`dict` both carried in `03` §3. These are the only `Any` annotations in
`contracts.py`, taken under `04` §3's explicit allowance for `Any` at a
documented boundary, and the boundary is now documented in `03` §3 itself.
**Why:** bare `dict` does not survive `mypy --strict` — reproduced in
isolation before deciding anything: `Missing type arguments for generic type
"dict"  [type-arg]`, twice, exit 1. Since `04` §11 makes `mypy --strict`
clean a Definition-of-Done item on every phase, `03` §3's literal content and
`04`'s standards were in direct conflict and one had to move. Two candidate
replacements were then tested against real pydantic 2.13 rather than reasoned
about: (1) both `dict[str, Any]` and `dict[str, object]` round-trip a
realistically nested JSON-LD payload — nested objects, arrays, floats and
`null` all survive `model_dump_json()` → `model_validate_json()` with types
intact and `==` equality holding, so correctness did not separate them;
(2) what separated them was downstream ergonomics under `mypy --strict` —
`dict[str, object]` fails on `jsonld_product["brand"]["name"]` with
`Value of type "object" is not indexable  [index]`, and that nested access is
JSON-LD's actual shape (`brand.name`, `offers[0].price` both appear in real
schema.org Product markup). Choosing `object` would therefore have forced a
cast or a suppression at every read site in P8 and P9 — trading one honest,
documented boundary annotation for scattered per-line suppressions, which is
precisely the anti-pattern `04` §3 and §12 name. Rejected on that basis, not
on taste. `Any` is contained: it appears on exactly two fields, both holding
third-party markup whose schema we do not control and cannot pin.
**Affects:** `03-architecture.md` §3 (both field types, plus a new paragraph
recording the rationale and the measurements). `specs/contracts.md` Pydantic
conventions (new bullet, with an explicit "don't "fix" this in either
direction" note so a later reader doesn't re-litigate it). `src/nimo/contracts.py`.
`tests/test_contracts.py` — `test_nested_jsonld_survives_round_trip_with_types_intact`
exercises exactly the nested access that motivated the choice, so if anyone
does tighten it to `object` later, a test fails rather than a type-checker
run somewhere else going quiet.
**Status:** standing

## 2026-09-10 — Real type stubs over `ignore_missing_imports`, after they caught two live defects
**Decision:** `pandas-stubs`, `types-openpyxl` and `types-PyYAML` added to the
`dev` dependency group. `[[tool.mypy.overrides]]`'s `ignore_missing_imports`
list stays limited to `extruct.*`/`trafilatura.*`, which genuinely ship no
stubs.
**Why:** `specs/scaffold.md`'s override table says to add an entry "only when
mypy actually reports the import as untyped" — which it did, for `openpyxl`,
`pandas` and `yaml`, the moment P2's loader imported them. Two remedies were
available and they are not equivalent, so this was tested rather than assumed.
With real stubs installed, `mypy --strict` immediately reported two genuine
defects in freshly written loader code, both of which `ignore_missing_imports`
would have silently accepted: (1) `cell: Cell = row[index]` is unsound —
`Worksheet.iter_rows` yields `Cell | MergedCell`; (2) `int(cell.value)` was
being applied to openpyxl's full numeric-cell union, which includes `date`,
`time`, `timedelta` and `Decimal` — on a `date` that either raises something
unhelpful or truncates, on exactly the column (`EXTERNAL_CODE`) whose silent
type coercion is already the canonical latent-failure instance in this project
(`05` §5). The fix now narrows explicitly with `isinstance(value, int | float)`
and raises `DatasetSchemaError` otherwise. Suppression would have left a real
bug in the highest-risk column in the dataset. `pandas-stubs` was the one with
a plausible downside (it is strict enough to generate noise on ordinary
DataFrame use); measured, it produced zero false positives against this
codebase, so that concern did not materialize.
**Affects:** `pyproject.toml` `[dependency-groups] dev`. `uv.lock`.
`src/nimo/loader/dataset.py` (`_read_external_codes` narrowing + new
`DatasetSchemaError` branch). `specs/scaffold.md`'s override-table note stands
unchanged and was followed, not overridden.
**Status:** standing

## 2026-09-10 — `barcode_valid` is a derived function, not a `RawRow` field
**Decision:** `01` §10 criterion 1 asks the loader to "emit `barcode_valid:
bool` ... per row". Implemented as a pure function,
`nimo.loader.fields.barcode_valid(barcode) -> bool`, not as a fifteenth
`RawRow` field.
**Why:** `03` §3 is the contract authority and does not list it; adding a
field would have put `contracts.py` out of field-for-field agreement with
`03` §3, which `specs/contracts.md`'s DoD requires and P1 now enforces with a
test. More substantively, `barcode_valid` is a total function of `barcode`,
which the row already carries — storing it duplicates derived state that can
drift out of sync with its source, the same class of problem as any cached
denormalization. Note `01` §10 criterion 1's naming is already known-loose
against `03` §3 (it calls the corruption flag `barcode_corrupt_rounded`;
the contract calls it `barcode_corrupt`), so treating that criterion as a
statement of *intent* rather than a literal field list is consistent with how
the rest of it is already read. `specs/loader.md` §2 supports this reading
too — it introduces the rule with "Validity, **separately**".
**Affects:** `src/nimo/loader/fields.py`. No contract change, so `03` §3 and
`contracts.py` are untouched. `01` §10 criterion 1's intent is satisfied.
**Status:** standing

## 2026-09-10 — Only 18 of `dev`'s 35 intact barcodes are usable; `01` §3 corrected
**Decision:** `01` §3 consequence 2 amended. It previously said to tune
barcode matching "on the 35 intact rows only". The real usable count is
**18** — the other 17 are not GTINs.
**Why:** measured during P2 against the loaded rows, not estimated. The 35
`dev` rows that survive the `0.00E+00` rounding defect have length
distribution `{6: 4, 7: 13, 8: 18}`; only the 18 eight-digit values are valid
GTIN lengths (8/12/13/14). Values like `266611` and `1071580` cannot
participate in a GTIN hard rule, Tier-0 blocking, or an S1/S2 barcode search
strategy, so counting them as "intact" overstates the tunable sample by
almost half — on a signal `01` §3 itself calls "the single strongest identity
signal available". `qa`'s distribution is `{8: 1, 13: 411}`, i.e. 412/412
usable, which sharpens the dev/qa asymmetry `01` §3 already warns about
rather than contradicting it. Whether the 17 short values are a second
corruption mode (leading zeros dropped by the same numeric cell format) or
genuinely short internal codes is not determinable from the file alone;
recorded as unresolved and folded into Q1 rather than guessed.
**Affects:** `01-dataset-contract.md` §3 consequence 2 (rewritten), version
bumped to 1.3. Q1 in the open-questions table gains the short-value question.
Relevant later to P7 (S1/S2 strategy coverage on dev) and P9 (the GTIN hard
rule's effective sample size).
**Status:** standing

## 2026-09-10 — `size_g_equiv` added: size is two dimensions, and 35 rows are mass-only
**Decision:** `DescTokens` and `CanonicalEntity` each gain
`size_g_equiv: float | None` alongside the existing `size_ml_equiv`. Volume
normalizes to ml, mass to g, exactly one is set per parse, and the two are
never interconverted. The stage-1 fingerprint block key becomes
`brand + size_ml_equiv + size_g_equiv + count`.
**Why:** found while measuring real `RETAILER_DESC` data before writing
`specs/normalize.md`. `03` §4 stage `[0]` already required "Normalize volume
to ml, mass to g", but `DescTokens` had only an ml field, so the contract
could not express half of what the stage spec asked for. Measured across all
824 `dev`+`qa` rows: 421 carry a volume token, 40 a mass token, 5 both — and
**35 are mass-only** (`"crest 3d charcoal tooth paste 85g"`,
`"tom's pepermint toothpaste 170g"`, `"diamond whites black edition powder
32g"`). With a single ml field those 35 would carry `size_value=85.0,
size_unit="g", size_ml_equiv=None`, i.e. no usable size for the stage-1
fingerprint (`03` §1a), collapsing every mass-sized product of a given brand
into one block regardless of actual size — precisely the over-broad blocking
the registry design is most exposed to. The obvious shortcut, coercing g→ml
at density 1, was rejected outright: toothpaste is denser than water, so that
substitutes a plausible wrong number for an honestly missing one, which is the
failure shape `05` §5 exists to name. Two nullable fields with an
exactly-one-set invariant is the honest encoding. Cost: one extra field on two
models, and `size_match` in `MatchFeatures` (P9) must compare within a
dimension rather than across — noted for P9, not needed yet.
**Affects:** `03-architecture.md` §3 (`DescTokens`, `CanonicalEntity`, new size
note), §1a blocking bullet, §4 stage `[1]` fingerprint signature, version
bumped to 0.6. `src/nimo/contracts.py`. `tests/test_contracts.py` fixtures.
Consumed by `specs/normalize.md` (P3) and the block key in P6.
**Status:** standing

## 2026-09-10 — P3 normalizer designed from measurement; three defects caught during implementation
**Decision:** `specs/normalize.md` written (first spec authored
this side, per the shared-authority change) and implemented. Four design
choices worth recording, each grounded in a measurement over all 824 real
`dev`+`qa` rows rather than the three illustrative strings in `03` §4:

1. **Retailer-suffix stripping is data-driven, not a hardcoded list.**
   Measured: **824 of 824 rows** end in at least one token that also appears
   in that same row's `RETAILER` value. So the rule pops trailing tokens while
   they belong to *this row's own* retailer. A static 50-entry junk list was
   rejected: it rots when a retailer is added, and it cannot distinguish
   `boots` as junk on a Boots row from `boots` as content elsewhere. The
   data-driven form is self-limiting by construction.
2. **`variant_terms` is derived, not curated.** There are 1725 distinct
   residual tokens; a hand-maintained variant vocabulary would silently drop
   whatever nobody thought of, and `03` §4 stage 4 scores *variant overlap*,
   so a missing term is a quietly weakened feature rather than a visible
   error. Only `format_hints` is a curated closed set, because it is small,
   genuinely closed, and feeds `MatchFeatures.format_consistent`.
3. **Count parsing needs explicit precedence.** 53 of 824 rows match more than
   one count pattern. `pack of N` is the dominant form (122 rows), not
   `N pack` (26). `N count` ranks **last** because it is Amazon listing
   boilerplate — `"1 count (pack of 4)"` means four, and taking `1 count`
   first would silently report a 4-pack as a single.
4. **`free` and `extra` are not junk**, despite sitting in the same frequency
   band as the real unit-of-sale codes (43 and 31 rows). They carry
   `alcohol free`, `fluoride-free`, `extra soft` — exactly the variant signal
   stage 4 scores on.

**Why this entry matters beyond the design: three defects were found by
measuring, after the spec was written and while implementing it.** All three
would have produced plausible wrong output with no exception:

- **`N x` fired on marketing claims.** Enumerating all 11 real `N x`
  occurrences showed 3 are comparatives, not multipacks: `"3x more
  effective"`, `"4x more effective"`, `"2x stronger enamel defence"`. Since
  rule 1 ranks first, `"2x stronger enamel"` became a 2-pack — a wrong hard
  identity attribute (`03` §4 calls multipack count exactly that). Fixed with
  a claim-word guard keyed off the *following* word, since the 8 genuine ones
  are followed by a size or a product noun. All 3 now fall through correctly.
- **The tokenizer was ASCII-only.** `nûby` split into `n` + `by`, so that
  row's variant terms contained the meaningless `by` and lost the brand
  token. 23 rows carry legitimate non-ASCII (`pärla`, `antibactérien`),
  i.e. the same rows `01` §13's encoding work exists to protect — repaired at
  load and then mangled at normalize would have been a silent regression of
  an already-fixed defect. Tokenizing on `\w` fixes it.
- **`"listerine coolmint 500 millilitres"` parsed to no size.** Spelled-out
  unit forms were missing. Adding them took sized rows from 440 to 445.

Also worth flagging for review: an editing mistake of mine wrote literal
backspace bytes into `parse.py`'s regexes (a non-raw Python string in a patch
script turned `\b` into `0x08`), silently breaking every word boundary in the
count patterns. Caught by inspecting the file bytes, not by any test — the
patterns still compiled and still matched, just more loosely. The file was
rewritten wholesale and `src/` is now verified free of control bytes.
**Affects:** new `specs/normalize.md`, new `config/normalize.yaml`, new
`src/nimo/normalize/` (`parse.py`, `vocab.py`, `normalizer.py`), new
`tests/normalize/`. `04` §1 P3 row → done.
**Status:** standing

## 2026-09-10 — `NAN_KEY`/`ITEM_CODE` are corrupted too; the dev/qa overlap is void; row identity moves to `row_uid`
**Decision:** Three linked changes, from one finding made during P4.
(1) New `01` §14 documents that `NAN_KEY` and `ITEM_CODE` carry the same
`0.00E+00` rounding corruption as `EXTERNAL_CODE`. (2) `RawRow` gains
`row_uid: str` (`"{sheet}:{index}"`), which becomes **the** row identity;
`CanonicalEntity.member_nan_keys` becomes `member_row_uids`; `GoldUrl` keys
on `row_uid`. `NAN_KEY`/`ITEM_CODE` stay on the row verbatim for
traceability and submission, but nothing is ever keyed on them. (3) P6's
gate and `03` §1a's efficiency claim are restated against a content
fingerprint, because the overlap they rested on does not exist.
**Why:** noticed because the P4 stratified sampler reported 26 modules
covered when it should have covered 27 — a `NAN_KEY`-keyed dict inside the
sampler was silently collapsing rows. Chasing that one-module discrepancy
produced the following, all measured via `openpyxl` cell `number_format`,
the same method that found the barcode defect:

- **`NAN_KEY`: 65/412 `dev`, 67/412 `qa` rounded. `ITEM_CODE`: 162/412
  `dev`, 168/412 `qa`.** 15 `dev` `NAN_KEY`s are duplicated (42 rows), 16 in
  `qa` (46 rows), and **every duplicated value is one of the rounded ones** —
  the duplication is entirely an artifact. 11 `dev` `NAN_KEY`s span multiple
  modules: `147000000` is simultaneously a breath freshener, a Listerine
  mouthwash and an Oral-B toothbrush.
- **This breaks two things `03` states directly.** §2: "Every stage writes
  its intermediate artifact to disk keyed by `NAN_KEY`." §5: "Batch runner
  processes by `NAN_KEY`, skips completed." Under collision, one product's
  cached artifact is served for a different product, and a completed row
  marks an unrelated row done — no exception, plausible wrong output. `05`
  §5 predicted this exact case in writing ("the same class can recur
  anywhere a numeric-looking string crosses openpyxl/pandas, **including
  `NAN_KEY`/`ITEM_CODE`**"); it had simply never been checked.
- **The dev/qa overlap is entirely spurious.** All 40 shared `ITEM_CODE`s
  and all 23 shared `NAN_KEY`s are rounded values; **zero are clean**. The
  pairs are visibly different products (`ITEM_CODE 509000000`: "jason
  coconut mint toothpaste 119g" in `dev` vs "ultradex one go mouthwash
  sachets" in `qa`). So `01` §9's overlap bullet and `03` §1a's motivating
  evidence — "dev and qa share 40 identical `ITEM_CODE` values despite being
  nominally disjoint" — were describing Excel's cell formatting, not the
  data. The sets are disjoint. **This is the second time `03` §1a's
  checkable claim has had to be replaced**; the first replacement (Tier-0 →
  Tier-1) fixed the wrong tier while keeping the void overlap underneath it.
- **The registry premise survives; its evidence was rebuilt from content.**
  Fingerprinting P3-normalized rows on `brand + size_ml_equiv +
  size_g_equiv + count` (sized rows only, 225 `dev` / 220 `qa`): **95 `dev`
  rows repeat an earlier `dev` row**, and **136 of 220 sized `qa` rows (62%)
  block against a fingerprint already resolved in `dev`**. Real repeat
  structure, found in descriptions rather than corrupted keys.
- **And that same measurement produced the design finding worth the most.**
  Of the 48 fingerprints shared across `dev`/`qa`, some are the same product
  (`aquafresh whitening pump 100ml` on both sides) and some are not
  (`aquafresh extra care mint breeze 500ml` vs `aquafresh intense clean
  invigorating 500ml`; `aloe dent coconut oil` vs `aloe dent charcoal`). The
  fingerprint is a **blocking** key and must never be treated as a match —
  which is what `03` §1a and §4 stage `[1]` already say, but the measurement
  turns that from a design preference into a demonstrated requirement: a
  block-key-as-match design merges Aquafresh Extra Care into Aquafresh
  Intense Clean on the first run over real data. That is registry poisoning
  (`05` §4) reachable immediately, and it is why P6's gate now reports
  **two** numbers — block hit rate *and* within-block precision — rather
  than one recall figure that would score highest exactly when the merge
  logic is wrongest.
**Affects:** `01-dataset-contract.md` new §14, §9 overlap bullet superseded,
version → 1.4. `03-architecture.md` §1a (premise and efficiency-claim
sections rewritten), §2, §3 (`RawRow.row_uid`, `CanonicalEntity.member_row_uids`,
`GoldUrl.row_uid`), §4 stage 4 write-back, §5, version → 0.7.
`04-build-standards.md` §1 P6 gate. `05-security-safety.md` §4 (audit log
records `row_uid`). `specs/loader.md` new §4a + test. `specs/gold.md`
criterion 3. `src/nimo/contracts.py`, `src/nimo/loader/dataset.py`,
`src/nimo/gold/store.py`, and the three test modules.
**Status:** standing

## 2026-09-10 — Q7 answered (CIS LLM); the endpoint is internal-only; the SSRF guard must not be global
**Decision:** Q7's answer recorded in `config/models.yaml` — provider
`cis-azure-ai-inference`, model **pinned** to `hack-fest-gpt-5.6-luna` (`05` §3
forbids `latest`), endpoint `https://llm-api-cis.azure-intlsd-np.nielsencsp.net/`,
SDK `azure-ai-inference` `ChatCompletionsClient` at api_version
`2025-03-01-preview`, temperature 0. The API key lives only in gitignored
`.env` as `CIS_LLM_API_KEY`; `config/models.yaml` and `.env.example` carry
names and non-secret settings only (`04` §9). `azure-ai-inference>=1.0.0b9`
added to the dependency list. **No LLM client module was built** — that is
P11's deliverable, and it cannot be live-verified from here (below), so
writing it now would be speculative code against an unreachable service.
**Why, and the two findings that came out of trying to verify it:**

**1. The endpoint is not reachable from outside NIQ's network.** Probed rather
than assumed, per `04` §13's verification standard. DNS resolves
`llm-api-cis.azure-intlsd-np.nielsencsp.net` to **`10.249.224.116`**, an
RFC1918 private address (`ipaddress.ip_address(...).is_global` is `False`);
a TCP connect to port 443 times out; and a control connection to
`api.github.com:443` from the same machine succeeds, so this is not local
connectivity. The API therefore requires the NIQ corporate network or VPN.
The onboarding notebook does not mention this, and it changes how P11–P13 get
built: they can be *written and tested* off-network against frozen fixtures
(which `04` §6 mandates anyway — "zero network calls in tests"), but can only
be *executed* on-network. The cost of finding this at demo time instead of now
is the entire demo.

**2. `05` §2's SSRF guard would block our own model if implemented globally.**
`05` §2 requires the fetcher to reject private/RFC1918 ranges — and the LLM
endpoint *is* a private address. These are not actually in conflict, but only
because the guard's scope is narrow: it protects against **untrusted candidate
URLs arriving from search results** (`03` §4 stage 2), not against a
configured, trusted endpoint read from `config/`. Implemented as a global
outbound-address check in the shared HTTP wrapper — the obvious way to write
it, since `04` §6 says all HTTP goes through one client — it would break the
pipeline's own LLM calls with a timeout whose cause is not remotely obvious
from the symptom. Recorded in `config/models.yaml` directly next to the
endpoint, so whoever writes the fetch client in P8 reads it there rather than
rediscovering it.

**Still unanswered inside Q7**, and worth re-asking CIS rather than assuming:
context-window size, rate limits, and whether the model accepts image input.
`03` §4 stage 6 step 5 routes the primary pack shot to a multimodal call for
the four visual characteristics (packaging material, bristle strength,
toothbrush head size, dispense method); if `hack-fest-gpt-5.6-luna` is
text-only, that step needs a different plan and those four fall back to text
evidence alone. Q7's row is marked partially resolved, not resolved, for
exactly that reason.
**Affects:** `config/models.yaml` (rewritten), `.env.example`, `.env`
(untracked, gitignored — verified absent from `git status`), `pyproject.toml`
(`azure-ai-inference`), `uv.lock`, Q7's row in the open-questions table.
Consumed by P11, P12, P13; the SSRF note is consumed by P8.
**Status:** standing — connectivity unverified; re-verify on-network before P11.

## 2026-09-10 — Orchestration gap closed: `RowFailure`/`RunSummary` contracts and a P6a batch-runner phase
**Decision:** Added `RowFailure` and `RunSummary` to `03` §3 and
`contracts.py` (16 models now), and added **P6a — Batch runner &
orchestration** to `04` §1's build order, sited between P6 and P7.
**Why:** prompted by a direct question — is there a proper harness here, with
memory orchestration and the rest — which on checking turned up two real gaps
rather than a reassuring answer.

**1. `RowFailure` was mandated and defined nowhere.** `04` §4 states that
per-row failures are "caught at exactly one place — the runner — recorded as a
typed `RowFailure` with stage, exception type, and message." Grepping the
repo, that sentence was the *only* occurrence of the name: no contract in `03`
§3, no implementation, no test. This is the same authoring-gap class as the
`CharacteristicSchema` reference caught earlier in this project — a type named
in prose by a standards document, which every later phase is required to
produce, that does not exist.

**2. The batch runner had no phase and no owner.** `04` §2's layout lists
`src/nimo/run/` as "batch runner, CLI"; `04` §4 routes all per-row failure
handling through "the runner"; `03` §2 requires every stage to write artifacts
keyed by `row_uid`; `03` §5 requires the runner to process by `row_uid`, skip
completed rows and survive interruption. Four load-bearing requirements across
three documents — and P0 through P15 never allocated a phase to building any
of it. P14 is Assembly (output serialization), P15 is Demo.
`src/nimo/run/__init__.py` is 0 bytes.

**On the framing question itself, since it shapes what P6a is:** NIMO
deliberately has no agent harness. `03` §1 rejects the autonomous loop
explicitly and `03` §7 lists "Autonomous ReAct agent over search+fetch tools"
among rejected alternatives — and those reasons still hold now that an LLM is
actually available (reproducibility across 412 rows, scoreability with no URL
ground truth, token cost, and transparency being a scored criterion). What
NIMO has instead is a deterministic pipeline plus a persistent Canonical
Entity Registry as its memory layer, which is a coherent design and the right
one here. The gap was never "this should have been an agent" — it was that the
*orchestration* concerns a harness would centralise (failure capture, resume,
tracing, budget enforcement, run summary) were scattered across three
documents with no phase that owned them.

**P6a's gate is behavioural, not structural**, because that is where the value
is: all 412 dev rows driven through the stages built so far; a deliberately
failing row recorded as a typed `RowFailure` that neither aborts the run nor
emits a partial output row (`04` §4's two hardest rules, and the ones most
likely to be quietly violated by a `try/except` in the wrong place); and a
kill-and-restart mid-run resuming without redoing completed rows. `RunSummary`
carries the tier-distribution counts `03` §1a's efficiency claim is checked
against, the per-stage failure counts `04` §10 requires every run to print,
and the `config_hash` that `05` §5's version-skew guardrail needs recorded per
run.
**Affects:** `03-architecture.md` §3 (two new contracts).
`src/nimo/contracts.py`. `tests/test_contracts.py` (16 models, new fixtures,
drift guard updated). `specs/contracts.md` class list and DoD.
`04-build-standards.md` §1 (new P6a row). `specs/run.md` is still to be
written, at the start of P6a.
**Status:** standing


## 2026-09-10 — P5 module baseline: char n-grams over words, BRAND excluded against the gate's own wording, 32 modules unreachable
**Decision:** `specs/classify.md` written and implemented. The module baseline
is a **character-4-gram TF-IDF nearest centroid over P3's `desc_clean`**,
emitting a new `ModulePrediction` contract. Measured leave-one-out over all
412 `dev` rows: **80.3% overall (331/412), 49.7% macro**. Four decisions
inside that, each made from a measurement rather than a preference, and the
last one is the one worth reading.

**1. Character n-grams, not word tokens — +8 points, and P3 earns its keep.**
Leave-one-out, nearest-centroid throughout, only features varying:

| features | overall | macro |
|---|---|---|
| word unigrams over `desc_raw` | 68.9% | 35.4% |
| word unigrams over `desc_clean` | 72.1% | 41.2% |
| words + brand + char 4-grams | 80.3% | 47.9% |
| **char 4-grams alone over `desc_clean`** | **80.3%** | **49.7%** |

The mechanism is visible in the data: this dataset writes the same product as
`toothpaste`, `tooth paste`, `t/paste`, `pste`, `dentifrice` and
`aufsteckbürsten`, and truncates hard (`s/d t/c tooth stain erase`,
`ob g&e es man tbrush`). Word tokens make each of those a separate feature;
4-grams share substrings across all of them. Adding word features on top of
n-grams buys nothing. Sizes were swept (3, 4, 5, and the three pairs/triple)
and everything from 4 up is within a point on both metrics — `[4]` is the
default for the best overall figure at a third of the feature count.

Separately worth recording: **`desc_clean` beats `desc_raw` by 3.2 points
overall and 5.8 macro on identical features.** That is the first independent,
downstream-task evidence that P3's retailer-suffix stripping does something,
as opposed to P3's own unit tests confirming it does what it says.

**2. Nearest centroid over Naive Bayes, decided on macro rather than overall.**

| model | overall | macro |
|---|---|---|
| TF-IDF nearest centroid | **80.3%** | **49.7%** |
| Multinomial NB, empirical prior | 73.1% | 22.6% |
| Complement NB, uniform prior | 78.4% | 38.3% |
| k-NN cosine, k=1 | 66.3% | 32.1% |

Complement NB lands within 2 points of the centroid on overall accuracy and
11 points behind on macro. It buys head accuracy by collapsing the tail —
exactly the trap `01` §9 predicted in the abstract, now instantiated. Had this
phase reported overall accuracy alone, NB would have looked like a reasonable
choice. **Macro accuracy is the headline number for this stage**, and
`format_report` prints it first with `overall` beneath it, deliberately.

No scikit-learn: 412 rows × 27 classes is a hundred lines of arithmetic, and
the dependency would need an `ignore_missing_imports` override (`04` §3) to
buy an implementation of what is now unit-tested against hand-computed vectors.

**3. BRAND is excluded, which contradicts `04` §1's own P5 gate wording, and
the gate was corrected rather than the code.** `04` §1 said "text-only
classifier over `RETAILER_DESC` + `BRAND`". Measured, char (3,4,5)-grams:

    desc_clean only        80.1% overall / 50.3% macro
    BRAND + desc_clean     72.6% overall / 46.8% macro

7.5 points overall. Brand does not predict module: `ORAL-B` makes manual
brushes, electric brushes, refill heads and toothpaste; `COLGATE` makes paste,
mouthwash and brushes. A brand's n-grams pull all of its products toward
whichever module dominates that brand. There is a second reason worth naming
because it would otherwise look like a bug: P3's `strip_repeated_brand`
deliberately removes the brand from the description, and prepending `BRAND`
puts it back, undoing a normalization made on measured grounds. Left behind a
`use_brand: false` config flag so the finding stays reproducible instead of
becoming folklore, with the numbers in the test's assertion message.

**4. 32 of 59 modules are unreachable, two mechanisms were built to fix that,
and both were measured and rejected. This is the finding of the phase.**

`dev` covers 27 of the 59 defined modules, so a model fitted on it can never
emit the other 32 — `01` §6 names a live casualty, `TOOTHBRUSHES - MANUAL -
INTERDENTAL`, with zero `dev` rows and `qa` rows that need it.

*Attempt 1 — module-name pseudo-documents*, adding each of the 59 module names
to its own class so every module exists in the model. Costs 3 points overall
and 4–6 macro at every weight tried (w=0.25 → 77.2%/46.8%; w=2.0 →
77.9%/44.5%). Rejected.

*Attempt 2 — a separate zero-shot arm* over the 32 absent modules, scoring a
row against each absent module's **name**, routing when it beats the
supervised arm by margin δ. **`dev` prices this exactly, which is why it was
worth building: `dev` contains none of the 32, so every `dev` row the arm
claims is a false route by construction.**

| δ | dev routed | correct answers destroyed | dev overall | qa routed | qa → INTERDENTAL |
|---|---|---|---|---|---|
| +0.00 | 35 | 18 | 76.0% | 37 | 2 |
| +0.10 | 16 | 6 | 78.9% | 11 | 2 |
| +0.20 | 4 | 0 | 80.3% | 1 | 0 |

No setting is both free and useful: at δ=+0.20 it costs nothing and does
nothing; at δ=+0.10 it reaches the interdental rows and destroys 6 correct
answers. And the qualitative check is worse than the table. Of the 11 `qa`
rows routed at δ=+0.10, roughly 4 are right (`wisdom advanced interdental
toothbrush 2pack` → INTERDENTAL; `tung brush` → TONGUE CLEANING) and the rest
are plainly wrong (`poli-grip liquid foam cleanser` → ORTHODONTIC CLEANSERS,
when Poligrip is denture care; `colgate 2 in 1 whitening liquid gel` →
ORTHODONTIC CLEANSERS, when it is toothpaste).

The `dev` false routes show the mechanism exactly: **the arm gets the product
family right and the form wrong.**

    "x-press dental stain remover"      -> TOOTH STAIN REMOVERS - KITS
    "galpharm mouth ulcer treatment 3s" -> ORAL TREATMENT - GRANULES/POWDER - MULTI DOSE

Module names encode the form axis in category jargon — `FOAM/GEL/LIQUID/PASTE`,
`KITS`, `MULTI DOSE`, `PRE CUT PIECES/SINGLES` — that retail descriptions never
use. Name matching therefore resolves the family and then *guesses* the form,
and a wrong form scores identically to a wildly wrong answer.

**So: compute the unseen score, record it, never act on it at P5.**
`ModuleClassifier.unseen_scores` exists and has no routing code by design.
`01` §6's requirement is deferred, not dropped, and now has a concrete lever:
`qa:259` is reachable with margin +0.195 for whichever later stage holds an
actual product page saying "interdental brush". `qa:124` (`tesco proformula
interdental sticks 100's`) is genuinely ambiguous — the supervised model calls
it `TOOTHPICKS - MANUAL - DISPOSABLE` at 0.391, which is defensible for an
interdental *stick*; `01` §6 called both rows candidates, not confirmed labels.

**Also decided, smaller:**

- **`ModulePrediction` added to `03` §3** (17 contracts now). `03` §2 drew
  stage `[5]`'s output as a bare `MODULE` string, which is too thin once
  anything downstream has to decide with it — `03` §4 stage 5 makes this the
  fallback path, so the runner needs to know how much to trust it, and `04` §3
  requires inter-module values to be typed anyway. It carries
  `nearest_example_row_uid`: char-4-gram weights explain nothing to a human
  (`othp`, `aste`), but *"most resembles `dev:12` `aquafresh whitening pump
  100ml`, cosine 0.82, labelled that module"* is a citation someone can check,
  which is what the brief's transparency criterion and `03` §4 stage 7's
  anti-hallucination rule actually need.
- **No abstention at this stage.** Stage `[5]` is the fallback when retrieval
  fails; a fallback that declines to answer is not one. `module` is always set
  and trust is carried on `confidence`. That is licensed by measurement rather
  than assumed: accuracy by confidence decile runs 31.7% in the bottom decile
  to 95.2% in the top, so confidence carries real information. Had it been
  flat, the field would have been decoration.
- **`load_module_labels` added to the loader**, returning labels positionally
  aligned with `load_rows` rather than as a `RawRow` field — putting ground
  truth on the input row would make it structurally possible for a predictor
  to read its own answer. It also asserts every label is in
  `char_value_list`'s module set, which is `05` §5's silent-schema-drift
  guardrail applied to labels instead of inputs.
- **Two evaluation protocols, both without any RNG.** Leave-one-out (412 fits,
  ~60s) is the reported number. A deterministic module-stratified 5-fold (5
  fits, 0.3s — rows dealt round-robin within each module, so no shuffle, so no
  seed) is the regression guard, pinned at exactly 323/412 in the test suite.
  LOO is deliberately not asserted in the suite: a 60-second test would make
  `make check` five times slower for every future phase. It is reproducible
  with `uv run python -m nimo.classify`.
- **The four single-row `dev` modules score a structural 0%** under any
  held-out protocol, LOO included — removing the row removes the class. They
  stay in the macro denominator. Dropping them would raise the headline by
  hiding precisely the tail the metric exists to expose.
- **`ClassifierReport` is a frozen dataclass, not a `contracts.py` model.**
  `03` §3 is the *pipeline* contract authority and this is an evaluation
  artifact that never crosses a stage boundary. It still satisfies `04` §3 —
  what leaves the module is typed, not a bare dict.

**Where the remaining errors are, for whoever builds the page-evidence layer:**
they are systematic, not random, and they sit on the **form** axis inside a
correct family — ELECTRIC COMPLETE PACK ↔ MANUAL REGULAR (13 rows both ways),
TOOTH CLEANING ↔ TOOTH STAIN REMOVERS (6), ELECTRIC COMPLETE PACK ↔ REFILL
HEADS (6). Those are exactly the distinctions a product page states outright
and a truncated retailer string does not, which is a concrete, measurable
target for the delta `03` §4 stage 5 asks for rather than a hope.
**Affects:** new `specs/classify.md`, new `config/classify.yaml`, new
`src/nimo/classify/` (`config.py`, `features.py`, `model.py`, `evaluate.py`,
`__main__.py`), new `tests/classify/`. `03-architecture.md` §3
(`ModulePrediction` + transparency note), §4 stage 5 (rewritten with the
measured results), version → 0.8. `04-build-standards.md` §1 P5 row (gate
wording corrected, status done). `src/nimo/loader/dataset.py`
(`load_module_labels`). `src/nimo/contracts.py`, `tests/test_contracts.py`
(17 models), `specs/contracts.md`.
**Status:** standing


## 2026-09-10 — P6 registry: the block key was an either/or and shouldn't have been; no similarity separates same from different; Tier 0 is structurally dead on this data
**Decision:** `specs/registry.md` written and implemented —
`src/nimo/registry/` with blocking, Tier-0/Tier-1 lookup, a deterministic
Union-Find match graph, and an audit-logged persistent store. `GoldPair`
added to `03` §3 (18 contracts). `config/thresholds.yaml`'s `tau_ann` and
`tau_merge` replaced with derived values. **Three findings, and the first is a
defect in `03` itself that would have silently disabled the cascade on the
only sheet we submit.**

**1. `03` §4 stage 1's block key was "clean barcode when present, *else* a
fingerprint". The `else` is wrong, and the cost is total.** `qa` carries a
clean barcode on **412 of 412** rows. Under an either/or rule every `qa` row
takes the GTIN branch, so **no `qa` row ever receives a fingerprint key and
Tier 1 is unreachable for the entire evaluation set** — while **0 of those
412 GTINs appear in `dev`**, so Tier 0 misses all 412 as well. The compute
cascade would have degraded to "always Tier 2" on `qa`, and the 61.8% block
hit rate that `01` §14, `03` §1a and `04` §1's P6 gate all cite would have
been unreachable in the real pipeline — measurable in a scratch script,
impossible in the code.

Found by running the shipped implementation against the real sheets and
getting `qa fingerprint-keyed rows = 0` where the scratch measurement said
220. Worth noting how: the scratch script fingerprinted every sized row
regardless of barcode, and the implementation followed `03` faithfully. **The
spec and the measurement disagreed, and the measurement was measuring
something the spec could not do.** This is the third time a claim in `03` §1a
has had to be rebuilt (Tier-0→Tier-1, then the void `ITEM_CODE` overlap, now
this), and the same root cause each time: a number produced by a script whose
logic did not match the pipeline's.

Fixed by splitting into `gtin_block_key` and `fingerprint_block_key`, with
`block_keys` returning every key a row can be blocked under. A Tier-0 miss
means nobody has resolved *that GTIN* before, not that the product is new —
the same product may sit in the registry under a different retailer's row
whose barcode was absent or corrupt. That is what stage 1 step 3's "no exact
hit → ... within the same block" always implied. `03` §4 stage 1 corrected.

**2. No similarity function separates same-product from different-product on
this data. This is the phase's central finding and it is negative.**

`03` §4 stage 1 requires `tau_ann` to be *tuned, not hand-picked*, and there
was nothing to tune it against — the P4 URL gold set answers a different
question. So `data/gold/pairs.jsonl` was built the same way P4's was: 20
blocked `dev` pairs read in full and hand-adjudicated with written evidence
(4 `same`, 2 `ambiguous`, 14 `different`). `ambiguous` is a real answer;
recording a guess would corrupt the instrument.

Three candidate similarities were measured against it. **Every one has a true
positive scoring below a true negative:**

| pair | variant Jaccard | char-4gram/variants | char-4gram/desc |
|---|---|---|---|
| `dev:2`/`dev:36` — **same** | 0.250 | 0.629 | 0.733 |
| `dev:107`/`dev:147` — **different** | 0.500 | 0.723 | 0.777 |

Two rows explain it, and both are worth knowing:

- `dev:2`/`dev:36` are `macleans confidence mouthspray 15ml` and `macleans
  confidence mouth spray 15ml mcleans 15.00 ml` — the same product. Jaccard
  scores 0.250 purely because `mouthspray` and `mouth spray` tokenize
  differently. Char n-grams repair most of that (0.629), the same
  tokenization-robustness that bought P5 eight points.
- `dev:107`/`dev:147` are Sensodyne Pronamel Intensive Enamel Repair *Extra
  Fresh* and the *Whitening* variant in *Cool Mint* — genuinely different
  SKUs differing by two words in a fifteen-word description. **No
  bag-of-features similarity can rank this pair low**, because the pair
  really is textually near-identical; the discriminating token (`whitening`)
  carries hard identity weight a similarity measure has no way to know about.

That is the same lesson `03` §4 stage 4 already encodes by putting hard rules
(GTIN equality, size, count) *above* the weighted score — now demonstrated on
real data rather than asserted.

**`tau_ann = 0.75`, derived and precision-first.** With no separating
threshold available, the choice is which error to take, and `03` §1a is
unambiguous: a wrong merge poisons every future row that blocks against it, a
missed merge costs one row's retrieval budget. Using char-4-gram cosine over
variant terms (best of the three — its worst true positive is 0.629 against
Jaccard's 0.250): highest proven-different pair 0.723, lowest proven-same pair
above it 0.787, `tau_ann` = the 0.755 midpoint, rounded to 0.75. On the
labelled set that admits **3 of 4 true positives and 0 of 14 true negatives**;
across all 379 blocked `dev` pairs it fires on 4 (the fourth being an
`ambiguous`-labelled pair, not a known false merge).

**Two caveats that belong in the report, not buried here.** The window is
**0.064 wide and rests on four positive examples** — one more labelled pair
could close it, and if it does the answer is a stricter `tau_ann` and more
Tier-2 traffic, never a looser one. And it buys that precision by giving up
`dev:2`/`dev:36` at 0.629, a real duplicate Tier 1 will now miss forever.
Intended trade, recorded rather than discovered later.

`tau_merge = 0.95`, and the `tau_merge > tau_ann` invariant `03` §4 stage 4
requires is **asserted at config load**, not merely documented — inverted, the
registry accumulates merges no later lookup can distinguish from confirmed
ones (`05` §4).

**3. Tier 0 has zero opportunities to fire anywhere in this dataset in a
single pass.** Not rarely — zero: 0 barcodes shared between `dev` and `qa`,
and `qa`'s 412 clean barcodes are 412 distinct values with no duplicates.
This is not a reason to delete Tier 0, and the distinction is the interesting
part: **within one run it cannot fire; across runs it fires on everything.**
`03` §5's warm-start property persists the registry to `data/registry/`, so a
second pass over `qa` hits Tier 0 on 412/412 and skips stages 2–4 entirely.
So the honest demonstration of `03` §1a's efficiency claim on this data is a
**re-run**, not a single pass — and in production, where a catalog is
re-audited, the re-run case is the normal case. Worth saying plainly at demo
time rather than showing a tier histogram with a zero in it and hoping nobody
asks.

**Also decided, smaller but load-bearing:**

- **A block is overwhelmingly not one product, and now quantified.** The
  `('SENSODYNE', 75.0, None, 1)` block holds **14 rows** — daily care gel,
  pronamel active enamel shield, sensitivity & gum whitening, junior new
  groove, clinical repair, and so on. Of 379 blocked `dev` pairs, roughly 4
  are genuinely the same product. `01` §14 and `03` §1a both already said the
  fingerprint is a blocking key and not a match key; the measured magnitude is
  far larger than either implies, and it is why Tier-1 similarity is
  load-bearing rather than a refinement.
- **A `MODULE` cross-check is a weak instrument here and was not used as the
  headline.** Only 5 of 379 blocked pairs cross a module boundary, suggesting
  98.7% precision — but `MODULE` can only ever prove a pair *different*, and
  the canonical bad merge from `01` §14 (Aquafresh Extra Care vs Intense
  Clean) is same-module. Hand adjudication was the only honest route.
- **A row with no variant terms can never produce a Tier-1 hit**, checked
  before any arithmetic runs rather than left to emerge from a zero vector.
  Within a block, brand/size/count are equal by construction — they *are* the
  block key — so merging on them is merging on zero evidence. `sensodyne 75ml`
  is a real `dev` row (`dev:94`).
- **Union-Find representatives are the smallest member by sort order**, never
  insertion order. Union-by-size alone makes the representative depend on the
  order unions were applied, and a registry whose entity membership depends on
  row ordering cannot produce a byte-identical re-run (`04` §5).
- **`entity_id` is `sha256` of the block key, method-prefixed** (`gtin:` /
  `fp:`), never a uuid — `03` §3 requires reproducibility, and without it the
  registry cannot warm-start across runs, which is the only reason it is
  persisted.
- **Every registry write is audit-logged append-only** (`05` §4), recording
  `row_uid`s and never `nan_key`. `write_entities` refuses a member that has
  no `:` in it, because a bare integer is a `nan_key` — the bug this project
  has already introduced twice, and which here would serve one product's
  resolved answer for a different product forever.
- **The write-back *decision* is deliberately not built.** `03` §4 stage 4
  gates it on a hard GTIN accept or `calibrated_prob >= tau_merge`, both P9/P10
  artifacts. P6 ships the mechanism and the thresholds; inventing a confidence
  signal to gate it on now would be building the wrong thing carefully.
- **A test asserts a limitation on purpose.**
  `test_a_true_positive_scores_below_a_true_negative` pins the
  0.629 < 0.723 inversion. If it ever disappears that is a real change in the
  data or the features and `tau_ann` must be re-derived, so it fails loudly
  rather than quietly becoming true.
**Affects:** new `specs/registry.md`, new `data/gold/pairs.jsonl`, new
`src/nimo/registry/` (`block.py`, `similarity.py`, `unionfind.py`, `store.py`,
`config.py`, `lookup.py`, `pairs.py`), new `tests/registry/`.
`config/thresholds.yaml` (derived `tau_ann`/`tau_merge` with the derivation in
comments). `03-architecture.md` §3 (`GoldPair`), §4 stage 1 steps 1 and 3
(rewritten — the either/or defect and the two Tier-1 rules).
`src/nimo/contracts.py`, `tests/test_contracts.py` (18 models),
`specs/contracts.md`. `04-build-standards.md` §1 P6 row.
**Status:** standing


---

# Open questions — resolve with organizers

| # | Question | Blocking? | Status |
|---|---|---|---|
| Q1 | **Three columns are damaged by the same `0.00E+00` cell format, not one.** `EXTERNAL_CODE` is rounded in 377/412 `dev` rows; `NAN_KEY` in 65/412 `dev` and 67/412 `qa`; `ITEM_CODE` in 162/412 `dev` and 168/412 `qa` (`01` §14). The `NAN_KEY`/`ITEM_CODE` damage makes those columns unusable as row identifiers — 11 `dev` `NAN_KEY`s span multiple modules — and makes the apparent 40-value dev/qa `ITEM_CODE` overlap entirely spurious. Can uncorrupted versions of all three columns be provided? Separately: of the 35 rows that survive rounding, 17 are only 6–7 digits (e.g. `266611`, `1071580`) and are not valid GTIN lengths — are these a second corruption mode (dropped leading zeros) or genuinely short internal codes? Usable dev barcodes are 18, not 35. | High — kills barcode matching on dev | open |
| Q2 | Is the expected `PRODUCT_URL` submission value a real URL, or the page title? `sample_output` contains titles. | High — wrong format = zero score | open |
| Q3 | No URL ground truth exists in `dev`. How is URL selection (stage 4) scored? | High — cannot optimize what we cannot measure | open |
| Q4 | `sample_output` shows an Amazon.in page as the answer for a `FR,GB` item. Is cross-market resolution acceptable? | Medium — determines whether market is a filter or a feature | open |
| Q5 | `sample_output` carries `GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT`, absent from `dev`/`qa`. Required in submission? | Medium | open |
| Q6 | Is scraping retailer sites permitted, and are there rate/robots constraints for the demo? | Medium | open |
| Q7 | Which LLM is provided, with what context window and rate limit? Multimodal available for image evidence? | High — image comparison is an explicit requirement | **partially resolved 2026-09-10** — CIS LLM, model `hack-fest-gpt-5.6-luna`, `azure-ai-inference` SDK, api_version `2025-03-01-preview`; key in gitignored `.env`. **New constraint found by probing: the endpoint is internal-only** — it resolves to `10.249.224.116` (RFC1918) and TCP 443 times out off-network, so it needs the NIQ VPN. Context window, rate limit and multimodal support are still unstated — re-ask, and confirm connectivity on-network before P11/P12 execute. |
| Q8 | `dev` row with module `TOOTH CLEANING - GUM/TABLETS (NATURAL TEETH)` has `GLOBAL_PACKAGING_MATERIAL = 'GLASS'`, but that module's allowed values are `['CARDBOARD', 'PAPER', 'PLASTIC']` — no `GLASS`. Confirmed organizer data error, not a parsing issue on our side. Is a corrected value available? | Low — 1 of 412 rows, but worth flagging | open |
| Q9 | `dev.BRAND` contains a double-encoded-UTF-8 mojibake value (`'JASÃƒâ€“N'`, 3 rows, presumably `JASÖN`); several `RETAILER_DESC` rows in both `dev`/`qa` are similarly corrupted. Can corrected-encoding sheets be provided, or should we repair on load? | Medium — degrades retrieval query quality for affected rows | open |

## 2026-09-10 — P4 gold set: partial by design, sample frozen after it shifted under the labels
**Decision:** P4 ships with **6 of 50 sampled rows labelled** (5 `correct`,
1 `ambiguous`) and the full infrastructure around them: `GoldUrl` contract, a
module-stratified sampler, a fail-loud JSONL store, and — added mid-phase —
a **frozen sample artifact** at `data/gold/sample.txt`. `04` §1's P4 row is
marked done on the infrastructure and the honest partial set, not on reaching
the round number.
**Why:** three things, in order of how much they matter.

**1. Partial beats invented, and this is the one phase where that is not a
platitude.** The gold set is the *measurement instrument* for L3 and L4
(`03` §6) — it is the only thing stage-1 URL selection can ever be scored
against, because `01` §6 establishes there is no URL ground truth anywhere in
the dataset. A fabricated or snippet-guessed URL does not fail; it silently
miscalibrates P9's precision@1 and P10's isotonic fit, and there is no
downstream check that would notice, because this *is* the check. So every
entry was searched for, opened in a browser, and inspected, with `evidence`
recording what was actually confirmed. Real near-misses were rejected in the
process — a Cocowhite sibling with identical brand and size but a different
variant, a Humble Co fluoride-FREE sibling otherwise identical in brand,
format and count, and a Listerine listing that is a 6-pack of 8-tablet packs
where the row wants a single 8-count unit. Those are precisely the "similar
or misleading matches" the brief's success criteria name, and hitting three
of them in six rows is a useful early signal about how hard stage 4 will be.

**2. The sampler had the very defect the project had just documented.** It
selected by `nan_key`, which `01` §14 (written hours earlier) establishes is
not unique. It was silently collapsing rows and reporting 26/27 module
coverage instead of 27/27 — and it was *that one-module discrepancy* that led
to discovering the `NAN_KEY`/`ITEM_CODE` corruption in the first place. Its
own test (`test_sampler_never_returns_more_than_available`) then caught the
bug still sitting in the sampler afterwards. Now keyed on `row_uid`;
coverage is 27/27, against ~12 for a proportional sample of the same size.

**3. Fixing that re-based the sample under labels already written against
it** — the sampler's within-module ordering changed, so 2 of the 6 labelled
rows fell outside the new 50. A sample that is recomputed on demand can
therefore silently invalidate existing labels with no error at all: the same
latent-failure shape as everything else in `05` §5, aimed at the measurement
instrument. Hence the frozen artifact, plus a test asserting it still equals
the sampler's output so a future change fails loudly. The two pre-freeze
labels were kept rather than discarded — the verification work is real — and
are named explicitly in the test as documented exceptions rather than papered
over by weakening the assertion.

**Also worth flagging:** `tesco.com` served a bot-protection interstitial
instead of the product page. One row (`dev:193`, Diamond Whites Black Edition
32g) whose correct answer is almost certainly a Tesco URL — the search-result
title matches the row exactly — was left **unlabelled** rather than accepted
on the strength of a snippet. That is `05` §5's "aggregate domain block"
reaching the labelling process rather than the fetcher, and it is direct
evidence for Q6: if Tesco blocks a browser, it will block the P8 fetcher too.
**Affects:** new `specs/gold.md`, new `src/nimo/gold/`, new `tests/gold/`,
new `data/gold/urls.jsonl` and `data/gold/sample.txt`. `03-architecture.md`
§3 (`GoldUrl`). `specs/contracts.md` class list (14 models).
`04-build-standards.md` §1 P4 row.
**Status:** standing — the remaining 44 sampled rows are unlabelled and
resumable directly from the frozen sample.
