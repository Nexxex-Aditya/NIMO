"""P4 gold-set tests — `specs/gold.md` acceptance criteria.

The gold set is the measurement instrument for L3/L4 (`03` §6). These tests
guard the instrument itself: a malformed or self-inconsistent entry corrupts
every threshold fitted against it, with nothing downstream to catch it.
"""

from pathlib import Path

import pandas as pd
import pytest

from nimo.contracts import GoldUrl, RawRow
from nimo.gold import (
    GoldSetError,
    labelled_correct,
    load_frozen_sample,
    load_gold,
    modules_covered,
    stratify_by_module,
    write_gold,
)
from nimo.loader import load_rows

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
RETAILERS = REPO_ROOT / "config" / "retailers.yaml"
GOLD_FILE = REPO_ROOT / "data" / "gold" / "urls.jsonl"


@pytest.fixture(scope="module")
def dev_rows() -> list[RawRow]:
    return load_rows(WORKBOOK, "dev", RETAILERS)


@pytest.fixture(scope="module")
def dev_modules() -> list[str]:
    return [
        str(module) for module in pd.read_excel(WORKBOOK, sheet_name="dev", dtype=str)["MODULE"]
    ]


@pytest.fixture(scope="module")
def entries() -> list[GoldUrl]:
    return load_gold(GOLD_FILE)


# --- Acceptance criteria 1–4: the committed file ------------------------


def test_gold_file_exists_and_parses(entries: list[GoldUrl]) -> None:
    """AC1/AC2 — every line is a valid GoldUrl."""
    assert GOLD_FILE.exists()
    assert entries


def test_every_row_uid_is_a_real_dev_row(entries: list[GoldUrl], dev_rows: list[RawRow]) -> None:
    """AC3 — and keyed on row_uid, not the colliding nan_key (`01` §14)."""
    valid = {row.row_uid for row in dev_rows}
    for entry in entries:
        assert entry.row_uid in valid, f"{entry.row_uid} is not a dev row"
        assert entry.sheet == "dev"


def test_no_row_uid_appears_twice(entries: list[GoldUrl]) -> None:
    """AC3 — one label per row."""
    uids = [entry.row_uid for entry in entries]
    assert len(set(uids)) == len(uids)


def test_nan_key_matches_the_row_it_claims(entries: list[GoldUrl], dev_rows: list[RawRow]) -> None:
    """The carried nan_key must actually belong to that row_uid.

    It is traceability-only, but a wrong one would mislead anyone reading the
    file back against the workbook.
    """
    by_uid = {row.row_uid: row for row in dev_rows}
    for entry in entries:
        assert entry.nan_key == by_uid[entry.row_uid].nan_key


def test_label_and_url_are_consistent(entries: list[GoldUrl]) -> None:
    """AC4 — `correct` implies an http(s) URL; anything else implies None.

    A URL under a non-correct label would be an unverified URL silently
    entering the measurement set.
    """
    for entry in entries:
        if entry.label == "correct":
            assert entry.url is not None
            assert entry.url.startswith(("http://", "https://"))
        else:
            assert entry.url is None


def test_every_entry_carries_real_evidence(entries: list[GoldUrl]) -> None:
    """`specs/gold.md`: "Looks right" is not evidence."""
    for entry in entries:
        assert len(entry.evidence.strip()) > 40, f"{entry.row_uid} evidence is too thin"
        assert entry.verified_on


def test_correct_entries_point_at_distinct_pages(entries: list[GoldUrl]) -> None:
    """Two rows resolving to one URL would mean one of them is mislabelled."""
    urls = [entry.url for entry in labelled_correct(entries)]
    assert len(set(urls)) == len(urls)


# --- Acceptance criterion 7: the loader fails loud ----------------------


def test_malformed_line_raises_rather_than_being_skipped(tmp_path: Path) -> None:
    """AC7 — a skipped entry shrinks the measurement set with no error."""
    bad = tmp_path / "urls.jsonl"
    bad.write_text('{"row_uid": "dev:1", "not_a_field": true}\n', encoding="utf-8")
    with pytest.raises(GoldSetError, match="not a valid GoldUrl"):
        load_gold(bad)


def test_url_under_a_non_correct_label_raises(tmp_path: Path) -> None:
    bad = tmp_path / "urls.jsonl"
    entry = GoldUrl(
        row_uid="dev:1",
        nan_key=1,
        sheet="dev",
        url=None,
        page_title=None,
        label="ambiguous",
        evidence="two defensible pages, neither confirmed",
        verified_on="2026-09-10",
    )
    payload = entry.model_dump_json().replace('"url":null', '"url":"https://example.com"')
    bad.write_text(payload + "\n", encoding="utf-8")
    with pytest.raises(GoldSetError, match="must have url=None"):
        load_gold(bad)


