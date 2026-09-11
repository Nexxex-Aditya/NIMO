"""The applicability gate — `03` §4 stage 6 step 1, `specs/characteristics.md` §1.

Runs first, and it is ours. A characteristic outside `char_value_list`'s
(module, characteristic) matrix is `None` for that row — before the model is
asked and again after it answers. `00`: "Predicting a plausible value for a
non-applicable characteristic is a wrong answer, not a partial credit
answer."
"""

from nimo.contracts import CanonicalEntity, CharacteristicRule, CharacteristicValues, OutputRow

# The 13 characteristic columns, in the qa header's order, read off the
# contract so there is exactly one list of them (`specs/characteristics.md` §1).
CHARACTERISTIC_COLUMNS: tuple[str, ...] = tuple(
    name for name in OutputRow.model_fields if name.startswith("GLOBAL_")
)


def applicable_rules(rules: list[CharacteristicRule], module: str) -> list[CharacteristicRule]:
    """The rules that apply to `module`, in column order."""
    by_name = {rule.characteristic: rule for rule in rules if rule.module == module}
    return [by_name[name] for name in CHARACTERISTIC_COLUMNS if name in by_name]


def empty_values() -> dict[str, str | None]:
    """All 13 keys, all `None` — the shape every result starts from."""
    return dict.fromkeys(CHARACTERISTIC_COLUMNS)


def gate_only(
    row_uid: str, module: str | None, rules: list[CharacteristicRule]
) -> CharacteristicValues:
    """The off-network result: the gate applied, no call, every value `None`.

    The null pattern is still exactly right for the module, which is the
    property `01` §6 says matters most; only the values are missing.
    """
    applicable = applicable_rules(rules, module) if module is not None else []
    return CharacteristicValues(
        row_uid=row_uid,
        module=module,
        values=empty_values(),
        applicable=[rule.characteristic for rule in applicable],
        rejected={},
        source="gate_only",
        prompt_hash=None,
        model=None,
        image_sha256=None,
    )


def from_entity(
    row_uid: str, entity: CanonicalEntity, rules: list[CharacteristicRule]
) -> CharacteristicValues:
    """A Tier 0/1 hit carries the stored entity's values (`03` §4 stage 6,
    last paragraph). The gate is re-applied under the entity's module so a
    stored value for a characteristic that does not apply — which cannot
    happen if the entity was written by this stage, but is the kind of thing
    a registry accumulates over versions — is dropped rather than served."""
    values = empty_values()
    applicable = (
        [rule.characteristic for rule in applicable_rules(rules, entity.module)]
        if entity.module is not None
        else []
    )
    for name in applicable:
        stored = entity.characteristics.get(name)
        values[name] = stored if stored else None
    return CharacteristicValues(
        row_uid=row_uid,
        module=entity.module,
        values=values,
        applicable=applicable,
        rejected={},
        source="registry",
        prompt_hash=None,
        model=None,
        image_sha256=None,
    )
