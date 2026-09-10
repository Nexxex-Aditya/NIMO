"""Pure parsing rules for the normalizer — `specs/normalize.md` §1–§5.

Every function is deterministic and does no I/O. Vocabularies are passed in;
loading them is `vocab.py`'s job.
"""

import re

# --- §2 size ------------------------------------------------------------
# Volume goes to ml, mass to g, and the two are NEVER interconverted
# (`03` §3's size note).
_VOLUME_FACTORS: dict[str, float] = {
    "ml": 1.0,
    "mls": 1.0,
    "cl": 10.0,
    "l": 1000.0,
    "ltr": 1000.0,
    "litre": 1000.0,
    "litres": 1000.0,
    # spelled-out forms seen in the real data ("listerine coolmint 500
    # millilitres") — without these the row parses to no size at all
    "millilitre": 1.0,
    "millilitres": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
}
_MASS_FACTORS: dict[str, float] = {
    "g": 1.0,
    "gm": 1.0,
    "gms": 1.0,
    "gr": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "mg": 0.001,
    "oz": 28.349523125,
}
_ALL_UNITS = sorted(set(_VOLUME_FACTORS) | set(_MASS_FACTORS), key=len, reverse=True)
_UNIT_ALTERNATION = "|".join(_ALL_UNITS)

_SIZE_RE = re.compile(
    rf"(?<![\w.])(\d+(?:[.,]\d+)?)\s*({_UNIT_ALTERNATION})(?![a-z])",
    re.IGNORECASE,
)
# Guards the 12 rows carrying `0.2%` / `50% extra` — concentration or
# promotion, never pack size (`specs/normalize.md` §2).
_PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%")

# --- §3 count -----------------------------------------------------------
# Order IS the precedence order and is load-bearing: 53 of 824 rows match
# more than one of these. `specs/normalize.md` §3 has the reasoning per rank.
_COUNT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 1. "10 x 15ml" -> 10, "12x wisdom" -> 12. A multiplier in the product
    #    title, ahead of any retailer listing boilerplate. Guarded at call
    #    time against marketing claims — see `_is_claim_multiplier`.
    ("n_x", re.compile(r"\b(\d+)\s*x\b", re.IGNORECASE)),
    # 2. "x8" -> 8. Two guards, both from measurement: the trailing-unit
    #    lookahead stops "twin pack x 250ml" yielding 250, and `(?!\.\d)`
    #    stops "20 x 1.7 gr" capturing the 1 of 1.7.
    (
        "x_n",
        re.compile(
            rf"\bx\s*(\d+)\b(?!\.\d)(?!\s*(?:{_UNIT_ALTERNATION})\b)",
            re.IGNORECASE,
        ),
    ),
    # 3. The dominant pattern — 122 rows.
    ("pack_of_n", re.compile(r"\bpacks?\s+of\s+(\d+)\b", re.IGNORECASE)),
    ("n_pack", re.compile(r"\b(\d+)\s*[-\s]?(?:pack|pk)s?\b", re.IGNORECASE)),
    ("twin_pack", re.compile(r"\btwin\s*pack\b", re.IGNORECASE)),
    ("n_s", re.compile(r"\b(\d+)'?s\b", re.IGNORECASE)),
    # 7. Last on purpose: "N count" is Amazon listing boilerplate, and
    #    "1 count (pack of 4)" means four, not one.
    ("n_count", re.compile(r"\b(\d+)\s*(?:count|ct)\b", re.IGNORECASE)),
)

_NEXT_WORD_RE = re.compile(r"\s*([a-z]+)", re.IGNORECASE)

