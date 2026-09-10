"""P6 Tier-1 similarity tests — `specs/registry.md` §4, §9, §10.

The measured figures here are pinned against the real 412-row `dev` sheet.
They are the evidence behind `config/thresholds.yaml`'s `tau_ann`, so a change
in any of them is a change to a tuned threshold, not a test to update.
"""

import itertools
from pathlib import Path

import pytest

from nimo.contracts import ProductQuery
from nimo.loader import load_rows
from nimo.normalize import normalize_rows
from nimo.registry import (
    fingerprint_block_key,
    fit_identity_idf,
    has_identity_evidence,
    identity_text,
    load_gold_pairs,
    load_thresholds,
    similarity,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
RETAILERS = REPO_ROOT / "config" / "retailers.yaml"
PAIRS_FILE = REPO_ROOT / "data" / "gold" / "pairs.jsonl"

# --- Pinned measurements, `specs/registry.md` §2, §4c, §4d --------------------
EXPECTED_DEV_BLOCKS = 130
EXPECTED_DEV_BLOCKED_PAIRS = 379
EXPECTED_QA_FINGERPRINTED = 220
EXPECTED_QA_BLOCK_HITS = 136  # 61.8% — `04` §1's P6 block-hit-rate gate
EXPECTED_PAIRS_ABOVE_TAU = 4  # 3 proven-same + 1 ambiguous, 0 proven-different
LOWEST_SAME = 0.629  # dev:2 / dev:36
HIGHEST_DIFFERENT = 0.723  # dev:107 / dev:147


@pytest.fixture(scope="module")
def dev() -> list[ProductQuery]:
    return normalize_rows(load_rows(WORKBOOK, "dev", RETAILERS))


@pytest.fixture(scope="module")
def qa() -> list[ProductQuery]:
    return normalize_rows(load_rows(WORKBOOK, "qa", RETAILERS))


@pytest.fixture(scope="module")
def idf(dev: list[ProductQuery]) -> dict[str, float]:
    return fit_identity_idf(dev)


@pytest.fixture(scope="module")
def by_uid(dev: list[ProductQuery]) -> dict[str, ProductQuery]:
    return {query.row_uid: query for query in dev}


# --- identity text -----------------------------------------------------------


def test_identity_text_is_variant_terms_only(by_uid: dict[str, ProductQuery]) -> None:
    """`03` §4 stage 1 step 3 says brand + variants + size + count, never page
    content. Only variants appear in the string because brand, size and count
    are equal across a block by construction — including them would add a
    constant to every comparison and inflate every score toward 1.0, making
    `tau_ann` measure nothing."""
    query = by_uid["dev:0"]
    text = identity_text(query)
    assert text == " ".join(query.tokens.variant_terms)
    assert query.brand.lower() not in text.lower() or query.brand.lower() in [
        term.lower() for term in query.tokens.variant_terms
    ]


# --- the safety rule ---------------------------------------------------------


def test_a_row_with_no_variant_terms_has_no_identity_evidence(
    by_uid: dict[str, ProductQuery],
) -> None:
    """`dev:94` is the literal string `sensodyne 75ml`. Brand and size alone
    ARE the block key, so merging on them is merging on zero evidence."""
    assert by_uid["dev:94"].desc_clean == "sensodyne 75ml"
    assert not has_identity_evidence(by_uid["dev:94"])


def test_evidenceless_rows_score_zero_against_anything(
    by_uid: dict[str, ProductQuery], idf: dict[str, float]
) -> None:
    bare = by_uid["dev:94"]
    for other_uid in ("dev:61", "dev:107", "dev:321"):
        assert similarity(bare, by_uid[other_uid], idf) == 0.0
        assert similarity(by_uid[other_uid], bare, idf) == 0.0
    assert similarity(bare, bare, idf) == 0.0


# --- the non-separability finding, pinned ------------------------------------


def test_a_true_positive_scores_below_a_true_negative(
    by_uid: dict[str, ProductQuery], idf: dict[str, float]
) -> None:
    """**This test asserts a limitation, on purpose.**

    `dev:2`/`dev:36` are the same product (`macleans confidence mouthspray`
    vs `mouth spray`). `dev:107`/`dev:147` are different products (Sensodyne
    Pronamel Intensive Repair *Extra Fresh* vs the *Whitening* variant in
    *Cool Mint*). The false pair scores HIGHER than the true one, and no
    threshold can separate them.

    If this inversion ever disappears, that is a real change in the data or
    the features and `tau_ann` must be re-derived — so this fails loudly
    rather than quietly becoming true. Do not "fix" it by loosening the
    assertion; `specs/registry.md` §4c explains why the pair is unfixable by
    any bag-of-features measure.
    """
    same = similarity(by_uid["dev:2"], by_uid["dev:36"], idf)
    different = similarity(by_uid["dev:107"], by_uid["dev:147"], idf)
    assert same == pytest.approx(LOWEST_SAME, abs=0.005)
    assert different == pytest.approx(HIGHEST_DIFFERENT, abs=0.005)
    assert same < different


def test_tau_ann_admits_every_proven_same_pair_above_the_worst_negative(
    by_uid: dict[str, ProductQuery], idf: dict[str, float]
) -> None:
    """3 of 4 true positives, 0 of 14 true negatives. The missed positive is
    `dev:2`/`dev:36` — a deliberate, recorded recall loss (`specs/registry.md`
    §4d), not an accident."""
    thresholds = load_thresholds()
    pairs = load_gold_pairs(PAIRS_FILE)

    admitted_same = 0
    for pair in pairs:
        score = similarity(by_uid[pair.left_row_uid], by_uid[pair.right_row_uid], idf)
        if pair.label == "different":
            assert score < thresholds.tau_ann, (
                f"proven-different pair {pair.left_row_uid}/{pair.right_row_uid} scores "
                f"{score:.3f} at or above tau_ann={thresholds.tau_ann}. This is a false merge, "
                f"which poisons every future row that blocks against it (`03` §1a, `05` §4)."
            )
        elif pair.label == "same" and score >= thresholds.tau_ann:
            admitted_same += 1

    assert admitted_same == 3


# --- blocking, over the real sheets ------------------------------------------


def test_dev_block_counts_are_unchanged(dev: list[ProductQuery]) -> None:
    blocks: dict[str, list[str]] = {}
    for query in dev:
        key = fingerprint_block_key(query)
        if key is not None:
            blocks.setdefault(key.key, []).append(query.row_uid)
    assert len(blocks) == EXPECTED_DEV_BLOCKS
    pairs = sum(1 for uids in blocks.values() for _ in itertools.combinations(uids, 2))
    assert pairs == EXPECTED_DEV_BLOCKED_PAIRS


def test_qa_block_hit_rate_is_the_gate_number(
    dev: list[ProductQuery], qa: list[ProductQuery]
) -> None:
    """`04` §1's P6 gate. 136/220 = 61.8%, independently measured in `01` §14
    before any of this code existed."""
    dev_keys = {
        key.key for key in (fingerprint_block_key(query) for query in dev) if key is not None
    }
    qa_keys = [fingerprint_block_key(query) for query in qa]
    fingerprinted = [key for key in qa_keys if key is not None]
    assert len(fingerprinted) == EXPECTED_QA_FINGERPRINTED
    assert sum(1 for key in fingerprinted if key.key in dev_keys) == EXPECTED_QA_BLOCK_HITS


def test_tau_ann_fires_on_only_a_handful_of_blocked_pairs(
    dev: list[ProductQuery], idf: dict[str, float]
) -> None:
    """A block is overwhelmingly not one product: of 379 blocked `dev` pairs,
    roughly 4 are genuinely the same. Tier 1 finding 4 of them is the design
    working, not Tier 1 under-firing (`specs/registry.md` §4a)."""
    thresholds = load_thresholds()
    blocks: dict[str, list[ProductQuery]] = {}
    for query in dev:
        key = fingerprint_block_key(query)
        if key is not None:
            blocks.setdefault(key.key, []).append(query)
    fired = [
        (left.row_uid, right.row_uid)
        for members in blocks.values()
        for left, right in itertools.combinations(members, 2)
        if similarity(left, right, idf) >= thresholds.tau_ann
    ]
    assert len(fired) == EXPECTED_PAIRS_ABOVE_TAU


# --- the gold pair set -------------------------------------------------------


def test_gold_pairs_load_and_reference_real_rows(by_uid: dict[str, ProductQuery]) -> None:
    pairs = load_gold_pairs(PAIRS_FILE)
    assert len(pairs) == 20
    for pair in pairs:
        assert pair.left_row_uid in by_uid
        assert pair.right_row_uid in by_uid
        assert pair.evidence.strip(), f"{pair.left_row_uid}/{pair.right_row_uid} has no evidence"


def test_gold_pairs_are_actually_blocked_together(by_uid: dict[str, ProductQuery]) -> None:
    """An adjudicated pair that does not share a block key measures nothing —
    Tier 1 would never compare them."""
    for pair in load_gold_pairs(PAIRS_FILE):
        left = fingerprint_block_key(by_uid[pair.left_row_uid])
        right = fingerprint_block_key(by_uid[pair.right_row_uid])
        assert left is not None and right is not None
        assert left.key == right.key, (
            f"{pair.left_row_uid}/{pair.right_row_uid} are not blocked together"
        )
