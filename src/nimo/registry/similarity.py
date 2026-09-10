"""Tier-1 identity similarity — `specs/registry.md` §4.

The measured finding this module exists under, restated because it governs
every line of it: **no similarity function separates same-product from
different-product on this data.** Three were tested against 20 hand-adjudicated
blocked pairs (`data/gold/pairs.jsonl`) and each has a true positive scoring
below a true negative. The irreducible case is `dev:107`/`dev:147` — Sensodyne
Pronamel Intensive Enamel Repair *Extra Fresh* against the *Whitening* variant
in *Cool Mint*, genuinely different SKUs differing by two words in a
fifteen-word description. It scores 0.723 here, above a real duplicate at
0.629, and no bag-of-features measure can rank it lower, because the pair
really is textually near-identical.

So `tau_ann` is not a separating threshold. It is a precision-first cut,
derived in `config/thresholds.yaml`, that accepts a known recall loss.

The TF-IDF primitives are imported from `nimo.classify.features`: they are
generic text-vector functions carrying no classifier state, and duplicating
them here would risk two copies drifting apart.
"""

from nimo.classify.features import (
    char_ngrams,
    cosine,
    document_frequencies,
    inverse_document_frequencies,
    tfidf_vector,
)
from nimo.contracts import ProductQuery

# Character 4-grams, matching P5's swept default. Measured on the pair set:
# n-grams recover `mouthspray` ~ `mouth spray` (0.250 -> 0.629 over variant
# Jaccard), which is the same tokenization-robustness that bought P5 eight
# points. `specs/registry.md` §4c.
NGRAM_SIZES = (4,)


def identity_text(query: ProductQuery) -> str:
    """`03` §4 stage 1 step 3: brand + variant terms + size + count, **never
    page content.**

    Only the variant terms appear in the returned string, and that is correct
    rather than a shortcut: brand, size and count are equal for every member
    of a block by construction, so including them would add a constant to
    every comparison and inflate every score toward 1.0 — making `tau_ann`
    measure nothing.
    """
    return " ".join(query.tokens.variant_terms)


def fit_identity_idf(queries: list[ProductQuery]) -> dict[str, float]:
    """Fit idf over a corpus of identity texts, so a rare variant term weighs
    more than a ubiquitous one like `whitening`."""
    corpus = [char_ngrams(identity_text(query), NGRAM_SIZES) for query in queries]
    return inverse_document_frequencies(document_frequencies(corpus), max(len(corpus), 1))


def identity_vector(query: ProductQuery, idf: dict[str, float]) -> dict[str, float]:
    """The row's Tier-1 identity vector. Empty when it has no variant terms."""
    return tfidf_vector(char_ngrams(identity_text(query), NGRAM_SIZES), idf)


def has_identity_evidence(query: ProductQuery) -> bool:
    """Whether the row carries any variant evidence at all.

    **A row without it can never produce a Tier-1 hit** — an explicit, tested
    rule rather than emergent arithmetic (`specs/registry.md` §4e). `sensodyne
    75ml` is a real `dev` row: brand and size alone are exactly the block key,
    so merging on them is merging on zero evidence, which is registry
    poisoning by definition (`05` §4).
    """
    return bool(query.tokens.variant_terms)


def similarity(left: ProductQuery, right: ProductQuery, idf: dict[str, float]) -> float:
    """Tier-1 identity similarity in `[0, 1]`. Returns 0.0 when either side
    carries no variant evidence, before any arithmetic runs."""
    if not has_identity_evidence(left) or not has_identity_evidence(right):
        return 0.0
    return cosine(identity_vector(left, idf), identity_vector(right, idf))
