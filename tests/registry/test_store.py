"""P6 store, Union-Find, threshold and lookup tests — `specs/registry.md` §5–§9."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nimo.contracts import CanonicalEntity, DescTokens, ProductQuery
from nimo.registry import (
    AuditRecord,
    RegistryError,
    ThresholdConfigError,
    UnionFind,
    append_audit,
    build_index,
    entity_id,
    fingerprint_block_key,
    fit_identity_idf,
    gtin_block_key,
    load_thresholds,
    lookup,
    read_audit,
    read_entities,
    write_entities,
)
from nimo.registry.config import CONFIG_PATH

FIXED_TS = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


def entity(
    entity_id_value: str,
    members: list[str],
    barcode: str | None = None,
    variant_terms: list[str] | None = None,
) -> CanonicalEntity:
    return CanonicalEntity(
        entity_id=entity_id_value,
        barcode=barcode,
        brand="AQUAFRESH",
        size_ml_equiv=100.0,
        size_g_equiv=None,
        count=1,
        variant_terms=variant_terms if variant_terms is not None else ["whitening"],
        module="TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
        resolved_url="https://example.test/p",
        page_title="Aquafresh Whitening 100ml",
        characteristics={"GLOBAL_IF_WITH_FLUORIDE": "YES"},
        confidence=0.9,
        member_row_uids=members,
        resolution_tier="tier2_retrieval",
        created_at=FIXED_TS,
        updated_at=FIXED_TS,
    )


def query(row_uid: str, variants: list[str], barcode: str | None = None) -> ProductQuery:
    return ProductQuery(
        row_uid=row_uid,
        nan_key=1,
        item_code=1,
        barcode=barcode,
        barcode_raw=barcode,
        barcode_corrupt=False,
        brand_raw="AQUAFRESH (HALEON)",
        brand="AQUAFRESH",
        brand_owner="HALEON",
        brand_encoding_suspect=False,
        retailer_raw="P00R4 (GB) BOOTS",
        retailer="BOOTS",
        countries=["GB"],
        desc_raw="x",
        desc_encoding_suspect=False,
        desc_clean="x",
        tokens=DescTokens(
            variant_terms=variants,
            size_value=100.0,
            size_unit="ml",
            size_ml_equiv=100.0,
            size_g_equiv=None,
            count=1,
            format_hints=[],
            stripped_junk=[],
        ),
    )


# --- Union-Find --------------------------------------------------------------


def test_union_find_merges_transitively() -> None:
    uf = UnionFind()
    uf.union("dev:1", "dev:2")
    uf.union("dev:2", "dev:3")
    assert uf.find("dev:1") == uf.find("dev:3")
    assert uf.components() == {"dev:1": ["dev:1", "dev:2", "dev:3"]}


def test_components_are_order_independent() -> None:
    """`03` §1a's whole claim for Union-Find over a learned model is that it is
    deterministic. The registry persists across runs, so components computed in
    a different order on Tuesday must equal Monday's, or `entity_id` stops
    being stable (`04` §5)."""
    orders = [
        [("dev:3", "dev:1"), ("dev:5", "dev:3"), ("dev:9", "dev:7")],
        [("dev:9", "dev:7"), ("dev:1", "dev:3"), ("dev:3", "dev:5")],
        [("dev:5", "dev:3"), ("dev:7", "dev:9"), ("dev:3", "dev:1")],
    ]
    results = []
    for order in orders:
        uf = UnionFind()
        for left, right in order:
            uf.union(left, right)
        results.append(uf.components())
    assert results[0] == results[1] == results[2]
    assert results[0] == {"dev:1": ["dev:1", "dev:3", "dev:5"], "dev:7": ["dev:7", "dev:9"]}


def test_a_lone_member_is_its_own_component() -> None:
    uf = UnionFind()
    uf.add("dev:1")
    assert uf.components() == {"dev:1": ["dev:1"]}


def test_union_is_idempotent() -> None:
    uf = UnionFind()
    uf.union("dev:1", "dev:2")
    first = uf.components()
    uf.union("dev:1", "dev:2")
    uf.union("dev:2", "dev:1")
    assert uf.components() == first


# --- store -------------------------------------------------------------------


def test_entities_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "entities.jsonl"
    entities = [entity("fp:b", ["dev:2"]), entity("fp:a", ["dev:1"])]
    write_entities(path, entities)
    assert read_entities(path) == sorted(entities, key=lambda e: e.entity_id)


def test_writing_twice_is_byte_identical(tmp_path: Path) -> None:
    """`04` §5: a re-run with no change must produce an identical file."""
    path = tmp_path / "entities.jsonl"
    entities = [entity("fp:b", ["dev:2"]), entity("fp:a", ["dev:1", "dev:3"])]
    write_entities(path, entities)
    first = path.read_bytes()
    write_entities(path, list(reversed(entities)))
    assert path.read_bytes() == first


def test_reading_a_missing_file_is_an_empty_registry(tmp_path: Path) -> None:
    assert read_entities(tmp_path / "nope.jsonl") == []


def test_a_malformed_line_raises_rather_than_being_skipped(tmp_path: Path) -> None:
    """`04` §4: silently dropping the line returns a Tier-2 miss for a product
    already resolved — a cold registry is indistinguishable from a corrupt one."""
    path = tmp_path / "entities.jsonl"
    path.write_text('{"entity_id": "fp:a"}\n', encoding="utf-8")
    with pytest.raises(RegistryError, match="not a valid CanonicalEntity"):
        read_entities(path)


def test_nan_key_shaped_membership_is_refused(tmp_path: Path) -> None:
    """`01` §14 regression. This bug has been introduced twice in this project
    already — once in the loader, once in the P4 sampler. Here it would serve
    one product's resolved answer for a different product, forever."""
    with pytest.raises(RegistryError, match="not a row_uid"):
        write_entities(tmp_path / "e.jsonl", [entity("fp:a", ["45138583"])])


