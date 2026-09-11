# Spec — P13 reasoning synthesis (`src/nimo/reason/`)

Authority: `03` §4 stage 7, `04` §7 ("`REASONING` is a deliberate, grounded
artifact, not a dump of model thinking"), `04` §8 (groundedness test is the
gate), `05` §1 (`REASONING` is the exposed free-text surface; nothing
downstream reads it back into a prompt).

## 0. Composed, not generated — and why that is a decision, not a shortcut

`03` §1 lists "reasoning synthesis" among the places the LLM is used. This
phase does **not** use it, and the reasons are the requirements themselves:

1. **`03` §4 stage 7's anti-hallucination rule** — "any factual claim in
   `REASONING` must trace to a field in `CandidateEvidence` or
   `MatchFeatures`" — is a property a composer has *by construction*: every
   clause it emits is rendered from a named field, and the test that `03`
   asks for (evidence lacking fluoride ⇒ no mention of fluoride) is exact
   rather than probabilistic. A model rewrite can only add claims; it cannot
   add grounding.
2. **`05` §1** names `REASONING` as the one exposed free-text surface. A
   composer whose inputs are typed fields has no injection surface at all;
   the page text it quotes is already inside those fields, and it quotes
   only titles, identifiers and values, never body text.
3. **It runs off-network, costs nothing, and is byte-identical on re-run**
   (`04` §5) — which the demo and the 412-row submission both need, and
   which a model call is not.
4. **The bar is the organizers' own examples**, and those are citations —
   EAN, pack size, fluoride ppm, dispense format, then which codes they
   support, then "no clear evidence … therefore NOT STATED". That is a
   composition over the record, which is what this stage produces.

`03` §1 and §4 stage 7 are corrected to say so (decision log). If a model
polish is ever wanted, it goes *after* this stage as a style pass over
text that is already grounded, with the composed text kept as the artifact
of record — never as the source of claims.

## 1. Input and output

Input: the row's `ProductQuery`, `RegistryLookupResult`, `Selection` (with
`adjudication` when Tier 3 ran), `ModulePrediction`, `CharacteristicValues`,
and the evidence list (to find the selected page's `CandidateEvidence`).

Output — `Reasoning` (`03` §3, added by this spec):

```python
class Reasoning:
    row_uid: str
    text: str            # the REASONING cell, `max_chars`-bounded prose
    claims: list[str]    # one tag per clause, naming the field it came from
```

`claims` is the provenance record: `"selection.gtin_exact"`,
`"selection.size_match"`, `"module.nearest_example"`,
`"characteristics.GLOBAL_IF_WITH_FLUORIDE"`, `"registry.tier0_exact"`, ….
The trace carries it, and the test in §4 checks every tag against the
record it names.

## 2. What the text says, in order

Sentences are emitted only when their source field is populated. Each
sentence is one clause of provenance; nothing is inferred across fields.

1. **Identity — how the URL was chosen.** One of:
   - registry hit: "Identity confirmed by exact barcode match to a
     previously resolved item" (`tier0_exact`), or "…by near-duplicate
     identity match (similarity 0.87)" (`tier1_ann`), "; page and
     characteristics carried from that record without re-examination" —
     or, when the hit found an entity with no coded values and this run
     extracted them from its page (`specs/characteristics.md` §5), "that
     record had no coded characteristics, so its page was read again to
     code them", with the page-evidence sentence then included —
     `03` §4 stage 7's last paragraph, verbatim in spirit;
   - GTIN accept: "The selected page (`host`) publishes EAN `n`, equal to
     the record's barcode — a decisive identity match";
   - weighted match: "The selected page (`host`) was ranked first on
     brand match `x.xx`, `size exact (100 ml)`, variant overlap `x.xx`
     (`whitening`, `pump`), format consistent, ahead of the runner-up by
     `0.xx`" — each feature only when present and non-null; demotions and
     negative flags are stated when they applied to the winner;
   - Tier 3: "An adjudication step chose it over N alternatives on
     `<decisive_fields>`: `<rationale>`" — the model's own rationale is a
     recorded field and is quoted as such, attributed;
   - abstained: "No candidate page met the evidence threshold; module and
     characteristics are derived from the retailer description alone."
2. **Module.** "Classified as `MODULE` from the description, which most
   resembles `dev:N` ("…", similarity 0.82)" — or "Module carried from the
   registry record" when `source == "registry"`. When the classifier's
   runner-up gap is small (`< low_margin`), say so: "(a close call against
   `RUNNER_UP`)".
3. **Characteristics.** "Coded: `NAME` = `VALUE`; …" for every applicable
   characteristic with a value; then "No evidence for `NAME`, `NAME`; left
   empty" for applicable ones without; then, when any, "The model proposed
   `X` for `NAME`, outside the allowed values, and it was not written."
   Non-applicable characteristics are not listed — "not applicable to this
   module" is the null pattern's own statement and would be noise thirteen
   times over.
4. **Page evidence used** — only what existed: "Page evidence: structured
   product data (JSON-LD), title, `n` characters of text" — so a reader
   knows how much the values rest on.

Bounded by `max_chars` (`config/reason.yaml`): sentences are dropped from
the end, never truncated mid-clause, and the characteristics sentence is
shortened before the identity sentence is.

## 3. What it never does

- Never quotes `body_text`. It names that body text was available and how
  much; a characteristic value is the *coded* form of whatever the body
  said, and the value is what gets cited.
- Never states a fact about a page that is not in a field: no "the page
  shows a pump" unless `format_consistent` or a coded value says so.
- Never mentions a characteristic the gate excluded.
- Never invents a probability: `confidence` is quoted as "score" while
  calibration is off (`specs/calibrate.md`).

## 4. Tests — the gate (`04` §8, `03` §4 stage 7)

- **The fluoride fixture.** Evidence and values with no fluoride anywhere ⇒
  `"fluorid"` not in the text. The same fixture with
  `GLOBAL_IF_WITH_FLUORIDE = "WITH FLUORIDE"` ⇒ the text says it, once, as a
  coded value.
- **Provenance.** Every `claims` tag names a field that is populated on the
  input; every number in the text (barcode, size, similarity, score) is the
  string form of a field value; every upper-case coded value in the text is
  in `values`.
- Registry hit ⇒ the identity sentence says so and no page-feature clause
  appears; Tier 3 ⇒ the rationale is quoted and attributed; abstained ⇒ the
  abstention sentence and no host.
- `max_chars` is respected by dropping whole sentences.
- Byte-identical on repeated composition.
- The runner: stage 8 `reason`, artifact written, failure attributed.

## 5. Runner

`STAGE_SEQUENCE` gains `reason` (eight stages). `RowArtifacts.reasoning`.
The trace records `reasoning_chars` and `reasoning_claims`. No CLI flag: the
stage always runs — it needs nothing external.
