"""P5 model tests — `specs/classify.md` §10.

Synthetic `ProductQuery` rows, so these stay fast and independent of the
workbook. The real-data measurements live in `test_evaluate.py`.
"""

import pytest

from nimo.classify import (
    ClassifierError,
    ClassifyConfig,
    ModuleClassifier,
    classified_text,
    load_classify_config,
)
from nimo.contracts import DescTokens, ProductQuery

CONFIG = ClassifyConfig(ngram_sizes=(4,), use_brand=False, unseen_margin=0.2)

EMPTY_TOKENS = DescTokens(
    variant_terms=[],
    size_value=None,
    size_unit=None,
    size_ml_equiv=None,
    size_g_equiv=None,
    count=None,
    format_hints=[],
    stripped_junk=[],
)


def query(row_uid: str, desc_clean: str, brand: str = "AQUAFRESH") -> ProductQuery:
    return ProductQuery(
        row_uid=row_uid,
        nan_key=1,
        item_code=1,
        barcode=None,
        barcode_raw=None,
        barcode_corrupt=False,
        brand_raw=f"{brand} (HALEON)",
        brand=brand,
        brand_owner="HALEON",
        brand_encoding_suspect=False,
        retailer_raw="P00R4 (GB) BOOTS",
        retailer="BOOTS",
        countries=["GB"],
        desc_raw=desc_clean,
        desc_encoding_suspect=False,
        desc_clean=desc_clean,
        tokens=EMPTY_TOKENS,
    )


PASTE = "TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)"
BRUSH = "TOOTHBRUSHES - MANUAL - REGULAR"

TRAINING = [
    (query("dev:0", "aquafresh whitening toothpaste 100ml"), PASTE),
    (query("dev:1", "colgate total toothpaste 75ml"), PASTE),
    (query("dev:2", "oral-b manual toothbrush medium"), BRUSH),
    (query("dev:3", "wisdom manual toothbrush soft"), BRUSH),
]


def fitted() -> ModuleClassifier:
    return ModuleClassifier.fit([q for q, _ in TRAINING], [m for _, m in TRAINING], CONFIG)


# --- the text the classifier reads ------------------------------------------


def test_classified_text_is_desc_clean_only_by_default() -> None:
    """No ground truth, no brand, no raw description in the feature path."""
    assert classified_text(query("dev:0", "aquafresh whitening"), CONFIG) == "aquafresh whitening"


def test_use_brand_prepends_brand_when_enabled() -> None:
    config = ClassifyConfig(ngram_sizes=(4,), use_brand=True, unseen_margin=0.2)
    assert classified_text(query("dev:0", "whitening"), config) == "AQUAFRESH whitening"


def test_shipped_config_excludes_brand() -> None:
    assert load_classify_config().use_brand is False, (
        "config/classify.yaml must keep use_brand false. Measured leave-one-out over all "
        "412 dev rows: desc_clean alone 80.1% overall / 50.3% macro; BRAND prepended "
        "72.6% / 46.8%. Brand does not predict module — ORAL-B makes manual brushes, "
        "electric brushes, refill heads and toothpaste. specs/classify.md §3c."
    )


def test_shipped_config_ngram_sizes_are_the_swept_default() -> None:
    assert load_classify_config().ngram_sizes == (4,)


# --- fitting -----------------------------------------------------------------


def test_fit_rejects_misaligned_labels() -> None:
    with pytest.raises(ClassifierError, match="positionally aligned"):
        ModuleClassifier.fit([q for q, _ in TRAINING], [PASTE], CONFIG)


def test_fit_rejects_an_empty_training_set() -> None:
    """An empty model would predict nothing and report no error at predict
    time — the masking-failure shape `04` §4 forbids."""
    with pytest.raises(ClassifierError, match="cannot fit on zero rows"):
        ModuleClassifier.fit([], [], CONFIG)


def test_modules_are_sorted_never_set_ordered() -> None:
    assert fitted().modules == sorted([PASTE, BRUSH])


# --- predicting --------------------------------------------------------------


