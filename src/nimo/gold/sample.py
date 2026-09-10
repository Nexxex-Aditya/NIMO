"""Stratified selection of which `dev` rows to hand-label — `specs/gold.md`.

Pure and deterministic: same rows in, same sample out, no randomness at all
(`04` §5). Proportional sampling is deliberately *not* used — `01` §9 records
that the top 4 modules are 317/412 of `dev`, so a proportional sample of ~50
would leave most of the 27 modules unrepresented and per-module accuracy
unmeasurable for the tail, which is the failure `01` §9 warns about.
"""

from collections import defaultdict

from nimo.contracts import RawRow


def stratify_by_module(
    rows: list[RawRow],
    modules: list[str],
    target: int,
    per_module_floor: int = 1,
) -> list[str]:
    """Return `row_uid`s to label, module-stratified, deterministically.

    Returns `row_uid`, **not** `nan_key`: `NAN_KEY` is not unique (385 distinct
    over 412 `dev` rows) and collides across genuinely different products
    (`01` §14), so a `nan_key`-keyed selection silently drops rows. Caught by
    `test_sampler_never_returns_more_than_available`.

    `rows` and `modules` are positionally aligned — `modules[i]` is the
    `MODULE` of `rows[i]`, read from the `dev` sheet by the caller (the
    loader deliberately does not carry ground-truth columns on `RawRow`).

    Every module present gets `per_module_floor` rows before any module gets
    an extra; remaining slots then go round-robin over modules in descending
    row count, so the head is proportionally denser without starving the tail.
    """
    if len(rows) != len(modules):
        raise ValueError(
            f"rows and modules must be positionally aligned; got {len(rows)} rows "
            f"and {len(modules)} module labels"
        )

    by_module: dict[str, list[str]] = defaultdict(list)
    for row, module in zip(rows, modules, strict=True):
        by_module[module].append(row.row_uid)
    for keys in by_module.values():
        keys.sort(key=lambda uid: int(uid.split(":")[1]))

    # Descending row count, then module name — never set iteration order,
    # which `04` §5 forbids relying on.
    ordered = sorted(by_module, key=lambda module: (-len(by_module[module]), module))

    taken: dict[str, int] = dict.fromkeys(ordered, 0)
    selected: list[str] = []

    for module in ordered:
        for _ in range(min(per_module_floor, len(by_module[module]))):
            if len(selected) >= target:
                break
            selected.append(by_module[module][taken[module]])
            taken[module] += 1

    while len(selected) < target:
        progressed = False
        for module in ordered:
            if len(selected) >= target:
                break
            if taken[module] < len(by_module[module]):
                selected.append(by_module[module][taken[module]])
                taken[module] += 1
                progressed = True
        if not progressed:
            break  # every row in every module is already selected

    return selected


def modules_covered(row_uids: list[str], rows: list[RawRow], modules: list[str]) -> set[str]:
    """Which modules a given selection actually covers."""
    module_by_uid = {row.row_uid: module for row, module in zip(rows, modules, strict=True)}
    return {module_by_uid[uid] for uid in row_uids if uid in module_by_uid}
