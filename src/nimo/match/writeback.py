"""Registry write-back — `03` §4 stage 4, `03` §1a, `05` §4.

P6 built the mechanism (`UnionFind`, `write_entities`, `append_audit`) and
deliberately left the *decision* to P9, because `03` §4 stage 4 gates it on a
confidence signal the registry phase had no way to produce.

**P9 makes the decision, and makes it narrow: write-back fires only on a GTIN
hard-rule accept.** `03` §4 stage 4 offers two triggers — a GTIN accept *or*
`calibrated_prob >= tau_merge` — and the second does not exist yet, because
calibration is P10 and `calibrated_prob` currently mirrors an uncalibrated raw
score (`specs/match.md` §5).

Writing back on that number would put merges into the registry that no later
lookup can distinguish from confirmed ones. `03` §1a: "A wrong merge is worse
than a wrong single-row answer — it poisons every future row that blocks
against it." P6 measured the same thing from the other side: no similarity
function separates same-product from different-product on this data, which is
exactly why the only trigger allowed here is a confirmed identifier rather
than a score.
"""

from dataclasses import dataclass
from datetime import datetime

from nimo.contracts import CanonicalEntity, ProductQuery
from nimo.match.score import ScoredCandidate
from nimo.registry import AuditRecord, UnionFind, block_keys, entity_id


class WriteBackError(Exception):
    """A write-back was attempted that must not happen."""


@dataclass(frozen=True)
class WriteBackDecision:
    """Whether this row's result may enter the registry, and why not if not.

    `reason` is recorded even on a refusal: "we looked and declined" is a
    different finding from "we never considered it", and `05` §4 wants the
    audit trail to make merges reconstructible.
    """

    allowed: bool
    reason: str


def decide(best: ScoredCandidate | None) -> WriteBackDecision:
    """Whether `best` is confirmed strongly enough to persist.

    The only accepted evidence is `barcode_exact is True` — a page GTIN equal
    to a clean query barcode. Everything else waits for P10.
    """
    if best is None:
        return WriteBackDecision(False, "no usable candidate")
    if best.rejected:
        return WriteBackDecision(False, "best candidate was rejected by a hard rule")
    if best.features.barcode_exact is True:
        return WriteBackDecision(True, "gtin_exact")
    return WriteBackDecision(
        False,
        "no confirmed GTIN; `calibrated_prob` is uncalibrated until P10 and must not gate a "
        "merge (`03` §1a, `05` §4)",
    )


def build_entity(
    query: ProductQuery,
    best: ScoredCandidate,
    module: str | None,
    now: datetime,
    existing: CanonicalEntity | None = None,
    characteristics: dict[str, str] | None = None,
) -> CanonicalEntity:
    """The entity this row confirms, merging into `existing` if there is one.

    `characteristics` are this row's validated, applicable values (P12); when
    given they replace the stored ones, so a Tier 0/1 hit later carries what
    this stage produced (`03` §4 stage 6, last paragraph). `None` keeps the
    stored ones — a caller without values must not blank a good entity.

    Membership is unioned by `row_uid`, never `nan_key` — `01` §14, and the
    bug this project has introduced twice already.

    `entity_id` comes from the row's GTIN block key, so the same product
    resolved on another day in another run lands on the same id and Tier 0 can
    warm-start across runs (`03` §5).
    """
    keys = block_keys(query)
    gtin_key = next((key for key in keys if key.method == "exact_gtin"), None)
    if gtin_key is None:
        raise WriteBackError(
            f"{query.row_uid} has no clean GTIN block key, so it cannot have produced a "
            f"gtin_exact accept. This is a caller error: `decide()` must gate this call."
        )

    members = UnionFind()
    members.add(query.row_uid)
    for existing_member in existing.member_row_uids if existing else []:
        members.union(query.row_uid, existing_member)
    merged = sorted(next(iter(members.components().values())))

    return CanonicalEntity(
        entity_id=entity_id(gtin_key),
        barcode=query.barcode,
        brand=query.brand,
        size_ml_equiv=query.tokens.size_ml_equiv,
        size_g_equiv=query.tokens.size_g_equiv,
        count=query.tokens.count if query.tokens.count is not None else 1,
        variant_terms=list(query.tokens.variant_terms),
        module=module if module is not None else (existing.module if existing else None),
        resolved_url=best.evidence.url,
        page_title=best.evidence.title,
        characteristics=(
            dict(characteristics)
            if characteristics is not None
            else (dict(existing.characteristics) if existing else {})
        ),
        confidence=best.score,
        member_row_uids=merged,
        resolution_tier="tier2_retrieval",
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )


def audit_for(entity: CanonicalEntity, run_id: str, now: datetime) -> AuditRecord:
    """The append-only record `05` §4 requires for every registry write.

    Not for compliance theatre: `03` §6's L6 spot-check exists to catch a bad
    merge, and without this the response would be reconstructing the registry
    from scratch rather than reversing one entry.
    """
    return AuditRecord(
        entity_id=entity.entity_id,
        row_uids=list(entity.member_row_uids),
        confidence=entity.confidence,
        tier=entity.resolution_tier,
        run_id=run_id,
        written_at=now,
    )
