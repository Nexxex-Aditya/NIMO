"""Query x evidence -> `MatchFeatures` — `03` §4 stage 4, `specs/match.md` §3.

Pure. No network, no LLM, no clock.

**P3's parser runs on the page title too**, so both sides of every comparison
are in the same shape. A separate page-side parser would drift from the
query-side one, and then "size mismatch" would sometimes mean "the two parsers
disagree" — a difference invisible in the output and impossible to debug from
a score. Reuse also means P3's measured fixes (the `N x` claim-word guard,
spelled-out units, Unicode-aware tokenizing) apply to page text for free.
"""

from urllib.parse import urlsplit

from nimo.contracts import CandidateEvidence, MatchFeatures, ProductQuery
from nimo.loader import barcode_valid
from nimo.match.config import MatchConfig
from nimo.normalize import extract_variant_terms, load_vocabularies, parse_count, parse_size

# GTIN lengths that a page value must have to be worth comparing. Same set the
# loader uses for the query side (`01` §3): 6- and 7-digit values are not
# GTINs, and comparing one would be comparing a hole to a real identifier.
_GTIN_LENGTHS = frozenset({8, 12, 13, 14})


def page_gtin_valid(gtin: str | None) -> bool:
    """Whether a page-side GTIN is worth comparing at all."""
    if gtin is None:
        return False
    digits = gtin.strip()
    return digits.isdigit() and len(digits) in _GTIN_LENGTHS


def query_gtin_valid(query: ProductQuery) -> bool:
    """Whether the query side has a usable GTIN.

    **Both conditions matter.** `01` §3 is an entire document about an
    identifier silently reshaped by a spreadsheet: `barcode_corrupt` marks the
    rounded values, and `barcode_valid` rejects the 6-7 digit survivors that
    are not GTINs. Comparing a rounded `5000000000000` against a real page
    GTIN would reject every correct candidate for that row.
    """
    return query.barcode is not None and not query.barcode_corrupt and barcode_valid(query.barcode)


def barcode_exact(query: ProductQuery, evidence: CandidateEvidence) -> bool | None:
    """`True`/`False` when both sides are usable, `None` when they are not.

    `03` §3 gave this field three states rather than two precisely so that
    "cannot evaluate" is distinguishable from "does not match" — on `dev` the
    first is the case for 394 of 412 rows.
    """
    if not query_gtin_valid(query) or not page_gtin_valid(evidence.gtin):
        return None
    assert query.barcode is not None  # query_gtin_valid guarantees it
    assert evidence.gtin is not None
    return query.barcode.strip() == evidence.gtin.strip()


def page_text(evidence: CandidateEvidence, config: MatchConfig) -> str:
    """The page text identity is read from.

    Title first, then a bounded slice of body. Body text on a real page runs
    to hundreds of KB and is mostly navigation, reviews and cross-sells —
    unbounded, it swamps variant overlap with unrelated brand names.
    """
    parts = [evidence.title or "", evidence.body_text[: config.page_text_chars]]
    return " ".join(part for part in parts if part).strip()


def brand_match(query: ProductQuery, evidence: CandidateEvidence, text: str) -> float:
    """0..1. A page for a different brand is a different product.

    Checks the URL as well as the text: retailer URLs carry the brand as a
    path segment far more reliably than a title carries it in a comparable
    form (`boots.com/aquafresh-whitening-...`).
    """
    token = query.brand.split()[0].lower().strip() if query.brand.strip() else ""
    if not token:
        return 0.0
    haystack = f"{text} {evidence.url}".lower()
    if token in haystack:
        return 1.0
    # A brand written with punctuation or spacing differences still counts —
    # `ORAL B` vs `oral-b`, `THE HUMBLE CO.` vs `humble`.
    squashed = "".join(ch for ch in haystack if ch.isalnum())
    return 1.0 if "".join(ch for ch in token if ch.isalnum()) in squashed else 0.0


def variant_overlap(query: ProductQuery, text: str) -> float:
    """Fraction of the query's variant terms present on the page.

    Asymmetric on purpose: the page legitimately says more than the query does
    (reviews, related products, marketing), so scoring the intersection
    against the *query's* terms asks "does the page mention what identifies
    this product" rather than "are these documents similar". `03` §1a measured
    variant terms to be the only thing separating Aquafresh Extra Care from
    Intense Clean.
    """
    wanted = {term.lower() for term in query.tokens.variant_terms if len(term) > 2}
    if not wanted:
        return 0.0
    lowered = text.lower()
    return sum(1 for term in wanted if term in lowered) / len(wanted)


