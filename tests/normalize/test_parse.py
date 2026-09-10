"""Unit tests for the normalizer's pure rules — `specs/normalize.md` §1–§5.

No I/O, no network. Each case names the real input string it protects.
"""

import pytest

from nimo.normalize.parse import (
    collapse_whitespace,
    extract_format_hints,
    extract_variant_terms,
    parse_count,
    parse_size,
    strip_duplicate_sizes,
    strip_repeated_brand,
    strip_retailer_suffix,
    strip_unit_fragments,
    strip_unit_of_sale,
    tokenize,
)
from nimo.normalize.vocab import load_vocabularies

UNIT_OF_SALE, FORMAT_VOCAB, STOPWORDS, CLAIM_WORDS = load_vocabularies()


# --- §1a retailer suffix -------------------------------------------------


@pytest.mark.parametrize(
    "desc,retailer_raw,retailer,expected,removed",
    [
        (
            "aquafresh whitening pump 100ml unit 00000012 e0028",
            "E0028 (GB) WAITROSE",
            "WAITROSE",
            "aquafresh whitening pump 100ml unit 00000012",
            ["e0028"],
        ),
        (
            "macleans confidence mouthspray 15ml e00n3",
            "E00N3 (GB) CWS CENSUS",
            "CWS",
            "macleans confidence mouthspray 15ml",
            ["e00n3"],
        ),
        (
            "jason coconut mint toothpaste 119g amazon",
            "AMAZON (GB)",
            "AMAZON",
            "jason coconut mint toothpaste 119g",
            ["amazon"],
        ),
        (
            "12x wisdom smokers brush toothbrush amazon new",
            "AMAZON NEW (GB)",
            "AMAZON",
            "12x wisdom smokers brush toothbrush",
            ["amazon", "new"],
        ),
        (
            "dentex anti plaque mouthwash twin pack home bargains",
            "HOME BARGAINS",
            "HOME BARGAINS",
            "dentex anti plaque mouthwash twin pack",
            ["home", "bargains"],
        ),
    ],
)
def test_strip_retailer_suffix(
    desc: str, retailer_raw: str, retailer: str, expected: str, removed: list[str]
) -> None:
    """§1a — measured on 824/824 real rows; keyed off the row's own RETAILER."""
    result, taken = strip_retailer_suffix(desc, retailer_raw, retailer)
    assert result == expected
    assert taken == removed


def test_retailer_suffix_never_strips_a_foreign_retailer_token() -> None:
    """The whole point of keying off this row's own retailer.

    `boots` is junk on a Boots row and could be content elsewhere; a global
    junk list could not tell the difference.
    """
    result, removed = strip_retailer_suffix("some product boots", "AMAZON (GB)", "AMAZON")
    assert result == "some product boots"
    assert removed == []


def test_retailer_suffix_only_strips_from_the_tail() -> None:
    result, removed = strip_retailer_suffix(
        "amazon basics toothbrush 4 pack", "AMAZON (GB)", "AMAZON"
    )
    assert result == "amazon basics toothbrush 4 pack"
    assert removed == []


# --- §1b/§1c/§1d/§1e other junk classes ----------------------------------


def test_strip_unit_fragments() -> None:
    result, removed = strip_unit_fragments("aquafresh whitening pump 100ml unit 00000012")
    assert collapse_whitespace(result) == "aquafresh whitening pump 100ml"
    assert removed == ["unit 00000012"]


def test_strip_unit_of_sale_codes() -> None:
    result, removed = strip_unit_of_sale("listerine go tabs x8 u", UNIT_OF_SALE)
    assert result == "listerine go tabs x8"
    assert removed == ["u"]


@pytest.mark.parametrize("word", ["free", "extra"])
def test_free_and_extra_are_not_unit_of_sale_junk(word: str) -> None:
    """43 rows say `alcohol free`, 31 say `extra soft`. Both are content.

    They sit in the same frequency band as the real junk codes, which is
    exactly why this guard exists (`config/normalize.yaml`).
    """
    assert word not in UNIT_OF_SALE
    text = f"wisdom mouthwash alcohol {word} 300ml"
    result, removed = strip_unit_of_sale(text, UNIT_OF_SALE)
    assert word in result
    assert removed == []


def test_strip_duplicate_sizes() -> None:
    """94 rows repeat the same size token."""
    result, removed = strip_duplicate_sizes("colgate superfresh 75ml*75ml*sgl")
    assert "75ml" in result
    assert removed == ["75ml"]


def test_strip_repeated_brand() -> None:
    """62 rows repeat the brand mid-string."""
    text = "wisdom mouthwash chlorhexidine 300ml wisdom chlorhexidine mouthwash"
    result, removed = strip_repeated_brand(text, "WISDOM")
    assert collapse_whitespace(result).count("wisdom") == 1
    assert removed == ["wisdom"]


def test_strip_repeated_brand_leaves_a_single_occurrence_alone() -> None:
    text = "wisdom mouthwash 300ml"
    result, removed = strip_repeated_brand(text, "WISDOM")
    assert result == text
    assert removed == []


# --- §2 size -------------------------------------------------------------


@pytest.mark.parametrize(
    "desc,value,unit,ml,g",
    [
        ("aquafresh whitening pump 100ml", 100.0, "ml", 100.0, None),
        ("wisdom mouthwash 300ml", 300.0, "ml", 300.0, None),
        ("crest 3d charcoal tooth paste 85g", 85.0, "g", None, 85.0),
        ("tom's pepermint toothpaste 170g", 170.0, "g", None, 170.0),
        ("jason coconut mint toothpaste 119.00 g", 119.0, "g", None, 119.0),
        ("listerine coolmint 500 millilitres", 500.0, "ml", 500.0, None),
        ("c/dg spearmint sensation*18 gm", 18.0, "g", None, 18.0),
        ("mouthwash 1 litre", 1.0, "ml", 1000.0, None),
        ("toothpaste 1.5 kg bulk", 1.5, "g", None, 1500.0),
        ("no size mentioned at all", None, None, None, None),
    ],
)
def test_parse_size(
    desc: str, value: float | None, unit: str | None, ml: float | None, g: float | None
) -> None:
    assert parse_size(desc) == (value, unit, ml, g)


