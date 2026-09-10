"""Character n-gram TF-IDF — `specs/classify.md` §3, §4.

Pure functions, no I/O, no state. Every definition here is stated exactly in
`specs/classify.md` §4 so the implementation cannot drift from the spec
without one of them being visibly wrong.

Why hand-written rather than scikit-learn: `specs/classify.md` §4 — 412 rows
by 27 classes is a hundred lines of arithmetic, and the dependency would need
an `ignore_missing_imports` override (`04` §3) to buy an implementation of
what is below. Keeping it here also keeps every scoring step inspectable,
which `ModulePrediction`'s evidence fields depend on.
"""

import math
import re
from collections import Counter

# Collapse every run of non-word characters to a single space before
# n-gramming. `\w` is Unicode-aware deliberately: `01` §13 records real
# non-ASCII content in this data (`pärla`, `antibactérien`, `nûby`), and P3
# already had one defect where an ASCII-only tokenizer split `nûby` into
# `n` + `by` (`02-decision-log.md`). Do not narrow this to `[a-z0-9]`.
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize_for_ngrams(text: str) -> str:
    """Lowercase, collapse non-word runs to single spaces, pad with spaces.

    The padding is what lets an n-gram represent "this token starts here" —
    without it, `" mint"` and `"amint"` are indistinguishable features.
    """
    collapsed = _NON_WORD.sub(" ", text.lower()).strip()
    return f" {collapsed} "


def char_ngrams(text: str, sizes: tuple[int, ...]) -> list[str]:
    """All character n-grams of `text` at each size, size-tagged.

    Tagged with the size (`"4:aqua"`) so two sizes cannot collide on the same
    substring when several are configured — a 3-gram `"min"` and a prefix of
    the 4-gram `"mint"` are different features and must stay so.
    """
    padded = normalize_for_ngrams(text)
    grams: list[str] = []
    for size in sizes:
        grams.extend(f"{size}:{padded[i : i + size]}" for i in range(len(padded) - size + 1))
    return grams


def document_frequencies(documents: list[list[str]]) -> dict[str, int]:
    """How many documents each term appears in — presence, not count."""
    frequencies: Counter[str] = Counter()
    for document in documents:
        frequencies.update(set(document))
    return dict(frequencies)


def inverse_document_frequencies(
    document_frequency: dict[str, int], n_documents: int
) -> dict[str, float]:
    """Smoothed idf: `log((n + 1) / (df + 1)) + 1`. `specs/classify.md` §4."""
    if n_documents <= 0:
        raise ValueError("n_documents must be positive to compute idf")
    return {
        term: math.log((n_documents + 1) / (frequency + 1)) + 1.0
        for term, frequency in document_frequency.items()
    }


def tfidf_vector(terms: list[str], idf: dict[str, float]) -> dict[str, float]:
    """Sublinear-tf, idf-weighted, L2-normalized sparse vector.

    Terms absent from `idf` are **dropped, not smoothed** — an n-gram never
    observed at fit time carries no information about any class, and giving it
    a floor weight would let unseen noise compete with real evidence.
    """
    counts: Counter[str] = Counter(terms)
    vector = {
        term: (1.0 + math.log(count)) * idf[term] for term, count in counts.items() if term in idf
    }
    return l2_normalize(vector)


def l2_normalize(vector: dict[str, float]) -> dict[str, float]:
    """Scale to unit length. An all-zero vector is returned unchanged rather
    than divided by zero — it means "no known features", which is a real
    state for a row of pure retailer junk, not an error."""
    norm = math.sqrt(sum(weight * weight for weight in vector.values()))
    if norm == 0.0:
        return dict(vector)
    return {term: weight / norm for term, weight in vector.items()}


def sum_vectors(vectors: list[dict[str, float]]) -> dict[str, float]:
    """Elementwise sum. Used for centroids, which are then L2-normalized —
    a sum rather than a mean because after normalization the two are identical
    and the division can only introduce float noise (`specs/classify.md` §4)."""
    total: dict[str, float] = {}
    for vector in vectors:
        for term, weight in vector.items():
            total[term] = total.get(term, 0.0) + weight
    return total


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    """Dot product — equal to cosine similarity for L2-normalized vectors.

    Iterates the smaller side, which matters when comparing a ~200-term
    document against a centroid holding tens of thousands of terms.
    """
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(term, 0.0) for term, weight in left.items())
