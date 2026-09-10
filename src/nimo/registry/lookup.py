"""Tier 0 / Tier 1 registry lookup — `03` §4 stage `[1]`, `specs/registry.md`.

Stage `[1]` of the pipeline. A hit here skips stages 2–4 entirely, which is
the entire point of `03` §1a's compute cascade.
"""

from dataclasses import dataclass

from nimo.classify.features import char_ngrams, cosine, tfidf_vector
from nimo.contracts import CanonicalEntity, ProductQuery, RegistryLookupResult
from nimo.registry.block import entity_id, fingerprint_block_key, gtin_block_key
from nimo.registry.config import RegistryThresholds
from nimo.registry.similarity import (
    NGRAM_SIZES,
    has_identity_evidence,
    identity_text,
)

MISS = RegistryLookupResult(hit=False, tier="miss", entity=None, similarity=None)


@dataclass(frozen=True)
class RegistryIndex:
    """Entities grouped by block key, plus the fitted identity idf.

    Grouping by block key is the "never compare against every entity" rule
    from `03` §1a. At this dataset's size a linear scan would be fast enough,
    which is exactly why the grouping has to be structural rather than an
    optimization — it is the thing that keeps precision honest as the registry
    grows, not a speed trick.
    """

    by_entity_id: dict[str, CanonicalEntity]
    identity_by_entity: dict[str, dict[str, float]]
    idf: dict[str, float]


def build_index(
    entities: list[CanonicalEntity],
    identity_texts: dict[str, str],
    idf: dict[str, float],
) -> RegistryIndex:
    """Index a persisted entity set for lookup.

    `identity_texts` maps `entity_id` to the identity text of the row that
    established it — carried alongside rather than recomputed, because a
    `CanonicalEntity` stores brand/size/count but not the variant terms that
    Tier 1 actually compares.
    """
    return RegistryIndex(
        by_entity_id={entity.entity_id: entity for entity in entities},
        identity_by_entity={
            eid: tfidf_vector(char_ngrams(text, NGRAM_SIZES), idf)
            for eid, text in identity_texts.items()
        },
        idf=idf,
    )


def lookup(
    query: ProductQuery, index: RegistryIndex, thresholds: RegistryThresholds
) -> RegistryLookupResult:
    """Tier 0, then Tier 1, then miss. `03` §4 stage 1 steps 2–4.

    **Tier 0** is an exact clean-GTIN match. Measured on this dataset it fires
    zero times in a single pass — 0 barcodes shared between `dev` and `qa`, 0
    duplicated within `qa` — and 412/412 times on a re-run against a warm
    registry (`specs/registry.md` §3). That is not a defect; it is what
    `03` §5's warm-start property means, and this dataset makes it unusually
    visible.

    **Tier 1** compares only inside the block, above `tau_ann`, and returns
    the best match with its similarity so the caller can record a confidence
    discount on `Selection.confidence` (`03` §4 stage 1 step 3).
    """
    # Tier 0 — exact clean GTIN. Measured on this dataset it fires zero times
    # in a single pass (0 barcodes shared dev<->qa, 0 duplicated within qa) and
    # 412/412 on a re-run against a warm registry (`specs/registry.md` §3).
    gtin_key = gtin_block_key(query)
    if gtin_key is not None:
        entity = index.by_entity_id.get(entity_id(gtin_key))
        if entity is not None:
            return RegistryLookupResult(
                hit=True, tier="tier0_exact", entity=entity, similarity=None
            )

    # Tier 1 — fingerprint block. Reached on a Tier-0 miss INCLUDING for rows
    # that carried a clean GTIN: a Tier-0 miss means nobody has resolved that
    # GTIN before, not that the product is new (`block_keys`' docstring has the
    # measurement that forced this correction to `03` §4 stage 1 step 1).
    fingerprint_key = fingerprint_block_key(query)
    if fingerprint_key is None:
        return MISS

    # A row carrying no variant evidence cannot hit, checked before any
    # arithmetic: brand and size alone ARE the block key, so merging on them is
    # merging on zero evidence (`05` §4).
    if not has_identity_evidence(query):
        return MISS

    candidate_id = entity_id(fingerprint_key)
    entity = index.by_entity_id.get(candidate_id)
    if entity is None:
        return MISS

    entity_vector = index.identity_by_entity.get(candidate_id)
    if not entity_vector:
        return MISS

    query_vector = tfidf_vector(char_ngrams(identity_text(query), NGRAM_SIZES), index.idf)
    score = cosine(query_vector, entity_vector)
    if score >= thresholds.tau_ann:
        return RegistryLookupResult(hit=True, tier="tier1_ann", entity=entity, similarity=score)
    return MISS
