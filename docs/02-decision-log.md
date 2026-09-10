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

---

# Open questions — resolve with organizers

| # | Question | Blocking? | Status |
|---|---|---|---|
| Q1 | `dev.EXTERNAL_CODE` is rounded to 3 sig figs in 377/412 rows. Can a corrected sheet be provided? Separately: of the 35 rows that survive rounding, 17 are only 6–7 digits (e.g. `266611`, `1071580`) and are not valid GTIN lengths — are these a second corruption mode (dropped leading zeros) or genuinely short internal codes? Usable dev barcodes are 18, not 35. | High — kills barcode matching on dev | open |
| Q2 | Is the expected `PRODUCT_URL` submission value a real URL, or the page title? `sample_output` contains titles. | High — wrong format = zero score | open |
| Q3 | No URL ground truth exists in `dev`. How is URL selection (stage 4) scored? | High — cannot optimize what we cannot measure | open |
| Q4 | `sample_output` shows an Amazon.in page as the answer for a `FR,GB` item. Is cross-market resolution acceptable? | Medium — determines whether market is a filter or a feature | open |
| Q5 | `sample_output` carries `GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT`, absent from `dev`/`qa`. Required in submission? | Medium | open |
| Q6 | Is scraping retailer sites permitted, and are there rate/robots constraints for the demo? | Medium | open |
| Q7 | Which LLM is provided, with what context window and rate limit? Multimodal available for image evidence? | High — image comparison is an explicit requirement | open |
| Q8 | `dev` row with module `TOOTH CLEANING - GUM/TABLETS (NATURAL TEETH)` has `GLOBAL_PACKAGING_MATERIAL = 'GLASS'`, but that module's allowed values are `['CARDBOARD', 'PAPER', 'PLASTIC']` — no `GLASS`. Confirmed organizer data error, not a parsing issue on our side. Is a corrected value available? | Low — 1 of 412 rows, but worth flagging | open |
| Q9 | `dev.BRAND` contains a double-encoded-UTF-8 mojibake value (`'JASÃƒâ€“N'`, 3 rows, presumably `JASÖN`); several `RETAILER_DESC` rows in both `dev`/`qa` are similarly corrupted. Can corrected-encoding sheets be provided, or should we repair on load? | Medium — degrades retrieval query quality for affected rows | open |