def test_predicts_the_obvious_module() -> None:
    prediction = fitted().predict(query("qa:0", "sensodyne repair toothpaste 75ml"))
    assert prediction.module == PASTE
    assert prediction.runner_up == BRUSH
    assert prediction.runner_up_gap > 0.0
    assert prediction.source == "text_baseline"


def test_prediction_always_emits_a_module_even_for_junk() -> None:
    """Stage [5] is the fallback path (`03` §4 stage 5); a fallback that
    abstains is not one. Trust is carried on `confidence` instead."""
    prediction = fitted().predict(query("qa:1", "zzzz qqqq"))
    assert prediction.module in fitted().modules
    assert prediction.confidence == 0.0


def test_confidence_and_gap_are_consistent_with_the_scores() -> None:
    classifier = fitted()
    subject = query("qa:2", "colgate whitening toothpaste 100ml")
    scored = classifier.score(subject)
    prediction = classifier.predict(subject)
    assert prediction.confidence == pytest.approx(scored[0][0])
    assert prediction.runner_up_gap == pytest.approx(scored[0][0] - scored[1][0])


def test_single_module_model_has_no_runner_up() -> None:
    classifier = ModuleClassifier.fit([TRAINING[0][0]], [PASTE], CONFIG)
    prediction = classifier.predict(query("qa:3", "aquafresh whitening toothpaste 100ml"))
    assert prediction.runner_up is None
    assert prediction.runner_up_gap == 0.0


def test_nearest_example_cites_a_real_training_row() -> None:
    """The transparency surface (`03` §3): a char-4-gram weight explains
    nothing; a cited neighbour a person can open does."""
    prediction = fitted().predict(query("qa:4", "colgate total toothpaste 75ml"))
    assert prediction.nearest_example_row_uid == "dev:1"
    assert prediction.nearest_example_similarity == pytest.approx(1.0)


def test_nearest_example_excludes_the_query_row_itself() -> None:
    """Predicting on a training row must cite its neighbour, not itself —
    otherwise every leave-one-out explanation is circular."""
    prediction = fitted().predict(TRAINING[0][0])
    assert prediction.nearest_example_row_uid != "dev:0"


# --- determinism (`04` §5) ---------------------------------------------------


def test_fit_and_predict_are_deterministic() -> None:
    subject = query("qa:5", "oral-b toothbrush soft medium")
    first = ModuleClassifier.fit([q for q, _ in TRAINING], [m for _, m in TRAINING], CONFIG)
    second = ModuleClassifier.fit([q for q, _ in TRAINING], [m for _, m in TRAINING], CONFIG)
    assert first.predict(subject) == second.predict(subject)
    assert first.predict(subject) == first.predict(subject)


def test_ties_are_broken_by_module_name_not_iteration_order() -> None:
    """Two identical training texts under different labels produce identical
    centroids, so the cosines tie exactly. The winner must be the
    alphabetically first module, every time."""
    rows = [query("dev:0", "identical text"), query("dev:1", "identical text")]
    classifier = ModuleClassifier.fit(rows, ["ZEBRA MODULE", "ALPHA MODULE"], CONFIG)
    scored = classifier.score(query("qa:0", "identical text"))
    assert scored[0][0] == pytest.approx(scored[1][0])
    assert classifier.predict(query("qa:0", "identical text")).module == "ALPHA MODULE"


# --- the unseen arm is computed, never acted on (`specs/classify.md` §6) ------


def test_unseen_scores_are_reported_but_never_routed() -> None:
    classifier = fitted()
    absent = ["TOOTHBRUSHES - MANUAL - INTERDENTAL", "DENTURE FIXATIVES - ADHESIVE POWDER"]
    subject = query("qa:6", "wisdom advanced interdental toothbrush 2pack")

    scored = classifier.unseen_scores(subject, absent)
    assert scored[0][1] == "TOOTHBRUSHES - MANUAL - INTERDENTAL"
    assert scored[0][0] > 0.0

    # ...and the prediction is unaffected by it. Measured on real qa data, this
    # arm gets the product family right and the form wrong roughly 7 times in
    # 11 ("x-press dental stain remover" -> TOOTH STAIN REMOVERS - KITS), so
    # routing on it destroys more answers than it rescues.
    assert classifier.predict(subject).module in classifier.modules