def test_correct_label_without_a_url_raises(tmp_path: Path) -> None:
    bad = tmp_path / "urls.jsonl"
    entry = GoldUrl(
        row_uid="dev:1",
        nan_key=1,
        sheet="dev",
        url=None,
        page_title=None,
        label="ambiguous",
        evidence="placeholder evidence long enough to pass the length check",
        verified_on="2026-09-10",
    )
    payload = entry.model_dump_json().replace('"label":"ambiguous"', '"label":"correct"')
    bad.write_text(payload + "\n", encoding="utf-8")
    with pytest.raises(GoldSetError, match="requires an http"):
        load_gold(bad)


def test_duplicate_row_uid_raises(tmp_path: Path) -> None:
    bad = tmp_path / "urls.jsonl"
    entry = GoldUrl(
        row_uid="dev:1",
        nan_key=1,
        sheet="dev",
        url=None,
        page_title=None,
        label="no_page_found",
        evidence="searched thoroughly, no product page exists for this row",
        verified_on="2026-09-10",
    )
    line = entry.model_dump_json()
    bad.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(GoldSetError, match="appears twice"):
        load_gold(bad)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(GoldSetError, match="not found"):
        load_gold(tmp_path / "absent.jsonl")


def test_write_then_read_round_trips(tmp_path: Path, entries: list[GoldUrl]) -> None:
    path = tmp_path / "urls.jsonl"
    write_gold(entries, path)
    assert load_gold(path) == sorted(entries, key=lambda e: (e.sheet, e.row_uid))


# --- Acceptance criteria 5–6: the sampler -------------------------------


def test_sampler_is_deterministic(dev_rows: list[RawRow], dev_modules: list[str]) -> None:
    """AC5 — `04` §5. No randomness anywhere in the selection."""
    first = stratify_by_module(dev_rows, dev_modules, target=50)
    second = stratify_by_module(dev_rows, dev_modules, target=50)
    assert first == second
    assert len(first) == 50


def test_stratification_beats_a_proportional_sample(
    dev_rows: list[RawRow], dev_modules: list[str]
) -> None:
    """AC6 — the point of stratifying at all.

    `01` §9: the top 4 modules are 317/412 of dev, so a proportional sample of
    50 reaches only ~12 of the 27 modules and the tail is unmeasurable.
    """
    selected = stratify_by_module(dev_rows, dev_modules, target=50)
    covered = modules_covered(selected, dev_rows, dev_modules)
    total_modules = len(set(dev_modules))
    proportional_reach = sum(
        1
        for module in set(dev_modules)
        if round(50 * dev_modules.count(module) / len(dev_modules)) >= 1
    )
    assert len(covered) > proportional_reach
    assert len(covered) >= total_modules - 1


def test_sampler_rejects_misaligned_inputs(dev_rows: list[RawRow]) -> None:
    """Positional alignment is the function's core assumption — fail loud."""
    with pytest.raises(ValueError, match="positionally aligned"):
        stratify_by_module(dev_rows, ["ONLY", "THREE", "MODULES"], target=10)


def test_sampler_never_returns_more_than_available(
    dev_rows: list[RawRow], dev_modules: list[str]
) -> None:
    selected = stratify_by_module(dev_rows, dev_modules, target=10_000)
    assert len(selected) == len(dev_rows)
    assert len(set(selected)) == len(selected)


# --- Coverage reporting (not a gate — `specs/gold.md` says so) ----------


# Two rows were labelled before the sample was frozen, while the sampler was
# still ordering within a module by `nan_key` (which is not unique — `01` §14).
# Fixing that changed which 50 rows the sampler picks. The verification work on
# these two is real and was kept rather than discarded; they are named here so
# the exception is explicit and auditable rather than a silently relaxed test.
PRE_FREEZE_LABELS = {"dev:205", "dev:410"}


def test_frozen_sample_still_matches_the_sampler(
    dev_rows: list[RawRow], dev_modules: list[str]
) -> None:
    """The drift guard the frozen sample exists for.

    If the sampler changes, this fails loudly rather than silently re-basing
    the measurement set under labels already written against the old one —
    which is exactly what happened once during P4.
    """
    assert load_frozen_sample() == stratify_by_module(dev_rows, dev_modules, target=50)


def test_frozen_sample_covers_every_dev_module(
    dev_rows: list[RawRow], dev_modules: list[str]
) -> None:
    """AC6, against the committed artifact rather than a recomputation."""
    covered = modules_covered(load_frozen_sample(), dev_rows, dev_modules)
    assert covered == set(dev_modules)


def test_every_labelled_row_comes_from_the_frozen_sample(entries: list[GoldUrl]) -> None:
    """Labels must not drift toward easy-to-find products.

    Otherwise L3 measures something easier than the real task. The two
    documented pre-freeze labels are the only exceptions.
    """
    sample = set(load_frozen_sample())
    for entry in entries:
        assert entry.row_uid in sample or entry.row_uid in PRE_FREEZE_LABELS, (
            f"{entry.row_uid} was labelled but is neither in the frozen sample nor "
            f"a documented pre-freeze label"
        )
