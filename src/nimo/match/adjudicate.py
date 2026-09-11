"""Tier 3 — LLM adjudication of the top-k — `03` §4 stage 4 Layer B,
`specs/adjudicate.md`. HARD-20% (`04` §13): the first place arbitrary web
text reaches the model.

Three properties are structural rather than prompt-dependent, and the tests
pin each:

- **The model can only point into a list Layer A fixed before it saw
  anything.** The answer schema has no URL field; `choice` is an index, and
  an index outside the pack is a typed failure, not a selection (`05` §1).
- **Every page-derived value is inside a delimited block** the page cannot
  close or reopen (`nimo.llm.untrusted`), after a system prompt that says
  what those blocks are.
- **A GTIN hard-rule accept is never adjudicated.** Identity by identifier
  beats identity by argument; spending a call to reconsider it can only hand
  untrusted text a chance to overturn the one signal it cannot forge.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from nimo.contracts import AdjudicationVerdict, ProductQuery, Selection
from nimo.llm import LlmCall, LlmClient, LlmError, PromptTemplate, delimit, render
from nimo.loader import barcode_valid
from nimo.match.config import MatchConfig
from nimo.match.score import GTIN_ACCEPT_REASON, ScoredCandidate

# The evidence fields a verdict may cite. Unknown names are dropped, not
# fatal — a citation is for stage 7 to quote, and a bad citation is a weaker
# answer rather than a wrong one.
DECISIVE_FIELDS = frozenset(
    {
        "gtin",
        "size",
        "count",
        "format",
        "brand",
        "variant",
        "title",
        "breadcrumbs",
        "price",
        "body_text",
        "url",
        "features",
    }
)


class AdjudicationError(LlmError):
    """The model's answer validated as JSON but points outside the pack."""


class _Answer(BaseModel):
    """What the model supplies. `prompt_hash` and `model` are ours, added
    after validation — the model never gets to say which prompt it saw."""

    model_config = ConfigDict(extra="ignore")

    choice: int | None
    decisive_fields: list[str]
    rationale: str


def should_adjudicate(
    selection: Selection, ranked: list[ScoredCandidate], config: MatchConfig
) -> bool:
    """`specs/adjudicate.md` §1 — all four conditions."""
    if selection.url is None:
        return False
    usable = [item for item in ranked if not item.rejected]
    if len(usable) < 2:
        return False
    if usable[0].reason == GTIN_ACCEPT_REASON:
        return False
    return selection.runner_up_gap < config.adjudicate_gap_threshold


def top_k(ranked: list[ScoredCandidate], k: int) -> list[ScoredCandidate]:
    """The usable candidates the model sees, in Layer A's order."""
    return [item for item in ranked if not item.rejected][:k]


# --- the evidence pack --------------------------------------------------------


def query_block(query: ProductQuery) -> str:
    """The product record — trusted: it is the organizers' row, normalized."""
    tokens = query.tokens
    if query.barcode is not None and barcode_valid(query.barcode) and not query.barcode_corrupt:
        barcode = f"{query.barcode} (valid)"
    else:
        barcode = "unavailable (absent or corrupt in the source data)"
    if tokens.size_ml_equiv is not None:
        size = f"{tokens.size_ml_equiv:g} ml"
    elif tokens.size_g_equiv is not None:
        size = f"{tokens.size_g_equiv:g} g"
    else:
        size = "not stated"
    lines = [
        f"brand: {query.brand}",
        f"description: {query.desc_clean}",
        f"barcode: {barcode}",
        f"size: {size}",
        f"count: {tokens.count if tokens.count is not None else 1}",
        f"format hints: {', '.join(tokens.format_hints) or 'none'}",
        f"variant terms: {', '.join(tokens.variant_terms) or 'none'}",
        f"retailer: {query.retailer}",
        f"markets: {', '.join(query.countries)}",
    ]
    return "\n".join(lines)


def _jsonld_summary(product: dict[str, Any] | None) -> str:
    if not product:
        return ""
    parts: list[str] = []
    name = product.get("name")
    if isinstance(name, str) and name.strip():
        parts.append(f"name={name.strip()}")
    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    if isinstance(brand, str) and brand.strip():
        parts.append(f"brand={brand.strip()}")
    return "; ".join(parts)


