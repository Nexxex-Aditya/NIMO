"""`RegistryWriter` — the registry's write and refresh paths, on disk."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from nimo.characteristics import CHARACTERISTIC_COLUMNS
from nimo.contracts import CanonicalEntity, CharacteristicValues
from nimo.registry import read_audit, read_entities
from nimo.run.live import RegistryWriter
from tests.match.test_match import query

TS = datetime(2026, 9, 11, tzinfo=UTC)
PASTE = "TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)"


def entity(
    module: str | None = None, characteristics: dict[str, str] | None = None
) -> CanonicalEntity:
    return CanonicalEntity(
        entity_id="gtin:x",
        barcode="5014697056627",
        brand="AQUAFRESH",
        size_ml_equiv=100.0,
        size_g_equiv=None,
        count=1,
        variant_terms=["whitening"],
        module=module,
        resolved_url="https://boots.com/p",
        page_title="p",
        characteristics=characteristics or {},
        confidence=1.0,
        member_row_uids=["qa:5"],
        resolution_tier="tier2_retrieval",
        created_at=TS,
        updated_at=TS,
    )


def values(source: Literal["llm", "registry", "gate_only"], **coded: str) -> CharacteristicValues:
    filled: dict[str, str | None] = dict.fromkeys(CHARACTERISTIC_COLUMNS)
    filled.update(coded)
    return CharacteristicValues(
        row_uid="qa:9",
        module=PASTE,
        values=filled,
        applicable=list(coded) or ["GLOBAL_IF_WITH_FLUORIDE"],
        rejected={},
        source=source,
        prompt_hash=None,
        model=None,
    )


def writer(tmp_path: Path, stored: CanonicalEntity) -> RegistryWriter:
    return RegistryWriter(
        entities_path=tmp_path / "entities.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        run_id="t",
        entities={stored.entity_id: stored},
    )


def test_refresh_fills_a_missing_module_and_llm_values_and_audits(tmp_path: Path) -> None:
    w = writer(tmp_path, entity())
    q = query(barcode="5014697056627").model_copy(update={"row_uid": "qa:9"})
    assert w.refresh(q, entity(), PASTE, values("llm", GLOBAL_IF_WITH_FLUORIDE="WITH FLUORIDE"))
    stored = read_entities(tmp_path / "entities.jsonl")[0]
    assert stored.module == PASTE
    assert stored.characteristics == {"GLOBAL_IF_WITH_FLUORIDE": "WITH FLUORIDE"}
    assert stored.member_row_uids == ["qa:5", "qa:9"]
    assert len(read_audit(tmp_path / "audit.jsonl")) == 1  # `05` §4: every write


def test_refresh_never_overwrites_a_stored_module(tmp_path: Path) -> None:
    w = writer(tmp_path, entity(module="MOUTHWASH X"))
    q = query(barcode="5014697056627").model_copy(update={"row_uid": "qa:9"})
    w.refresh(q, entity(module="MOUTHWASH X"), PASTE, values("gate_only"))
    assert read_entities(tmp_path / "entities.jsonl")[0].module == "MOUTHWASH X"


def test_gate_only_values_do_not_blank_stored_characteristics(tmp_path: Path) -> None:
    kept = {"GLOBAL_IF_WITH_FLUORIDE": "WITH FLUORIDE"}
    w = writer(tmp_path, entity(characteristics=kept))
    q = query(barcode="5014697056627").model_copy(update={"row_uid": "qa:9"})
    w.refresh(q, entity(characteristics=kept), PASTE, values("gate_only"))
    assert read_entities(tmp_path / "entities.jsonl")[0].characteristics == kept


def test_refresh_with_nothing_to_change_writes_nothing(tmp_path: Path) -> None:
    complete = entity(module=PASTE)
    w = writer(tmp_path, complete)
    q = query(barcode="5014697056627").model_copy(update={"row_uid": "qa:5"})  # already a member
    assert not w.refresh(q, complete, PASTE, values("gate_only"))
    assert not (tmp_path / "audit.jsonl").exists()


def test_a_write_merges_with_what_another_process_wrote_meanwhile(tmp_path: Path) -> None:
    """Two live processes (the UI and a batch run) share the file. A write
    must not clobber an entity the other wrote after this process loaded."""
    mine = entity()
    theirs = entity().model_copy(update={"entity_id": "gtin:theirs", "barcode": "5000000000001"})
    w = writer(tmp_path, mine)
    # the other process writes first
    from nimo.registry import write_entities

    write_entities(tmp_path / "entities.jsonl", [theirs])
    q = query(barcode="5014697056627").model_copy(update={"row_uid": "qa:9"})
    assert w.refresh(q, mine, PASTE, values("llm", GLOBAL_IF_WITH_FLUORIDE="WITH FLUORIDE"))
    ids = sorted(e.entity_id for e in read_entities(tmp_path / "entities.jsonl"))
    assert ids == ["gtin:theirs", "gtin:x"]  # both survive
    assert w.entities["gtin:x"].module == PASTE  # ours is the newer version of ours
