"""Closed-vocabulary validation, per `&` component — `01` §11, `03` §4 stage
6 step 3, `05` §1.

`01` §11: 187 of `dev`'s 412 ground-truth rows carry `&`-joined combinations
of individually valid values (`'ANTI BACTERIAL & FRESHENING & WHITENING'`),
and no allowed value anywhere contains `&`. Whole-string validation would
reject the organizers' own answers; component-wise validation accepts them
and still refuses anything not assembled from the fixed vocabulary — which
is why `05` §1 can call closed fields structurally immune to injection.
"""

import re
from dataclasses import dataclass

from nimo.contracts import CharacteristicRule

_WHITESPACE = re.compile(r"\s+")
_JOIN = re.compile(r"\s*&\s*")


@dataclass(frozen=True)
class Validation:
    """The outcome for one characteristic. `value` is what gets written;
    `rejected` is what the model said when it was refused, for the trace."""

    value: str | None
    rejected: str | None
    reason: str | None


def normalise(raw: str) -> str:
    """Whitespace collapsed, uppercased, `&` joins canonicalised to ` & `.
    Ground truth is uppercase throughout `dev`; the vocabulary is too."""
    collapsed = _WHITESPACE.sub(" ", raw).strip().upper()
    return " & ".join(part.strip() for part in _JOIN.split(collapsed) if part.strip())


def validate(rule: CharacteristicRule, raw: str | None) -> Validation:
    """Validate one answer against its rule. `None` is a legitimate answer."""
    if raw is None:
        return Validation(value=None, rejected=None, reason=None)
    value = normalise(raw)
    if not value:
        return Validation(value=None, rejected=None, reason=None)
    if rule.open_close == "Open-ended":
        # Guideline conformance is the prompt's job; `01` §6 notes even dev
        # carries `'1'` where the guideline wants `99%`.
        return Validation(value=value, rejected=None, reason=None)

    allowed = {normalise(item) for item in rule.allowed_values}
    components = value.split(" & ")
    bad = [component for component in components if component not in allowed]
    if bad:
        return Validation(
            value=None,
            rejected=value,
            reason=f"component(s) {bad} not in the allowed values for "
            f"{rule.characteristic} under {rule.module}",
        )
    return Validation(value=value, rejected=None, reason=None)
