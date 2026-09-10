"""P5 module baseline — `specs/classify.md`.

Public surface only. Same rule as `loader/__init__.py`: don't build an API
wider than later phases actually import.
"""

from nimo.classify.config import ClassifyConfig, ClassifyConfigError, load_classify_config
from nimo.classify.evaluate import (
    ClassifierReport,
    ConfidenceBucket,
    EvaluationError,
    ModuleAccuracy,
    build_report,
    cross_validate,
    format_report,
    leave_one_out,
    stratified_folds,
)
from nimo.classify.features import (
    char_ngrams,
    cosine,
    document_frequencies,
    inverse_document_frequencies,
    l2_normalize,
    normalize_for_ngrams,
    sum_vectors,
    tfidf_vector,
)
from nimo.classify.model import ClassifierError, ModuleClassifier, classified_text

__all__ = [
    "ClassifierError",
    "ClassifierReport",
    "ClassifyConfig",
    "ClassifyConfigError",
    "ConfidenceBucket",
    "EvaluationError",
    "ModuleAccuracy",
    "ModuleClassifier",
    "build_report",
    "char_ngrams",
    "classified_text",
    "cosine",
    "cross_validate",
    "document_frequencies",
    "format_report",
    "inverse_document_frequencies",
    "l2_normalize",
    "leave_one_out",
    "load_classify_config",
    "normalize_for_ngrams",
    "stratified_folds",
    "sum_vectors",
    "tfidf_vector",
]
