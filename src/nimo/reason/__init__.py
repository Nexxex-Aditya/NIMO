"""P13 reasoning composition — `specs/reason.md`.

Public surface only.
"""

from nimo.reason.compose import (
    CONFIG_PATH,
    ReasonConfig,
    ReasonConfigError,
    Sentence,
    characteristics_sentences,
    compose,
    evidence_sentence,
    identity_sentence,
    load_reason_config,
    module_sentence,
)

__all__ = [
    "CONFIG_PATH",
    "ReasonConfig",
    "ReasonConfigError",
    "Sentence",
    "characteristics_sentences",
    "compose",
    "evidence_sentence",
    "identity_sentence",
    "load_reason_config",
    "module_sentence",
]
