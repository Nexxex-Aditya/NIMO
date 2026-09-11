"""Per-row characteristic extraction — `03` §4 stage 6, `specs/characteristics.md` §2-§4.

One model call per row, carrying only the applicable characteristics'
guidelines. Page evidence is delimited (`05` §1); the guidelines are the
organizers' and are trusted. The gate is applied before the call and again
after it: a value the model volunteers for a non-applicable characteristic is
dropped, never validated, never written.
"""

import json
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

from nimo.characteristics.config import CharacteristicsConfig, PracticeDefault
from nimo.characteristics.gate import applicable_rules, empty_values, gate_only
from nimo.characteristics.validate import Validation, validate
from nimo.contracts import (
    CandidateEvidence,
    CharacteristicGuideline,
    CharacteristicRule,
    CharacteristicValues,
    ProductQuery,
)
from nimo.llm import LlmCall, LlmClient, PromptTemplate, delimit, render
from nimo.match.adjudicate import query_block

log = structlog.get_logger(__name__)


class _Answer(BaseModel):
    """What the model supplies. Numbers are tolerated for the percentage
    characteristic and stringified; anything else non-string is `None`."""

    model_config = ConfigDict(extra="ignore")

    values: dict[str, str | int | float | None]


def guideline_index(guidelines: list[CharacteristicGuideline]) -> dict[str, str]:
    """`"module\\tcharacteristic" -> text`. A dict keyed by a string, inside
    the module, built from the flat contract list (`03` §3's JSON rule)."""
    return {f"{g.module}\t{g.characteristic}": g.guideline_text for g in guidelines}


def relevant_excerpt(body_text: str, config: CharacteristicsConfig) -> str:
    """The page prefix plus windows around anchor terms, merged in page order,
    cut to `body_text_chars`.

    Measured before designing (`config/characteristics.yaml`): a plain prefix
    hands the model 3000 characters of site navigation on Shopify-style pages
    and never reaches the ingredients. Windows are joined with ` … ` so the
    model can see they are excerpts, not contiguous text.
    """
    if not body_text:
        return ""
    lowered = body_text.lower()
    spans: list[tuple[int, int]] = []
    if config.excerpt_prefix_chars:
        spans.append((0, min(len(body_text), config.excerpt_prefix_chars)))
    half = config.excerpt_window_chars // 2
    for term in config.excerpt_anchor_terms:
        start = 0
        while True:
            index = lowered.find(term, start)
            if index < 0:
                break
            spans.append((max(0, index - half), min(len(body_text), index + len(term) + half)))
            start = index + len(term)
    spans.sort()
    merged: list[list[int]] = []
    for begin, end in spans:
        if merged and begin <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([begin, end])
    separator = " … "
    pieces: list[str] = []
    used = 0
    for begin, end in merged:
        overhead = len(separator) if pieces else 0
        room = config.body_text_chars - used - overhead
        if room <= 0:
            break
        piece = body_text[begin:end][:room]
        pieces.append(piece)
        used += len(piece) + overhead
    return separator.join(pieces)


def evidence_block(evidence: CandidateEvidence | None, config: CharacteristicsConfig) -> str:
    """The selected page, every page-derived field delimited. `None` when the
    row has no page: the record alone is what the model gets (`01` §6)."""
    if evidence is None:
        return "(no page was selected for this product; code from the product record alone)"
    product = evidence.jsonld_product or {}
    name = product.get("name") if isinstance(product.get("name"), str) else ""
    brand: Any = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    jsonld = "; ".join(
        part
        for part in (
            f"name={name.strip()}" if isinstance(name, str) and name.strip() else "",
            f"brand={brand.strip()}" if isinstance(brand, str) and brand.strip() else "",
        )
        if part
    )
    fields: list[tuple[str, str]] = [
        ("title", evidence.title or ""),
        ("gtin", evidence.gtin or ""),
        ("jsonld", jsonld),
        ("breadcrumbs", " > ".join(evidence.breadcrumbs)),
        ("price", evidence.price or ""),
        ("body_text", relevant_excerpt(evidence.body_text, config)),
    ]
    blocks = [delimit(text, candidate=1, field=field) for field, text in fields if text.strip()]
    header = f"url: {evidence.url}\nfetch_status: {evidence.fetch_status}"
    return header + ("\n" + "\n".join(blocks) if blocks else "\n(the page yielded no text)")


