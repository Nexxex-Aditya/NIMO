# specs/contracts.md — P1: Contracts

Authority: `docs/03-architecture.md` §3. That section is the complete,
code-ready specification for every model — this file governs *how* to
transcribe it, not what the models are. If the two ever disagree after this
spec is written, `03` §3 wins; fix this file to match and note it in
`02-decision-log.md`, don't silently follow the stale version here.

Depends on P0 only. Zero dependency on P2 — contracts are pure data shapes,
nothing here reads the dataset.

## Scope

Every `class` in `03` §3's code block becomes a `pydantic.BaseModel` in
`src/nimo/contracts.py`. Nothing else goes in this file — no loading logic, no
validation logic beyond what pydantic's type system expresses declaratively,
no helper functions. If you find yourself writing a `def` that isn't a
pydantic validator, it belongs in the phase that actually uses the model, not
here.

## Class list, in dependency order

Build in this order — each depends only on classes above it:

1. `DescTokens`
2. `RawRow`
3. `CharacteristicRule`
4. `CharacteristicGuideline`
5. `ProductQuery` — inherits `RawRow`
5a. `ModulePrediction` — added for P5, see `02-decision-log.md`
6. `CanonicalEntity`
6a. `RowFailure`, `RunSummary` — added for P6a, see `02-decision-log.md`
6b. `GoldUrl` — added for P4, see `02-decision-log.md`
6c. `GoldPair` — added for P6, see `02-decision-log.md`
7. `BlockKey`
8. `RegistryLookupResult` — references `CanonicalEntity`
9. `CandidateURL`
10. `CandidateEvidence`
11. `MatchFeatures`
12. `Selection` — references `MatchFeatures`
13. `OutputRow`

(`03` §3 doesn't present them in this order — it's organized for human
reading, grouped by which pipeline phase produces each one. This list is
dependency order for writing code without forward references.)

## Pydantic conventions

- `pydantic>=2.6` (per `specs/scaffold.md`). Every class is a
  `BaseModel` subclass.
- Field types exactly as commented in `03` §3: `str | None` stays
  `str | None`, not `Optional[str]` — this codebase targets 3.12, use the
  modern syntax throughout, consistent with `ruff`'s `UP` rule already
  enabled in `pyproject.toml`.
- Every `Literal[...]` in `03` §3 is transcribed verbatim, values and all —
  e.g. `fetch_status: Literal["ok","http_error","timeout","blocked","parse_error"]`
  on `CandidateEvidence`. Do not widen any of these to plain `str`; the whole
  point is that invalid values fail at construction, not downstream.
- **`CandidateEvidence.jsonld_product` and `.og` are `dict[str, Any]`** — the
  only `Any` in the file, and a deliberate one (`04` §3's documented-boundary
  allowance). `03` §3 carries the full rationale and the measurements behind
  it. Do not "tighten" these to `dict[str, object]`: it was tested and breaks
  nested access, which is the shape real JSON-LD has. Do not leave them as
  bare `dict` either: that fails `mypy --strict`.
- `datetime` fields (`CandidateEvidence.fetched_at`,
  `CanonicalEntity.created_at`/`updated_at`) use `datetime.datetime`, timezone
  aware. Do not default to `datetime.now()` inside a model — `04` §5's
  determinism rule forbids wall-clock calls inside logic; the caller supplies
  the timestamp explicitly at construction.
- Preserve every inline comment from `03` §3 as either a field-level docstring
  or a trailing `#` comment — they're not decoration, they're the field's
  actual specification (e.g. `barcode_raw`'s comment is a safety rule, not a
  description).
- `model_config = ConfigDict(frozen=True)` on every model. These are data
  contracts crossing module boundaries — nothing downstream should be able to
  mutate a `RawRow` or a `CandidateEvidence` in place. If a later phase needs
  a modified copy, it constructs a new instance (`model_copy(update=...)`),
  it doesn't mutate the one it received.

## The JSON round-trip gate — concretely

`04` §1's P1 gate is "models instantiate; round-trip to JSON." This means,
for every class above:

```python
instance = SomeModel(...)  # every field populated, no defaults skipped
assert SomeModel.model_validate_json(instance.model_dump_json()) == instance
```

Write this as one parametrized test per model, not a single test that only
checks the last one. Two classes need explicit attention here, not just the
mechanical check:

- **`CanonicalEntity.characteristics: dict[str, str]`** — keys are
  characteristic names (plain strings), values are the predicted values. This
  round-trips fine as-is; confirm it with a test that includes at least one
  entry, not an empty dict, since an empty dict round-trips trivially and
  proves nothing.
- **`CharacteristicRule`/`CharacteristicGuideline`** — these exist specifically
  *because* a `dict` keyed by `(module, characteristic)` does not round-trip
  (`02-decision-log.md`, "CharacteristicRule / CharacteristicGuideline added").
  Don't accidentally reintroduce a tuple-keyed dict anywhere else in this file
  — if a new model ever seems to want one, that's a stop-and-flag moment
  (`04` §13), not a quick fix.

## Inheritance — `ProductQuery(RawRow)`

Pydantic v2 supports this directly:

```python
class RawRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    nan_key: int
    # ... rest of RawRow's fields per 03 §3

class ProductQuery(RawRow):
    desc_clean: str
    tokens: DescTokens
```

`ProductQuery.model_validate_json()` must correctly populate both the
inherited `RawRow` fields and its own two additions in one call — test this
specifically, since inheritance-plus-round-trip is exactly the kind of thing
that looks fine until an edge case in field ordering or a shadowed default
breaks it silently.

## What is explicitly NOT in scope for P1

- No loader logic (P2), no normalizer logic (P3), no LLM calls, no HTTP.
- No `applicable_characteristics()`-style helper functions — those consume
  `list[CharacteristicRule]`, they don't belong next to its definition.
- No `__init__.py` re-exports beyond making the classes importable as
  `from nimo.contracts import RawRow` etc. — don't build a public API surface
  beyond what later phases actually need to import.

## Definition of Done

In addition to `04` §11's full checklist:

- [ ] Every class in the dependency-ordered list above exists in
  `src/nimo/contracts.py`, matching `03` §3 field-for-field
- [ ] Every model is `frozen=True`
- [ ] Every `Literal` matches `03` §3 verbatim — no widened types
- [ ] Parametrized round-trip test covers every model individually (18 as of P6's `GoldPair`)
- [ ] `ProductQuery`'s inheritance round-trip is tested explicitly, not just
  implied by `RawRow`'s own test passing
- [ ] No `dict` with a non-`str` key anywhere in the file
- [ ] `mypy --strict` passes with zero `# type: ignore` in this file — these
  are pure type declarations; if mypy can't verify one without an ignore,
  that's a modeling problem to fix, not a suppression to add
