"""The reasoning composer — `03` §4 stage 7, `specs/reason.md`.

Every sentence is rendered from a named field and carries a provenance tag.
Nothing is inferred across fields, `body_text` is never quoted, and a
characteristic the gate excluded is never mentioned. That is what makes
`03`'s anti-hallucination rule a property of this module rather than a hope
about a prompt (`specs/reason.md` §0).
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from nimo.contracts import (
    CandidateEvidence,
    CharacteristicValues,
    ModulePrediction,
    ProductQuery,
    Reasoning,
    RegistryLookupResult,
    Selection,
)

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "reason.yaml"


class ReasonConfigError(Exception):
    """`config/reason.yaml` is missing, malformed, or missing a key."""


@dataclass(frozen=True)
class ReasonConfig:
    max_chars: int
    max_variant_terms_cited: int
    low_module_margin: float


@lru_cache(maxsize=1)
def load_reason_config(path: Path = CONFIG_PATH) -> ReasonConfig:
    if not path.exists():
        raise ReasonConfigError(f"{path} not found — `specs/reason.md` requires it")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ReasonConfigError(f"{path} did not parse to a mapping")
    max_chars = data.get("max_chars")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 100:
        raise ReasonConfigError(f"{path}: `max_chars` must be an integer >= 100.")
    cited = data.get("max_variant_terms_cited")
    if isinstance(cited, bool) or not isinstance(cited, int) or cited < 1:
        raise ReasonConfigError(f"{path}: `max_variant_terms_cited` must be a positive integer.")
    margin = data.get("low_module_margin")
    if isinstance(margin, bool) or not isinstance(margin, int | float) or not 0 <= margin <= 1:
        raise ReasonConfigError(f"{path}: `low_module_margin` must be in [0, 1].")
    return ReasonConfig(max_chars, cited, float(margin))


@dataclass(frozen=True)
class Sentence:
    text: str
    claims: tuple[str, ...]
    # Lower priority is dropped first when the text must be shortened.
    priority: int


def _host(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _size(query: ProductQuery) -> str | None:
    tokens = query.tokens
    if tokens.size_ml_equiv is not None:
        return f"{tokens.size_ml_equiv:g} ml"
    if tokens.size_g_equiv is not None:
        return f"{tokens.size_g_equiv:g} g"
    return None


def identity_sentence(
    query: ProductQuery,
    registry: RegistryLookupResult,
    selection: Selection,
    evidence: CandidateEvidence | None,
    config: ReasonConfig,
    *,
    re_examined: bool = False,
) -> Sentence:
    """How the URL was chosen — one of the six shapes in `specs/reason.md` §2.

    `re_examined`: a hit on an entity that had no stored values, in a run
    that extracts them — the entity's own page was fetched and read again.
    Saying "without re-examination" there would be the fabrication `03` §4
    stage 7 forbids, in the other direction."""
    if registry.hit:
        if registry.tier == "tier0_exact":
            how, claim = "exact barcode match", "registry.tier0_exact"
        else:
            similarity = f" (similarity {registry.similarity:.2f})" if registry.similarity else ""
            how, claim = f"near-duplicate identity match{similarity}", "registry.tier1_ann"
        if re_examined:
            return Sentence(
                f"Identity confirmed by {how} to a previously resolved item; that record had "
                f"no coded characteristics, so its page was read again to code them.",
                (claim, "registry.re_examined"),
                priority=100,
            )
        return Sentence(
            f"Identity confirmed by {how} to a previously resolved item; the page and its "
            f"characteristics are carried from that record without re-examination.",
            (claim,),
            priority=100,
        )

    if selection.url is None:
        return Sentence(
            "No candidate page met the evidence threshold; the module and characteristics are "
            "derived from the retailer description alone.",
            ("selection.abstained",),
            priority=100,
        )

    host = _host(selection.url)
    features = selection.features
    claims: list[str] = ["selection.url"]
    if features is not None and features.barcode_exact is True and evidence is not None:
        text = (
            f"The selected page ({host}) publishes EAN {evidence.gtin}, equal to the record's "
            f"barcode — a decisive identity match."
        )
        claims.append("selection.gtin_exact")
    else:
        parts: list[str] = []
        if features is not None:
            if features.brand_match > 0:
                parts.append(f"brand match {features.brand_match:.2f}")
                claims.append("selection.brand_match")
            if features.size_match in ("exact", "unit_converted"):
                size = _size(query)
                parts.append(f"size {features.size_match}" + (f" ({size})" if size else ""))
                claims.append("selection.size_match")
            if features.count_match == "exact" and query.tokens.count:
                parts.append(f"pack count {query.tokens.count}")
                claims.append("selection.count_match")
            if features.variant_overlap > 0:
                cited = ", ".join(query.tokens.variant_terms[: config.max_variant_terms_cited])
                parts.append(f"variant overlap {features.variant_overlap:.2f} ({cited})")
                claims.append("selection.variant_overlap")
            if features.format_consistent:
                parts.append("format consistent")
                claims.append("selection.format_consistent")
            if features.retailer_domain_match:
                parts.append("the record's own retailer domain")
                claims.append("selection.retailer_domain_match")
        basis = ", ".join(parts) if parts else f"a score of {selection.confidence:.2f}"
        text = f"The selected page ({host}) was ranked first on {basis}"
        if selection.runner_up_gap > 0:
            text += f", ahead of the runner-up by {selection.runner_up_gap:.2f}"
            claims.append("selection.runner_up_gap")
        if features is not None and features.calibrated_prob != features.raw_score:
            # Only when a fitted curve applied: without one the two are equal
            # by construction and "probability" would be an invented word.
            text += f" (calibrated probability {features.calibrated_prob:.2f})"
            claims.append("selection.calibrated_prob")
        text += "."
        if features is not None:
            demotions: list[str] = []
            if features.size_match == "mismatch":
                demotions.append("a size mismatch")
            if features.count_match == "mismatch":
                demotions.append("a pack-count mismatch")
            demotions.extend(f"the '{flag}' flag" for flag in features.negative_flags)
            if demotions:
                text += (
                    f" It was demoted for {', '.join(demotions)} and still won, so no better "
                    f"candidate was found."
                )
                claims.append("selection.demotions")

    verdict = selection.adjudication
    if selection.adjudicated_by_llm and verdict is not None:
        if verdict.choice is None:
            text += " An adjudication step found none of the alternatives a better fit."
        else:
            fields = ", ".join(verdict.decisive_fields) or "the evidence shown"
            text += f" An adjudication step chose it on {fields}: {verdict.rationale.strip()}"
            if not text.endswith("."):
                text += "."
        claims.append("selection.adjudication")
    return Sentence(text, tuple(claims), priority=100)


def module_sentence(prediction: ModulePrediction, config: ReasonConfig) -> Sentence:
    if prediction.source == "registry":
        return Sentence(
            f"Module {prediction.module} carried from the registry record.",
            ("module.registry",),
            priority=90,
        )
    text = f"Classified as {prediction.module} from the description"
    claims = ["module.module"]
    if prediction.nearest_example_row_uid is not None:
        text += (
            f", which most resembles {prediction.nearest_example_row_uid} "
            f"(similarity {prediction.nearest_example_similarity:.2f})"
        )
        claims.append("module.nearest_example")
    if prediction.runner_up is not None and prediction.runner_up_gap < config.low_module_margin:
        text += f" — a close call against {prediction.runner_up}"
        claims.append("module.runner_up")
    return Sentence(text + ".", tuple(claims), priority=90)


def characteristics_sentences(values: CharacteristicValues) -> list[Sentence]:
    """Coded values, then applicable-but-empty, then refused proposals. Non-
    applicable characteristics are never mentioned (`specs/reason.md` §2)."""
    sentences: list[Sentence] = []
    coded = [
        (name, values.values[name])
        for name in values.applicable
        if values.values.get(name) is not None
    ]
    if coded:
        sentences.append(
            Sentence(
                "Coded: " + "; ".join(f"{name} = {value}" for name, value in coded) + ".",
                tuple(f"characteristics.{name}" for name, _ in coded),
                priority=80,
            )
        )
    empty = [
        name
        for name in values.applicable
        if values.values.get(name) is None and name not in values.rejected
    ]
    if empty and values.source == "llm":
        sentences.append(
            Sentence(
                f"No evidence for {', '.join(empty)}; left empty.",
                ("characteristics.empty",),
                priority=60,
            )
        )
    if values.rejected:
        sentences.append(
            Sentence(
                "The model proposed "
                + "; ".join(f"{said} for {name}" for name, said in values.rejected.items())
                + ", outside the allowed values, and it was not written.",
                ("characteristics.rejected",),
                priority=70,
            )
        )
    if values.source == "gate_only" and values.applicable:
        sentences.append(
            Sentence(
                f"{len(values.applicable)} characteristic(s) apply to this module; values were "
                f"not extracted in this run.",
                ("characteristics.gate_only",),
                priority=80,
            )
        )
    return sentences


def evidence_sentence(evidence: CandidateEvidence | None) -> Sentence | None:
    if evidence is None:
        return None
    parts: list[str] = []
    if evidence.jsonld_product:
        parts.append("structured product data (JSON-LD)")
    if evidence.title:
        parts.append("the page title")
    if evidence.body_text:
        parts.append(f"{len(evidence.body_text)} characters of page text")
    if not parts:
        return Sentence(
            f"The selected page returned no usable text (fetch status: {evidence.fetch_status}).",
            ("evidence.fetch_status",),
            priority=50,
        )
    return Sentence(
        "Page evidence used: " + ", ".join(parts) + ".", ("evidence.fields",), priority=50
    )


def compose(
    query: ProductQuery,
    registry: RegistryLookupResult,
    selection: Selection,
    prediction: ModulePrediction,
    values: CharacteristicValues,
    evidence: list[CandidateEvidence],
    config: ReasonConfig,
) -> Reasoning:
    """The REASONING cell and its provenance. Deterministic (`04` §5)."""
    selected = next((item for item in evidence if item.url == selection.url), None)
    # The hit-then-extract path (`specs/characteristics.md` §5): values are
    # model-sourced on a hit only when the entity's page was read this run.
    re_examined = registry.hit and values.source == "llm"
    sentences: list[Sentence] = [
        identity_sentence(query, registry, selection, selected, config, re_examined=re_examined),
        module_sentence(prediction, config),
        *characteristics_sentences(values),
    ]
    page = evidence_sentence(selected if (not registry.hit or re_examined) else None)
    if page is not None:
        sentences.append(page)

    # Fit to `max_chars` by dropping whole sentences, lowest priority first,
    # never cutting mid-clause.
    kept = list(sentences)
    while kept and sum(len(s.text) + 1 for s in kept) - 1 > config.max_chars:
        lowest = min(range(len(kept)), key=lambda i: (kept[i].priority, -i))
        del kept[lowest]
    return Reasoning(
        row_uid=query.row_uid,
        text=" ".join(s.text for s in kept),
        claims=[claim for s in kept for claim in s.claims],
    )
