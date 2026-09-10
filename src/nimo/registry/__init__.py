"""P6 Canonical Entity Registry & blocking — `specs/registry.md`.

Public surface only. Same rule as the other packages: don't build an API
wider than later phases actually import.
"""

from nimo.registry.block import (
    block_keys,
    entity_id,
    fingerprint,
    fingerprint_block_key,
    gtin_block_key,
)
from nimo.registry.config import (
    RegistryThresholds,
    ThresholdConfigError,
    load_thresholds,
)
from nimo.registry.lookup import RegistryIndex, build_index, lookup
from nimo.registry.pairs import GoldPairError, load_gold_pairs
from nimo.registry.similarity import (
    NGRAM_SIZES,
    fit_identity_idf,
    has_identity_evidence,
    identity_text,
    identity_vector,
    similarity,
)
from nimo.registry.store import (
    AuditRecord,
    RegistryError,
    append_audit,
    read_audit,
    read_entities,
    write_entities,
)
from nimo.registry.unionfind import UnionFind

__all__ = [
    "NGRAM_SIZES",
    "AuditRecord",
    "GoldPairError",
    "RegistryError",
    "RegistryIndex",
    "RegistryThresholds",
    "ThresholdConfigError",
    "UnionFind",
    "append_audit",
    "block_keys",
    "build_index",
    "entity_id",
    "fingerprint",
    "fingerprint_block_key",
    "fit_identity_idf",
    "gtin_block_key",
    "has_identity_evidence",
    "identity_text",
    "identity_vector",
    "load_gold_pairs",
    "load_thresholds",
    "lookup",
    "read_audit",
    "read_entities",
    "similarity",
    "write_entities",
]