def characteristics_block(
    rules: list[CharacteristicRule],
    guidelines: dict[str, str],
    practice_defaults: dict[str, PracticeDefault] | None = None,
) -> str:
    """One section per applicable characteristic: kind, allowed values for a
    closed one, the guideline verbatim, and — where the labelled data's
    practice differs from the written default — the measured practice
    default with its evidence (`specs/characteristics.md` §2a)."""
    sections: list[str] = []
    for rule in rules:
        text = guidelines.get(f"{rule.module}\t{rule.characteristic}", "")
        lines = [f"### {rule.characteristic}", f"kind: {rule.open_close.upper()}"]
        if rule.open_close == "Close":
            lines.append("allowed values: " + " | ".join(rule.allowed_values))
        else:
            lines.append("example values: " + " | ".join(rule.allowed_values[:12]))
        lines.append("guideline: " + (text.strip() or "(no guideline text provided)"))
        default = (practice_defaults or {}).get(rule.characteristic)
        if default is not None:
            lines.append(
                f"practice default (measured on the labelled data; use it when the evidence "
                f"is silent, even where the guideline names another default): "
                f"{default.value} — {default.evidence}"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _as_text(value: str | int | float | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return f"{value:g}"
    return value


@dataclass(frozen=True)
class CharacteristicExtractor:
    llm: LlmClient
    prompt: PromptTemplate
    retry_prompt: PromptTemplate
    rules: list[CharacteristicRule]
    guidelines: dict[str, str]
    config: CharacteristicsConfig

    def extract(
        self, query: ProductQuery, module: str | None, evidence: CandidateEvidence | None
    ) -> CharacteristicValues:
        if module is None:
            return gate_only(query.row_uid, module, self.rules)
        applicable = applicable_rules(self.rules, module)
        if not applicable:
            return gate_only(query.row_uid, module, self.rules)

        user = render(
            self.prompt.user_template,
            query=query_block(query),
            module=module,
            evidence=evidence_block(evidence, self.config),
            characteristics=characteristics_block(
                applicable, self.guidelines, self.config.practice_defaults
            ),
            expected_keys=json.dumps([rule.characteristic for rule in applicable]),
        )
        answer = self._ask(user)
        outcome = self._validate(applicable, answer.values)

        retries = 0
        while any(v.rejected is not None for v in outcome.values()) and (
            retries < self.config.max_value_retries
        ):
            retries += 1
            rejections = "\n".join(
                f"- {name}: you said {v.rejected!r}; allowed values: "
                + " | ".join(next(r.allowed_values for r in applicable if r.characteristic == name))
                for name, v in outcome.items()
                if v.rejected is not None
            )
            retry_user = (
                user + "\n\n" + render(self.retry_prompt.user_template, rejections=rejections)
            )
            again = self._validate(applicable, self._ask(retry_user).values)
            # Keep what was accepted the first time; take the retry only for
            # what was rejected — a second answer that changes an accepted
            # value was not asked for.
            outcome = {
                name: (again[name] if outcome[name].rejected is not None else outcome[name])
                for name in outcome
            }

        values = empty_values()
        rejected: dict[str, str] = {}
        for name, v in outcome.items():
            values[name] = v.value
            if v.rejected is not None:
                rejected[name] = v.rejected
                log.warning(
                    "characteristic_rejected",
                    row_uid=query.row_uid,
                    characteristic=name,
                    said=v.rejected,
                )
        return CharacteristicValues(
            row_uid=query.row_uid,
            module=module,
            values=values,
            applicable=[rule.characteristic for rule in applicable],
            rejected=rejected,
            source="llm",
            prompt_hash=self.prompt.prompt_hash,
            model=self.llm.config.model,
        )

    def _ask(self, user: str) -> _Answer:
        return self.llm.complete_json(
            LlmCall(
                model=self.llm.config.model,
                system=self.prompt.system,
                user=user,
                temperature=self.llm.config.temperature,
                max_tokens=self.llm.config.max_output_tokens,
                prompt_hash=self.prompt.prompt_hash,
            ),
            _Answer,
        )

    @staticmethod
    def _validate(
        applicable: list[CharacteristicRule], said: dict[str, str | int | float | None]
    ) -> dict[str, Validation]:
        """The gate again, then the vocabulary. Keys the model added that are
        not applicable are ignored here — never validated, never written."""
        return {
            rule.characteristic: validate(rule, _as_text(said.get(rule.characteristic)))
            for rule in applicable
        }