def size_match(query: ProductQuery, text: str) -> tuple[str, float | None]:
    """`("exact"|"unit_converted"|"mismatch"|"absent", page_size)`.

    `unit_converted` is reported when the two agree only after normalizing to
    ml or g — a real case (`500ml` vs `0.5l`), and worth distinguishing from
    an exact string match because it is one normalization step further from
    certainty.
    """
    query_ml, query_g = query.tokens.size_ml_equiv, query.tokens.size_g_equiv
    if query_ml is None and query_g is None:
        return "absent", None

    page_value, _page_unit, page_ml, page_g = parse_size(text)
    if page_ml is None and page_g is None:
        return "absent", None

    # Never compare across dimensions. `03` §3's size note: toothpaste is not
    # water, so g and ml are not interchangeable and coercing them would
    # substitute a plausible wrong number for an honestly missing one.
    for query_side, page_side in ((query_ml, page_ml), (query_g, page_g)):
        if query_side is not None and page_side is not None:
            if abs(query_side - page_side) < 0.01:
                # `exact` means the two also agreed BEFORE normalization;
                # `unit_converted` means they agreed only after (500ml vs
                # 0.5l), which is one step further from certainty.
                exact = page_value == query.tokens.size_value
                return ("exact" if exact else "unit_converted"), page_side
            return "mismatch", page_side
    return "absent", None


def count_match(query: ProductQuery, text: str) -> str:
    """`"exact"|"mismatch"|"absent"`. Multipack count is a HARD identity
    attribute (`03` §4 stage 0) — a 2-pack and a single are different
    products, and this must not soften back into fuzzy text similarity."""
    _, _, _, claim_words = load_vocabularies()
    query_count = query.tokens.count
    page_count = parse_count(text, claim_words)
    if query_count is None and page_count is None:
        return "absent"
    # `03` §3: `count is None` means 1. Treating absent-vs-1 as a mismatch
    # would demote correct candidates on every single-unit row.
    left = query_count if query_count is not None else 1
    right = page_count if page_count is not None else 1
    return "exact" if left == right else "mismatch"


def format_consistent(query: ProductQuery, text: str) -> bool | None:
    """Whether the page mentions the query's format hints. `None` when the
    query has none — 160 of 412 `dev` rows, where this feature cannot speak."""
    hints = [hint.lower() for hint in query.tokens.format_hints]
    if not hints:
        return None
    lowered = text.lower()
    return any(hint in lowered for hint in hints)


def retailer_domain_match(
    query: ProductQuery, evidence: CandidateEvidence, domain: str | None
) -> bool:
    """Whether the candidate is on the row's own retailer's domain.

    Corroboration, not proof: the same product legitimately appears on many
    retailers, and `01` §5 shows the organizers' own answer crossing both
    retailer and market.
    """
    if not domain:
        return False
    host = (urlsplit(evidence.url).hostname or "").lower()
    return host == domain.lower() or host.endswith(f".{domain.lower()}")


def market_signal(query: ProductQuery, evidence: CandidateEvidence) -> float:
    """0..1 that the page serves one of the row's markets.

    **Scored, never a filter.** `01` §5: the organizers' `sample_output`
    resolves a `FR,GB` item to an Amazon.in page, so a country hard-filter
    rejects their own reference answer. `04` §12 lists it as forbidden.
    **[PROVISIONAL — Q4]**
    """
    host = (urlsplit(evidence.url).hostname or "").lower()
    for country in query.countries:
        suffix = {"GB": ".co.uk", "IE": ".ie", "FR": ".fr", "DE": ".de", "NL": ".nl"}.get(
            country.upper()
        )
        if suffix and (host.endswith(suffix) or f"{suffix}/" in evidence.url.lower()):
            return 1.0
    # A .com is market-neutral rather than wrong — most manufacturer sites are.
    return 0.5 if host.endswith(".com") else 0.0


def negative_flags(query: ProductQuery, text: str, config: MatchConfig) -> list[str]:
    """Flags present on the page but absent from the query.

    Asymmetric by construction: a query that *is* a refill is not penalised
    for matching a refill page. `03` §4 stage 4 lists these as hard demotions
    because they mark a different SKU of the same product line.
    """
    query_text = f"{query.desc_clean} {' '.join(query.tokens.variant_terms)}".lower()
    lowered = text.lower()
    return sorted(
        flag for flag in config.negative_flags if flag in lowered and flag not in query_text
    )


def compute_features(
    query: ProductQuery,
    evidence: CandidateEvidence,
    config: MatchConfig,
    retailer_domain: str | None = None,
) -> MatchFeatures:
    """The full audit surface for one candidate (`03` §3).

    `raw_score` and `calibrated_prob` are filled by `score.py`; this returns
    them as 0.0 so the feature computation stays independent of the weighting,
    which is what lets the weights be re-tuned at P10 without touching this.
    """
    text = page_text(evidence, config)
    size, _ = size_match(query, text)
    return MatchFeatures(
        barcode_exact=barcode_exact(query, evidence),
        brand_match=brand_match(query, evidence, text),
        size_match=size,
        count_match=count_match(query, text),
        variant_overlap=variant_overlap(query, text),
        format_consistent=format_consistent(query, text),
        retailer_domain_match=retailer_domain_match(query, evidence, retailer_domain),
        market_signal=market_signal(query, evidence),
        negative_flags=negative_flags(query, text, config),
        raw_score=0.0,
        calibrated_prob=0.0,
    )


def variant_terms_of(text: str, brand: str) -> list[str]:
    """Page-side variant terms, via P3's extractor. Exposed for tests and for
    P11's evidence record."""
    _, format_vocab, stopwords, _ = load_vocabularies()
    return extract_variant_terms(text, brand, None, stopwords, format_vocab)
