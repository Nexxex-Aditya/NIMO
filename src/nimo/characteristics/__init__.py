"""P12 characteristic extraction — `specs/characteristics.md`.

Public surface only.
"""

from nimo.characteristics.config import (
    CONFIG_PATH,
    CharacteristicsConfig,
    CharacteristicsConfigError,
    PracticeDefault,
    load_characteristics_config,
)
from nimo.characteristics.evaluate import (
    ApplicabilityReport,
    CharacteristicAccuracy,
    accuracy_report,
    applicability_report,
    format_accuracy,
    format_applicability,
    load_characteristic_labels,
)
from nimo.characteristics.extract import (
    CharacteristicExtractor,
    ImageFetchFn,
    characteristics_block,
    evidence_block,
    guideline_index,
    relevant_excerpt,
)
from nimo.characteristics.gate import (
    CHARACTERISTIC_COLUMNS,
    applicable_rules,
    empty_values,
    from_entity,
    gate_only,
)
from nimo.characteristics.validate import Validation, normalise, validate

__all__ = [
    "CHARACTERISTIC_COLUMNS",
    "CONFIG_PATH",
    "ApplicabilityReport",
    "CharacteristicAccuracy",
    "CharacteristicExtractor",
    "ImageFetchFn",
    "CharacteristicsConfig",
    "CharacteristicsConfigError",
    "PracticeDefault",
    "Validation",
    "accuracy_report",
    "applicability_report",
    "applicable_rules",
    "characteristics_block",
    "empty_values",
    "evidence_block",
    "format_accuracy",
    "format_applicability",
    "from_entity",
    "gate_only",
    "guideline_index",
    "load_characteristic_labels",
    "load_characteristics_config",
    "normalise",
    "relevant_excerpt",
    "validate",
]