def test_size_never_sets_both_dimensions() -> None:
    """`03` §3: exactly one of the two equivalents, never coerced across."""
    for desc in ("100ml pump", "85g paste", "1 litre", "2 oz"):
        _, _, ml, g = parse_size(desc)
        assert (ml is None) != (g is None)


@pytest.mark.parametrize(
    "desc,expected_value,expected_unit",
    [
        # 0.2% is concentration; the pack size is the 300ml
        ("wisdom mouthwash chlorhexidine digluconate 0.2% original 300ml", 300.0, "ml"),
        # 50% is a promotion; the pack size is the 75ml
        ("colgate superfresh 75ml*sgl*50% extra", 75.0, "ml"),
    ],
)
def test_percentages_are_never_pack_size(
    desc: str, expected_value: float, expected_unit: str
) -> None:
    """§2 — 12 rows carry a `%`. Concentration or promotion, never size."""
    value, unit, _, _ = parse_size(desc)
    assert (value, unit) == (expected_value, expected_unit)


# --- §3 count ------------------------------------------------------------


@pytest.mark.parametrize(
    "desc,expected",
    [
        ("listerine go tabs x8", 8),
        ("sensodyne complete toothbrush medium x12", 12),
        ("s/d denture tab ext/s x30", 30),
        ("b tooth wipes junior x 6", 6),
        ("oral b rep head x2", 2),
        ("12x wisdom smokers extra hard brush toothbrush", 12),
        ("ultradex sachets, 10 x 15ml", 10),
        ("colgate whitening toothpaste 2 x 150g", 2),
        ("oral b eb 417-2 dual action refills 2s", 2),
        ("c/dg spearmint sensation*10's", 10),
        ("oral-b pro kids toothbrush heads, pack of 8", 8),
        ("philips sonicare replacement heads 1 pack", 1),
        ("morrisons savers twin pack toothbrushes medium", 2),
        ("plackers flossers 1 count", 1),
        ("aquafresh whitening pump 100ml", None),
    ],
)
def test_parse_count(desc: str, expected: int | None) -> None:
    assert parse_count(desc, CLAIM_WORDS) == expected


def test_x_followed_by_a_size_is_not_a_count() -> None:
    """THE size trap. `twin pack x 250ml` must be 2, never 250.

    Found by measurement, not review: an unguarded `x\\s*(\\d+)` captures 250
    here and silently reports a 250-pack (`specs/normalize.md` §3).
    """
    desc = "dentex anti plaque and whitening mouthwash twin pack x 250ml 0.89"
    assert parse_count(desc, CLAIM_WORDS) == 2
    assert parse_size(desc)[:2] == (250.0, "ml")


@pytest.mark.parametrize(
    "desc",
    [
        "colgate total toothpaste 75ml, 3x more effective at fighting plaque",
        "colgate sensitive toothpaste 75ml, 4x more effective for strong teeth",
        "sensodyne pronamel junior toothpaste, 2x stronger enamel defence",
    ],
)
def test_marketing_claims_are_not_multipack_counts(desc: str) -> None:
    """3 of 11 real `N x` occurrences are comparative claims, not packs.

    Unguarded, rule 1 ranks first and turns `2x stronger enamel` into a
    2-pack. These are the three real strings.
    """
    assert parse_count(desc, CLAIM_WORDS) is None


def test_pack_of_n_beats_n_count() -> None:
    """`1 count (pack of 4)` is four items, not one.

    `N count` is Amazon listing boilerplate and ranks last for this reason;
    48 rows carry it and it collides with `pack of N` on most.
    """
    assert parse_count("oral-b heads|1 count (pack of 4)", CLAIM_WORDS) == 4


def test_count_of_one_is_one_not_none() -> None:
    """`None` means "no count expressed", distinct from an explicit 1."""
    assert parse_count("toothpaste (pack of 1)", CLAIM_WORDS) == 1
    assert parse_count("toothpaste", CLAIM_WORDS) is None


# --- §4 / §5 -------------------------------------------------------------


def test_format_hints_are_order_preserved_and_deduplicated() -> None:
    hints = extract_format_hints("mouthwash liquid sachets mouthwash pump", FORMAT_VOCAB)
    assert hints == ["mouthwash", "sachets", "pump"]


def test_variant_terms_exclude_brand_owner_format_and_stopwords() -> None:
    terms = extract_variant_terms(
        "aquafresh whitening pump 100ml", "AQUAFRESH", "HALEON", STOPWORDS, FORMAT_VOCAB
    )
    assert terms == ["whitening"]


def test_variant_terms_keep_non_ascii_words_intact() -> None:
    """23 rows carry legitimate non-ASCII. An ASCII-only tokenizer split
    `nûby` into `n` + `by` and produced the meaningless term `by`."""
    assert tokenize("nûby toddler toothpaste") == ["nûby", "toddler", "toothpaste"]
    terms = extract_variant_terms("nûby toddler paste", "NUBY", None, STOPWORDS, FORMAT_VOCAB)
    assert "nûby" in terms
    assert "by" not in terms


def test_collapse_whitespace() -> None:
    assert collapse_whitespace("  a   b \t c \n") == "a b c"