# --- §1 junk ------------------------------------------------------------
_UNIT_FRAGMENT_RE = re.compile(r"\bunit\s+\d+\b", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
# `\w` rather than `[a-z0-9]` on purpose: 23 rows carry legitimate non-ASCII
# letters (`nûby`, `pärla`, `antibactérien`). An ASCII-only class splits
# `nûby` into `n` + `by` and the variant term becomes the meaningless `by` —
# measured, not hypothetical.
_TOKEN_RE = re.compile(r"[\w&%+.\-']+")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric-ish tokens. Shared by several rules."""
    return _TOKEN_RE.findall(text.lower())


def _alnum(token: str) -> str:
    """Strip punctuation, keep letters/digits including non-ASCII ones."""
    return re.sub(r"[^\w&]", "", token.lower())


def strip_retailer_suffix(desc: str, retailer_raw: str, retailer: str) -> tuple[str, list[str]]:
    """§1a — pop trailing tokens that belong to this row's own RETAILER.

    Measured on 824/824 rows. Data-driven rather than a hardcoded list: it can
    only ever remove something this row's retailer actually contains, so it
    cannot strip legitimate content that happens to be another retailer's
    name. Tail only — a retailer token mid-description may be real content.
    """
    retailer_tokens = {_alnum(token) for token in tokenize(retailer_raw)}
    retailer_tokens |= {_alnum(token) for token in tokenize(retailer)}
    retailer_tokens.discard("")

    words = desc.split()
    removed: list[str] = []
    while words and _alnum(words[-1]) and _alnum(words[-1]) in retailer_tokens:
        removed.append(words.pop())
    removed.reverse()
    return " ".join(words), removed


def strip_unit_fragments(desc: str) -> tuple[str, list[str]]:
    """§1b — `unit 00000012` and friends. 40 rows."""
    removed = _UNIT_FRAGMENT_RE.findall(desc)
    return _UNIT_FRAGMENT_RE.sub(" ", desc), removed


def strip_unit_of_sale(desc: str, unit_of_sale_tokens: frozenset[str]) -> tuple[str, list[str]]:
    """§1c — `each`, `sgl`, `std`, `u`, `ea`, `pmp`, as standalone tokens.

    `free` and `extra` are deliberately absent from that vocabulary — they are
    product content here, not junk (`config/normalize.yaml` says why).
    """
    kept: list[str] = []
    removed: list[str] = []
    for word in desc.split():
        if _alnum(word) in unit_of_sale_tokens:
            removed.append(word)
        else:
            kept.append(word)
    return " ".join(kept), removed


def strip_duplicate_sizes(desc: str) -> tuple[str, list[str]]:
    """§1d — the same normalized size token repeated. 94 rows."""
    seen: set[tuple[str, str]] = set()
    removed: list[str] = []
    result: list[str] = []
    position = 0
    for match in _SIZE_RE.finditer(desc):
        key = (match.group(1).replace(",", "."), match.group(2).lower())
        if key in seen:
            result.append(desc[position : match.start()])
            removed.append(match.group(0))
            position = match.end()
        else:
            seen.add(key)
    result.append(desc[position:])
    return "".join(result), removed


def strip_repeated_brand(desc: str, brand: str) -> tuple[str, list[str]]:
    """§1e — brand occurring more than once; keep the first. 62 rows."""
    brand_clean = brand.strip()
    if len(brand_clean) < 3:
        return desc, []
    pattern = re.compile(rf"\b{re.escape(brand_clean)}\b", re.IGNORECASE)
    matches = list(pattern.finditer(desc))
    if len(matches) < 2:
        return desc, []
    removed: list[str] = []
    result: list[str] = []
    position = 0
    for match in matches[1:]:
        result.append(desc[position : match.start()])
        removed.append(match.group(0))
        position = match.end()
    result.append(desc[position:])
    return "".join(result), removed


def collapse_whitespace(text: str) -> str:
    """§1f."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def parse_size(desc: str) -> tuple[float | None, str | None, float | None, float | None]:
    """§2 — (size_value, size_unit, size_ml_equiv, size_g_equiv).

    First size token wins. Percentages are never sizes. Exactly one of the two
    equivalents is set when a size is found; both are `None` when none is.
    """
    percent_spans = [match.span() for match in _PERCENT_RE.finditer(desc)]
    for match in _SIZE_RE.finditer(desc):
        if any(start <= match.start() < end for start, end in percent_spans):
            continue
        raw_value, raw_unit = match.group(1), match.group(2).lower()
        value = float(raw_value.replace(",", "."))
        if raw_unit in _VOLUME_FACTORS:
            return value, "ml", value * _VOLUME_FACTORS[raw_unit], None
        return value, "g", None, value * _MASS_FACTORS[raw_unit]
    return None, None, None, None


def _is_claim_multiplier(desc: str, end: int, multiplier_claim_words: frozenset[str]) -> bool:
    """`2x stronger enamel` is a marketing claim, not a 2-pack.

    Measured: 3 of 11 `N x` occurrences in the real data are claims
    (`3x more`, `4x more`, `2x stronger`), all followed by a comparative. The
    other 8 are followed by a size (`10 x 15ml`, `2 x 150g`) or a product noun
    (`12x wisdom`, `2x replacement heads`, `1x usb cable`). Keying off the
    following word is what separates them.
    """
    following = _NEXT_WORD_RE.match(desc, end)
    if following is None:
        return False
    return following.group(1).lower() in multiplier_claim_words


def parse_count(desc: str, multiplier_claim_words: frozenset[str]) -> int | None:
    """§3 — first matching pattern in precedence order wins.

    `None` means no count was expressed at all — distinct from an explicit 1
    (`03` §3, `specs/normalize.md` §3).
    """
    for name, pattern in _COUNT_PATTERNS:
        for match in pattern.finditer(desc):
            if name == "n_x" and _is_claim_multiplier(desc, match.end(), multiplier_claim_words):
                continue
            if name == "twin_pack":
                return 2
            return int(match.group(1))
    return None


def extract_format_hints(desc: str, format_hints: frozenset[str]) -> list[str]:
    """§4 — curated closed vocabulary, order-preserved, deduplicated."""
    found: list[str] = []
    for token in tokenize(desc):
        cleaned = _alnum(token)
        if cleaned in format_hints and cleaned not in found:
            found.append(cleaned)
    return found


def extract_variant_terms(
    desc: str,
    brand: str,
    brand_owner: str | None,
    stopwords: frozenset[str],
    format_vocab: frozenset[str],
) -> list[str]:
    """§5 — residual content tokens. Derived, not curated.

    Removes brand/owner tokens, numbers and size-like tokens, format hints,
    and stopwords. What remains is the material that distinguishes two
    variants of the same brand — what `03` §4 stage 4 scores overlap on.
    """
    excluded = {_alnum(token) for token in tokenize(brand)}
    if brand_owner:
        excluded |= {_alnum(token) for token in tokenize(brand_owner)}
    excluded |= format_vocab
    excluded |= stopwords
    excluded.discard("")

    terms: list[str] = []
    for token in tokenize(desc):
        cleaned = _alnum(token)
        if not cleaned or cleaned in excluded or cleaned in terms:
            continue
        if cleaned.isdigit() or _NUMBER_RE.fullmatch(token) or _SIZE_RE.fullmatch(token):
            continue
        terms.append(cleaned)
    return terms
