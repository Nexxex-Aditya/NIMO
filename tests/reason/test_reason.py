"""P13 tests — `specs/reason.md` §4. The groundedness fixture `03` §4 stage 7
names is the gate: evidence lacking a fact ⇒ the reasoning does not assert it.
"""

import re
from pathlib import Path
from typing import Literal

import pytest

from nimo.characteristics import CHARACTERISTIC_COLUMNS
from nimo.contracts import (
    AdjudicationVerdict,
    CandidateEvidence,
    CharacteristicValues,
    ModulePrediction,
    Reasoning,
    RegistryLookupResult,
    Selection,
)
from nimo.match import load_match_config, select
from nimo.reason import ReasonConfig, ReasonConfigError, compose, load_reason_config
from tests.characteristics.test_characteristics import PASTE
from tests.match.test_match import page, query

CONFIG = load_reason_config()
MISS = RegistryLookupResult(hit=False, tier="miss", entity=None, similarity=None)


def prediction(**overrides: object) -> ModulePrediction:
    base = dict(
        row_uid="dev:0",
        module=PASTE,
        confidence=0.82,
        runner_up="TOOTH STAIN REMOVERS - FOAM/GEL/LIQUID/PASTE - MULTI DOSE",
        runner_up_gap=0.31,
        nearest_example_row_uid="dev:12",
        nearest_example_similarity=0.82,
        source="text_baseline",
    )
    base.update(overrides)
    return ModulePrediction.model_validate(base)


def values(
    source: Literal["llm", "registry", "gate_only"] = "llm", **coded: str | None
) -> CharacteristicValues:
    filled = dict.fromkeys(CHARACTERISTIC_COLUMNS)
    filled.update(coded)
    applicable = [
        "GLOBAL_CONSUMER_LIFESTAGE_CLAIM",
        "GLOBAL_IF_WITH_FLUORIDE",
        "GLOBAL_ORAL_CARE_FUNCTION",
        "GLOBAL_PACKAGING",
    ]
    return CharacteristicValues(
        row_uid="dev:0",
        module=PASTE,
        values=filled,
        applicable=applicable,
        rejected={},
        source=source,
        prompt_hash="h" if source == "llm" else None,
        model="m" if source == "llm" else None,
    )


def selected(
    pages: list[CandidateEvidence], subject: object = None
) -> tuple[Selection, list[CandidateEvidence]]:
    q = subject if subject is not None else query()
    selection, _ = select(q, pages, load_match_config())  # type: ignore[arg-type]
    return selection, pages


# --- the groundedness gate (`03` §4 stage 7) ------------------------------------------


def test_evidence_without_fluoride_asserts_nothing_about_fluoride() -> None:
    """**The test `03` asks for.** Nothing in the record says fluoride, so the
    reasoning must not assert it — however plausible for a toothpaste. The one
    permitted mention is a statement of ABSENCE ("No evidence for ...; left
    empty"), which is a claim about the record, not the product, and is what
    the organizers' own sample reasoning does ("no clear evidence of ... a
    fluoride claim ... therefore NOT STATED")."""
    subject = query()
    selection, pages = selected([page(title="Aquafresh Whitening Pump 100ml", body="Buy now.")])
    reasoning = compose(
        subject, MISS, selection, prediction(), values(GLOBAL_PACKAGING="TUBE"), pages, CONFIG
    )
    sentences = reasoning.text.split(". ")
    asserting = [s for s in sentences if not s.startswith("No evidence for")]
    assert "fluorid" not in " ".join(asserting).lower()
    assert "WITH FLUORIDE" not in reasoning.text and "WITHOUT FLUORIDE" not in reasoning.text
    absence = [s for s in sentences if s.startswith("No evidence for")]
    assert len(absence) == 1 and "GLOBAL_IF_WITH_FLUORIDE" in absence[0]
    assert reasoning.claims  # something was said, grounded


def test_a_coded_fluoride_value_is_cited_exactly_once_as_a_value() -> None:
    subject = query()
    selection, pages = selected([page(title="Aquafresh Whitening Pump 100ml")])
    reasoning = compose(
        subject,
        MISS,
        selection,
        prediction(),
        values(GLOBAL_IF_WITH_FLUORIDE="WITH FLUORIDE"),
        pages,
        CONFIG,
    )
    assert reasoning.text.count("FLUORIDE") == 2  # the name and the value, in one clause
    assert "GLOBAL_IF_WITH_FLUORIDE = WITH FLUORIDE" in reasoning.text
    assert "characteristics.GLOBAL_IF_WITH_FLUORIDE" in reasoning.claims


def test_every_number_in_the_text_comes_from_a_field() -> None:
    """Provenance: barcode, size, similarity, score — each is a field's
    string form. A number from nowhere is a hallucination by definition."""
    subject = query(barcode="5014697056627")
    right = page(
        url="https://a.test/p", title="Aquafresh Whitening Pump 100ml", gtin="5014697056627"
    )
    selection, pages = selected([right], subject)
    reasoning = compose(subject, MISS, selection, prediction(), values(), pages, CONFIG)
    allowed = {"5014697056627", "100", "0.82", "12"}  # barcode, size, similarity, dev:12
    for number in re.findall(r"\d+(?:\.\d+)?", reasoning.text):
        assert number in allowed, f"{number!r} is not the string form of any input field"


