"""P5 feature tests — `specs/classify.md` §10.

Pure functions, hand-worked expectations. The TF-IDF definitions are stated
exactly in `specs/classify.md` §4; these tests are what stops the code and the
spec drifting apart silently.
"""

import math

import pytest

from nimo.classify import (
    char_ngrams,
    cosine,
    document_frequencies,
    inverse_document_frequencies,
    l2_normalize,
    normalize_for_ngrams,
    sum_vectors,
    tfidf_vector,
)


def test_normalize_pads_and_collapses() -> None:
    assert (
        normalize_for_ngrams("Aquafresh  Whitening/Pump 100ML")
        == " aquafresh whitening pump 100ml "
    )


def test_char_ngrams_exact_including_padding_boundary() -> None:
    """Padding is what makes an n-gram able to say 'a token starts here'."""
    assert char_ngrams("ab", (3,)) == ["3: ab", "3:ab "]


def test_char_ngrams_are_size_tagged_so_sizes_cannot_collide() -> None:
    """A 3-gram must never be confusable with a 4-gram's prefix."""
    grams = char_ngrams("mint", (3, 4))
    assert "3:min" in grams
    assert "4:mint" in grams
    assert not {gram for gram in grams if not gram.startswith(("3:", "4:"))}


def test_char_ngrams_preserve_non_ascii() -> None:
    """`01` §13 records real non-ASCII in this data, and P3 already shipped one
    defect where an ASCII-only tokenizer split `nûby` into `n` + `by`. A
    feature extractor that drops these silently repeats it."""
    assert "4:nûby" in char_ngrams("nûby", (4,))
    assert "5:pärla" in char_ngrams("pärla", (5,))


def test_document_frequencies_count_presence_not_occurrences() -> None:
    assert document_frequencies([["a", "a", "a"], ["a", "b"]]) == {"a": 2, "b": 1}


def test_idf_matches_the_stated_formula() -> None:
    idf = inverse_document_frequencies({"a": 3, "b": 2}, 3)
    assert idf["a"] == pytest.approx(1.0)
    assert idf["b"] == pytest.approx(math.log(4 / 3) + 1.0)


def test_idf_rejects_a_zero_document_corpus() -> None:
    with pytest.raises(ValueError, match="n_documents must be positive"):
        inverse_document_frequencies({"a": 1}, 0)


def test_tfidf_vector_matches_a_hand_computed_result() -> None:
    """Toy 3-document corpus, worked by hand from `specs/classify.md` §4:
    sublinear tf `1 + log(count)`, smoothed idf `log((n+1)/(df+1)) + 1`, L2."""
    corpus = [["a"], ["a", "b"], ["a", "b", "b"]]
    idf = inverse_document_frequencies(document_frequencies(corpus), len(corpus))
    vector = tfidf_vector(["a", "b", "b"], idf)
    assert vector["a"] == pytest.approx(0.416905, rel=1e-4)
    assert vector["b"] == pytest.approx(0.908951, rel=1e-4)


def test_every_tfidf_vector_has_unit_norm() -> None:
    corpus = [["a", "b"], ["b", "c", "c"], ["a", "c"]]
    idf = inverse_document_frequencies(document_frequencies(corpus), len(corpus))
    for document in corpus:
        vector = tfidf_vector(document, idf)
        assert math.sqrt(sum(w * w for w in vector.values())) == pytest.approx(1.0)


def test_unseen_terms_are_dropped_not_smoothed() -> None:
    """An n-gram never observed at fit time carries no information about any
    class; giving it a floor weight would let unseen noise compete with real
    evidence (`specs/classify.md` §4)."""
    idf = {"a": 1.0}
    assert tfidf_vector(["a", "zzz"], idf) == {"a": pytest.approx(1.0)}


def test_all_zero_vector_is_not_divided_by_zero() -> None:
    """A row of pure retailer junk sharing no n-gram with the training set is
    a real state, not an error."""
    assert l2_normalize({}) == {}
    assert tfidf_vector(["unknown"], {"a": 1.0}) == {}


def test_sum_vectors_is_elementwise() -> None:
    assert sum_vectors([{"a": 1.0, "b": 2.0}, {"b": 0.5}]) == {"a": 1.0, "b": 2.5}


def test_cosine_is_symmetric_and_bounded_for_unit_vectors() -> None:
    left = l2_normalize({"a": 3.0, "b": 4.0})
    right = l2_normalize({"a": 1.0, "c": 1.0})
    assert cosine(left, right) == pytest.approx(cosine(right, left))
    assert 0.0 <= cosine(left, right) <= 1.0
    assert cosine(left, left) == pytest.approx(1.0)


def test_cosine_of_disjoint_vectors_is_zero() -> None:
    assert cosine({"a": 1.0}, {"b": 1.0}) == 0.0
