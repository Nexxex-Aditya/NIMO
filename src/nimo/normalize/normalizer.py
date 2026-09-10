"""`RawRow` -> `ProductQuery` — `specs/normalize.md`, `03` §4 stage [0].

Orchestration only: the ordered junk-removal pipeline, then the parsers. All
the rules themselves live in `parse.py`, pure and separately tested.
"""

from pathlib import Path

from nimo.contracts import DescTokens, ProductQuery, RawRow
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
)
from nimo.normalize.vocab import CONFIG_PATH, load_vocabularies


def normalize_row(row: RawRow, config_path: Path = CONFIG_PATH) -> ProductQuery:
    """One row, normalized. Deterministic — same input, same output, always."""
    unit_of_sale_tokens, format_vocab, stopwords, claim_words = load_vocabularies(config_path)

    stripped_junk: list[str] = []
    text = row.desc_raw

    # §1 — order is fixed and matters (specs/normalize.md §1).
    text, removed = strip_retailer_suffix(text, row.retailer_raw, row.retailer)
    stripped_junk.extend(removed)

    text, removed = strip_unit_fragments(text)
    stripped_junk.extend(removed)

    text, removed = strip_unit_of_sale(text, unit_of_sale_tokens)
    stripped_junk.extend(removed)

    text, removed = strip_duplicate_sizes(text)
    stripped_junk.extend(removed)

    text, removed = strip_repeated_brand(text, row.brand)
    stripped_junk.extend(removed)

    desc_clean = collapse_whitespace(text)

    # §2–§5 — parse the cleaned description.
    size_value, size_unit, size_ml_equiv, size_g_equiv = parse_size(desc_clean)
    count = parse_count(desc_clean, claim_words)
    format_hints = extract_format_hints(desc_clean, format_vocab)
    variant_terms = extract_variant_terms(
        desc_clean,
        row.brand,
        row.brand_owner,
        stopwords,
        format_vocab,
    )

    tokens = DescTokens(
        variant_terms=variant_terms,
        size_value=size_value,
        size_unit=size_unit,
        size_ml_equiv=size_ml_equiv,
        size_g_equiv=size_g_equiv,
        count=count,
        format_hints=format_hints,
        stripped_junk=[junk.strip() for junk in stripped_junk if junk.strip()],
    )

    return ProductQuery(**row.model_dump(), desc_clean=desc_clean, tokens=tokens)


def normalize_rows(rows: list[RawRow], config_path: Path = CONFIG_PATH) -> list[ProductQuery]:
    """Batch form. Order preserved exactly — no sorting, no reordering."""
    return [normalize_row(row, config_path) for row in rows]