def test_every_coded_value_in_the_text_is_in_values() -> None:
    subject = query()
    selection, pages = selected([page()])
    coded = values(GLOBAL_PACKAGING="TUBE", GLOBAL_ORAL_CARE_FUNCTION="ANTI BACTERIAL & WHITENING")
    reasoning = compose(subject, MISS, selection, prediction(), coded, pages, CONFIG)
    for name, value in re.findall(r"(GLOBAL_[A-Z_]+) = ([A-Z &%0-9.]+?)(?:;|\.)", reasoning.text):
        assert coded.values[name] == value
    assert "GLOBAL_BRISTLE_STRENGTH_CLAIM" not in reasoning.text  # never a non-applicable one


def test_body_text_is_never_quoted() -> None:
    subject = query()
    secret = "XYZZY-UNIQUE-BODY-TOKEN"
    selection, pages = selected([page(body=f"Great paste. {secret} 1450ppm fluoride.")])
    reasoning = compose(subject, MISS, selection, prediction(), values(), pages, CONFIG)
    assert secret not in reasoning.text and "1450" not in reasoning.text
    assert "characters of page text" in reasoning.text  # its existence is stated, not its content


# --- the five identity shapes (`specs/reason.md` §2) ----------------------------------


def test_gtin_accept_is_stated_as_decisive() -> None:
    subject = query(barcode="5014697056627")
    right = page(url="https://www.boots.com/p", title="Aquafresh 100ml", gtin="5014697056627")
    selection, pages = selected([right], subject)
    reasoning = compose(subject, MISS, selection, prediction(), values(), pages, CONFIG)
    assert reasoning.text.startswith("The selected page (boots.com) publishes EAN 5014697056627")
    assert "decisive" in reasoning.text and "selection.gtin_exact" in reasoning.claims


def test_weighted_match_cites_the_features_that_fired() -> None:
    subject = query()
    selection, pages = selected(
        [
            page(url="https://boots.com/a", title="Aquafresh Whitening Pump Toothpaste 100ml"),
            page(url="https://b.test/b", title="Colgate 75ml"),
        ]
    )
    reasoning = compose(subject, MISS, selection, prediction(), values(), pages, CONFIG)
    text = reasoning.text
    assert "ranked first on brand match" in text and "size exact (100 ml)" in text
    assert "variant overlap" in text and "whitening" in text
    assert "ahead of the runner-up by" in text
    assert {"selection.brand_match", "selection.size_match", "selection.runner_up_gap"} <= set(
        reasoning.claims
    )


def test_registry_hit_says_so_and_cites_no_page_features() -> None:
    """`03` §4 stage 7: say it plainly rather than fabricating fresh page-
    evidence language for evidence that was not re-examined."""
    hit = RegistryLookupResult(hit=True, tier="tier0_exact", entity=None, similarity=None)
    selection = Selection(
        url="https://boots.com/p",
        page_title="p",
        confidence=1.0,
        runner_up_gap=0.0,
        features=None,
        adjudicated_by_llm=False,
        resolution_tier="tier0_exact",
        adjudication=None,
    )
    reasoning = compose(
        query(),
        hit,
        selection,
        prediction(source="registry"),
        values(source="registry", GLOBAL_PACKAGING="TUBE"),
        [],
        CONFIG,
    )
    assert reasoning.text.startswith(
        "Identity confirmed by exact barcode match to a previously resolved item"
    )
    assert "carried from the registry record" in reasoning.text
    assert "ranked first" not in reasoning.text and "boots.com" not in reasoning.text
    assert reasoning.claims[:2] == ["registry.tier0_exact", "module.registry"]


def test_tier3_quotes_the_rationale_attributed() -> None:
    subject = query()
    selection, pages = selected(
        [
            page(url="https://a.test/1"),
            page(url="https://b.test/2", title="Aquafresh Whitening 100ml"),
        ]
    )
    verdict = AdjudicationVerdict(
        choice=2,
        decisive_fields=["title", "size"],
        rationale="Only candidate 2 names the 100ml pump.",
        prompt_hash="h",
        model="m",
    )
    adjudicated = selection.model_copy(
        update={"adjudicated_by_llm": True, "resolution_tier": "tier3_llm", "adjudication": verdict}
    )
    reasoning = compose(subject, MISS, adjudicated, prediction(), values(), pages, CONFIG)
    assert (
        "An adjudication step chose it on title, size: Only candidate 2 names the 100ml pump."
        in reasoning.text
    )
    assert "selection.adjudication" in reasoning.claims


