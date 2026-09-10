"""CanonicalEntity persistence and the registry audit log —
`specs/registry.md` §6, `05` §4.

`data/registry/` is persisted state, deliberately **not** gitignored (`04`
§2): unlike `data/cache/` it is derived-but-valuable, and `03` §5's
warm-start property depends on it surviving a run.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nimo.contracts import CanonicalEntity


class RegistryError(Exception):
    """The registry store was asked to do something unsafe or impossible."""


@dataclass(frozen=True)
class AuditRecord:
    """One registry write. `05` §4 requires every write to be audit-logged,
    append-only, so that a bad merge found later by L6 (`03` §6) is traceable
    and reversible instead of requiring registry reconstruction from scratch.

    Records `row_uid`s, never `nan_key` — the latter collides across genuinely
    different products (`01` §14), which would make the audit trail itself
    ambiguous about what was merged.
    """

    entity_id: str
    row_uids: list[str]
    confidence: float
    tier: str
    run_id: str
    written_at: datetime

    def to_json(self) -> str:
        return json.dumps(
            {
                "entity_id": self.entity_id,
                "row_uids": self.row_uids,
                "confidence": self.confidence,
                "tier": self.tier,
                "run_id": self.run_id,
                "written_at": self.written_at.isoformat(),
            },
            sort_keys=True,
        )


def _looks_like_a_nan_key(row_uid: str) -> bool:
    """`01` §14 guard. A bare integer string is a `nan_key`, not a `row_uid`.

    This exact bug has been introduced twice in this project — once in the
    loader, once in the P4 sampler — and caught twice by tests. Here it would
    be worse than either: a registry keyed on a colliding id serves one
    product's resolved answer for a different product, silently, forever.
    """
    return ":" not in row_uid


def write_entities(path: Path, entities: list[CanonicalEntity]) -> None:
    """Write the whole entity set, sorted by `entity_id`.

    Sorted so the file is diffable and a re-run is byte-identical (`04` §5).
    Whole-file rather than append: entities are updated in place as members
    merge into them, so an append-only entity file would accumulate
    superseded copies. The **audit log** is the append-only artifact.
    """
    for entity in entities:
        for row_uid in entity.member_row_uids:
            if _looks_like_a_nan_key(row_uid):
                raise RegistryError(
                    f"entity {entity.entity_id} has member {row_uid!r}, which is not a row_uid. "
                    f"`01` §14: NAN_KEY collides across different products and must never key "
                    f"registry membership. Expected a value like 'dev:12'."
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [entity.model_dump_json() for entity in sorted(entities, key=lambda e: e.entity_id)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_entities(path: Path) -> list[CanonicalEntity]:
    """Read the entity set. A malformed line raises rather than being skipped.

    `04` §4: a registry that silently drops the line it cannot parse returns a
    Tier-2 miss for a product it has actually already resolved, which looks
    like a cold registry rather than a corrupt one.
    """
    if not path.exists():
        return []
    entities: list[CanonicalEntity] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entities.append(CanonicalEntity.model_validate_json(line))
        except ValueError as error:
            raise RegistryError(
                f"{path}:{number} is not a valid CanonicalEntity: {error}"
            ) from error
    return entities


def append_audit(path: Path, record: AuditRecord) -> None:
    """Append one audit record. Never truncates — `05` §4 says append-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json() + "\n")


def read_audit(path: Path) -> list[str]:
    """Raw audit lines, for tests and for tracing a merge back."""
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