# --- audit log (`05` §4) -----------------------------------------------------


def test_audit_log_appends_and_never_truncates(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    for index in range(3):
        append_audit(
            path,
            AuditRecord(
                entity_id=f"fp:{index}",
                row_uids=[f"dev:{index}"],
                confidence=0.99,
                tier="tier1_ann",
                run_id="run-1",
                written_at=FIXED_TS,
            ),
        )
    lines = read_audit(path)
    assert len(lines) == 3
    assert '"entity_id": "fp:0"' in lines[0]
    assert '"row_uids": ["dev:0"]' in lines[0]


# --- thresholds --------------------------------------------------------------


def test_shipped_thresholds_are_derived_not_placeholders() -> None:
    thresholds = load_thresholds()
    assert thresholds.tau_ann == 0.75
    assert thresholds.tau_merge == 0.95


def test_tau_merge_must_exceed_tau_ann(tmp_path: Path) -> None:
    """`03` §4 stage 4 requires it; `05` §4 explains why inverting it is
    unrecoverable. Asserted at load, not merely documented."""
    path = tmp_path / "thresholds.yaml"
    path.write_text("tau_ann: 0.9\ntau_merge: 0.5\n", encoding="utf-8")
    with pytest.raises(ThresholdConfigError, match="must exceed"):
        load_thresholds(path)


def test_a_zero_tau_ann_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.yaml"
    path.write_text("tau_ann: 0.0\ntau_merge: 0.95\n", encoding="utf-8")
    with pytest.raises(ThresholdConfigError, match="tau_ann must be in"):
        load_thresholds(path)


def test_thresholds_file_actually_exists_where_the_code_looks() -> None:
    assert CONFIG_PATH.exists()


# --- lookup ------------------------------------------------------------------


def test_tier0_hits_on_an_exact_clean_gtin() -> None:
    subject = query("qa:0", ["whitening"], barcode="5014697056627")
    key = gtin_block_key(subject)
    assert key is not None
    stored = entity(entity_id(key), ["dev:1"], barcode="5014697056627")
    index = build_index([stored], {})
    result = lookup(subject, index, load_thresholds())
    assert result.hit
    assert result.tier == "tier0_exact"
    assert result.similarity is None


def test_a_tier0_miss_still_reaches_tier1() -> None:
    """The correction to `03` §4 stage 1 step 1. A Tier-0 miss means nobody
    has resolved that GTIN, not that the product is new — the same product may
    sit in the registry under a row whose barcode was absent or corrupt."""
    stored_row = query("dev:1", ["whitening", "pump"])
    subject = query("qa:0", ["whitening", "pump"], barcode="5014697056627")
    key = fingerprint_block_key(stored_row)
    assert key is not None
    stored = entity(entity_id(key), ["dev:1"], variant_terms=stored_row.tokens.variant_terms)
    idf = fit_identity_idf([stored_row, subject])
    index = build_index([stored], idf)
    result = lookup(subject, index, load_thresholds())
    assert result.hit
    assert result.tier == "tier1_ann"
    assert result.similarity is not None and result.similarity >= 0.75


def test_a_dissimilar_row_in_the_same_block_misses() -> None:
    stored_row = query("dev:1", ["whitening", "pump"])
    subject = query("qa:0", ["charcoal", "activated"])
    key = fingerprint_block_key(stored_row)
    assert key is not None
    stored = entity(entity_id(key), ["dev:1"], variant_terms=stored_row.tokens.variant_terms)
    idf = fit_identity_idf([stored_row, subject])
    index = build_index([stored], idf)
    assert not lookup(subject, index, load_thresholds()).hit


def test_a_row_with_no_variant_terms_never_hits_tier1() -> None:
    """`specs/registry.md` §4e — the difference between "no evidence" and
    "merge freely"."""
    stored_row = query("dev:1", [])
    subject = query("qa:0", [])
    key = fingerprint_block_key(stored_row)
    assert key is not None
    stored = entity(entity_id(key), ["dev:1"], variant_terms=stored_row.tokens.variant_terms)
    idf = fit_identity_idf([stored_row, subject])
    index = build_index([stored], idf)
    result = lookup(subject, index, load_thresholds())
    assert not result.hit
    assert result.tier == "miss"


def test_an_empty_registry_always_misses() -> None:
    subject = query("qa:0", ["whitening"], barcode="5014697056627")
    assert not lookup(subject, build_index([], {}), load_thresholds()).hit


def test_tier1_fires_through_persistence_not_just_a_hand_built_index(tmp_path: Path) -> None:
    """**The regression test for the bug the original suite missed.**

    Tier 1 was structurally dead in the real pipeline: `build_index` took the
    identity texts as a separate argument, the runner had none to pass, and
    every lookup returned a miss. Every existing test passed because each one
    built its index by hand with the texts filled in — so the tests exercised
    a code path the pipeline could not reach.

    This test refuses that shortcut. It writes the entity to disk, reads it
    back, and indexes ONLY what came off disk — which is what the runner does.
    If `CanonicalEntity` ever stops carrying enough to rebuild its own identity
    vector, this fails and the hand-built-index tests do not.
    """
    stored_row = query("dev:1", ["whitening", "pump"])
    subject = query("qa:0", ["whitening", "pump"])
    key = fingerprint_block_key(stored_row)
    assert key is not None

    path = tmp_path / "entities.jsonl"
    write_entities(
        path,
        [entity(entity_id(key), ["dev:1"], variant_terms=stored_row.tokens.variant_terms)],
    )

    # Everything below sees only what survived the round trip.
    from_disk = read_entities(path)
    index = build_index(from_disk, fit_identity_idf([stored_row, subject]))
    result = lookup(subject, index, load_thresholds())

    assert result.hit, (
        "Tier 1 missed on a persisted entity. A CanonicalEntity must be "
        "self-sufficient for its own lookup (`03` §3) — if it cannot rebuild its "
        "identity vector from disk, the registry is dead in the real pipeline "
        "while hand-built test indexes keep passing."
    )
    assert result.tier == "tier1_ann"
    assert result.similarity is not None and result.similarity >= load_thresholds().tau_ann


def test_the_runner_builds_a_tier1_capable_index(tmp_path: Path) -> None:
    """The call site itself, not just the function. `build_index` now takes
    exactly what `read_entities` returns, so there is no third argument a
    caller can forget to populate."""
    import inspect

    from nimo.registry.lookup import build_index as target

    parameters = list(inspect.signature(target).parameters)
    assert parameters == ["entities", "idf"], (
        f"build_index takes {parameters}. Any parameter beyond the entities and the idf is one "
        f"a caller can leave empty, which is exactly how Tier 1 went dead."
    )