def test_abstention_is_stated_and_no_host_appears() -> None:
    subject = query()
    selection, pages = selected([])
    reasoning = compose(
        subject, MISS, selection, prediction(), values(source="gate_only"), pages, CONFIG
    )
    assert reasoning.text.startswith("No candidate page met the evidence threshold")
    assert "http" not in reasoning.text and ".com" not in reasoning.text
    assert "4 characteristic(s) apply to this module; values were not extracted" in reasoning.text


# --- module, characteristics, evidence sentences -----------------------------------


def test_module_sentence_cites_the_nearest_example_and_flags_a_close_call() -> None:
    subject = query()
    selection, pages = selected([page()])
    close = prediction(runner_up_gap=0.01)
    reasoning = compose(subject, MISS, selection, close, values(), pages, CONFIG)
    assert (
        f"Classified as {PASTE} from the description, which most resembles dev:12 (similarity 0.82)"
        in reasoning.text
    )
    assert "a close call against TOOTH STAIN REMOVERS" in reasoning.text
    assert "module.runner_up" in reasoning.claims
    wide = compose(subject, MISS, selection, prediction(), values(), pages, CONFIG)
    assert "close call" not in wide.text


def test_empty_and_rejected_characteristics_are_reported() -> None:
    subject = query()
    selection, pages = selected([page()])
    coded = values(GLOBAL_PACKAGING="TUBE").model_copy(
        update={"rejected": {"GLOBAL_ORAL_CARE_FUNCTION": "MAKES YOU TALLER"}}
    )
    reasoning = compose(subject, MISS, selection, prediction(), coded, pages, CONFIG)
    assert (
        "No evidence for GLOBAL_CONSUMER_LIFESTAGE_CLAIM, GLOBAL_IF_WITH_FLUORIDE; left empty."
        in reasoning.text
    )
    assert (
        "The model proposed MAKES YOU TALLER for GLOBAL_ORAL_CARE_FUNCTION, outside the "
        "allowed values" in reasoning.text
    )
    assert "characteristics.rejected" in reasoning.claims


def test_evidence_sentence_names_only_what_existed() -> None:
    subject = query()
    selection, pages = selected([page(title="T", body="", gtin="5014697056627")])
    reasoning = compose(subject, MISS, selection, prediction(), values(), pages, CONFIG)
    assert (
        "Page evidence used: structured product data (JSON-LD), the page title." in reasoning.text
    )


# --- bounds and determinism ---------------------------------------------------------


def test_max_chars_is_respected_by_dropping_whole_sentences() -> None:
    subject = query()
    selection, pages = selected([page(body="x" * 100)])
    coded = values(
        GLOBAL_PACKAGING="TUBE",
        GLOBAL_IF_WITH_FLUORIDE="WITH FLUORIDE",
        GLOBAL_ORAL_CARE_FUNCTION="WHITENING",
    )
    tight = ReasonConfig(max_chars=200, max_variant_terms_cited=4, low_module_margin=0.05)
    reasoning = compose(subject, MISS, selection, prediction(), coded, pages, tight)
    assert len(reasoning.text) <= 200
    assert reasoning.text.startswith("The selected page")  # identity survives; lower priorities go
    assert reasoning.text.endswith(".")


def test_composition_is_byte_identical() -> None:
    subject = query()
    selection, pages = selected([page()])
    a = compose(
        subject, MISS, selection, prediction(), values(GLOBAL_PACKAGING="TUBE"), pages, CONFIG
    )
    b = compose(
        subject, MISS, selection, prediction(), values(GLOBAL_PACKAGING="TUBE"), pages, CONFIG
    )
    assert a == b and isinstance(a, Reasoning)


def test_shipped_config_and_sample_bar() -> None:
    """The organizers' sample reasoning runs 430-550 chars; the cap leaves
    room for a row with many coded values without becoming an essay."""
    assert 550 <= CONFIG.max_chars <= 2000


def test_config_rejects_a_cap_too_small_to_say_anything(tmp_path: Path) -> None:
    path = tmp_path / "reason.yaml"
    path.write_text(
        "max_chars: 10\nmax_variant_terms_cited: 4\nlow_module_margin: 0.05\n", encoding="utf-8"
    )
    with pytest.raises(ReasonConfigError, match=">= 100"):
        load_reason_config(path)


def test_calibrated_probability_is_quoted_only_when_a_curve_applied() -> None:
    """Without a curve the two numbers are equal by construction and
    "probability" would be an invented word (`specs/reason.md` §3)."""
    from nimo.calibrate import fit_isotonic

    subject = query()
    pages = [page(url="https://boots.com/a", title="Aquafresh Whitening Pump Toothpaste 100ml")]
    plain, _ = select(subject, pages, load_match_config())
    assert (
        "probability"
        not in compose(subject, MISS, plain, prediction(), values(), pages, CONFIG).text
    )
    curve = fit_isotonic([0.1, 0.2, 0.8, 0.9], [False, False, True, True], min_pairs=4)
    calibrated, _ = select(subject, pages, load_match_config(), None, curve)
    text = compose(subject, MISS, calibrated, prediction(), values(), pages, CONFIG).text
    assert "(calibrated probability " in text