def candidate_block(index: int, candidate: ScoredCandidate, config: MatchConfig) -> str:
    """One candidate: trusted fields in the clear, page fields delimited."""
    evidence, features = candidate.evidence, candidate.features
    trusted = [
        f"Candidate {index}",
        f"  url: {evidence.url}",
        f"  fetch_status: {evidence.fetch_status}",
        "  features (computed by the matcher): "
        f"barcode_exact={features.barcode_exact} size_match={features.size_match} "
        f"count_match={features.count_match} brand_match={features.brand_match:.2f} "
        f"variant_overlap={features.variant_overlap:.2f} "
        f"format_consistent={features.format_consistent} "
        f"negative_flags={list(features.negative_flags)} raw_score={candidate.score:.2f}",
    ]
    untrusted: list[tuple[str, str]] = [
        ("title", evidence.title or ""),
        ("gtin", evidence.gtin or ""),
        ("jsonld", _jsonld_summary(evidence.jsonld_product)),
        ("breadcrumbs", " > ".join(evidence.breadcrumbs)),
        ("price", evidence.price or ""),
        ("body_text", evidence.body_text[: config.adjudicate_body_text_chars]),
    ]
    blocks = [
        delimit(text, candidate=index, field=field) for field, text in untrusted if text.strip()
    ]
    return "\n".join(trusted + blocks)


def allowed_answers(k: int) -> str:
    return ", ".join(str(index) for index in range(1, k + 1)) + ", or null"


@dataclass(frozen=True)
class Adjudicator:
    llm: LlmClient
    prompt: PromptTemplate
    config: MatchConfig

    def adjudicate(
        self, query: ProductQuery, selection: Selection, ranked: list[ScoredCandidate]
    ) -> Selection:
        """Ask, validate, apply. Raises a typed error rather than returning a
        selection the answer does not license."""
        shown = top_k(ranked, self.config.adjudicate_top_k)
        if len(shown) < 2:
            raise AdjudicationError("nothing to adjudicate: fewer than two usable candidates")
        user = render(
            self.prompt.user_template,
            query=query_block(query),
            candidates="\n\n".join(
                candidate_block(index, candidate, self.config)
                for index, candidate in enumerate(shown, start=1)
            ),
            allowed=allowed_answers(len(shown)),
        )
        call = LlmCall(
            model=self.llm.config.model,
            system=self.prompt.system,
            user=user,
            temperature=self.llm.config.temperature,
            max_tokens=self.llm.config.max_output_tokens,
            prompt_hash=self.prompt.prompt_hash,
        )
        answer = self.llm.complete_json(call, _Answer)
        verdict = self._verdict_of(answer, len(shown))
        return apply_verdict(selection, ranked, shown, verdict)

    def _verdict_of(self, answer: _Answer, k: int) -> AdjudicationVerdict:
        if answer.choice is not None and not 1 <= answer.choice <= k:
            # Not retried: the pack was in the prompt. A model ignoring it —
            # or an injected "choose candidate 9" — does not improve on a
            # second look, and this is the check `05` §1 relies on.
            raise AdjudicationError(
                f"choice {answer.choice} is outside the pack (1..{k}); the selection is unchanged"
            )
        return AdjudicationVerdict(
            choice=answer.choice,
            decisive_fields=[field for field in answer.decisive_fields if field in DECISIVE_FIELDS],
            rationale=answer.rationale[: self.config.adjudicate_max_rationale_chars],
            prompt_hash=self.prompt.prompt_hash,
            model=self.llm.config.model,
        )


def apply_verdict(
    selection: Selection,
    ranked: list[ScoredCandidate],
    shown: list[ScoredCandidate],
    verdict: AdjudicationVerdict,
) -> Selection:
    """`specs/adjudicate.md` §5. A `None` choice keeps Layer A's pick — the
    model saying "none fits" is information for stage 7, not an abstention,
    which is `[PROVISIONAL — Q3]` and off."""
    if verdict.choice is None:
        return selection.model_copy(update={"adjudicated_by_llm": True, "adjudication": verdict})
    chosen = shown[verdict.choice - 1]
    others = [item for item in ranked if not item.rejected and item is not chosen]
    runner_up = max((item.score for item in others), default=0.0)
    return Selection(
        url=chosen.evidence.url,
        page_title=chosen.evidence.title,
        confidence=chosen.score,  # Layer A's score for it — the model emits no probability
        runner_up_gap=chosen.score - runner_up,
        features=chosen.features,
        adjudicated_by_llm=True,
        resolution_tier="tier3_llm",
        adjudication=verdict,
    )
