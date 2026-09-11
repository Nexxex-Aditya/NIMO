"""Per-row cards for the demo — `specs/demo.md`.

Pure over the runner's artifacts: nothing here decides anything, it only
reads the eight artifact trees and renders what each stage recorded. That
is the point of the demo — `03` §1's "when row 217 picks the wrong URL, we
need to see *which feature* misfired" — shown for ten rows.
"""

import html
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from nimo.contracts import (
    CandidateEvidence,
    CandidateURL,
    CharacteristicValues,
    ModulePrediction,
    ProductQuery,
    Reasoning,
    RegistryLookupResult,
    RowFailure,
    Selection,
)
from nimo.retrieval import brand_signal_rate
from nimo.run.artifacts import artifact_path, is_row_complete


@dataclass(frozen=True)
class RowCard:
    row_uid: str
    query: ProductQuery
    registry: RegistryLookupResult
    candidates: list[CandidateURL]
    evidence: list[CandidateEvidence]
    selection: Selection
    module: ModulePrediction
    characteristics: CharacteristicValues
    reasoning: Reasoning

    @property
    def tier(self) -> str:
        return self.registry.tier if self.registry.hit else self.selection.resolution_tier

    @property
    def brand_signal(self) -> float:
        return brand_signal_rate(self.candidates, self.query.brand)

    @property
    def selected_evidence(self) -> CandidateEvidence | None:
        return next((item for item in self.evidence if item.url == self.selection.url), None)


def load_card(root: Path, row_uid: str) -> RowCard | None:
    """The row's card, or `None` when the row is incomplete (failed/missing)."""
    if not is_row_complete(root, row_uid):
        return None

    def text(stage: str) -> str:
        return artifact_path(root, stage, row_uid).read_text(encoding="utf-8")

    return RowCard(
        row_uid=row_uid,
        query=ProductQuery.model_validate_json(text("normalize")),
        registry=RegistryLookupResult.model_validate_json(text("registry")),
        candidates=[CandidateURL.model_validate(item) for item in json.loads(text("retrieve"))],
        evidence=[CandidateEvidence.model_validate(item) for item in json.loads(text("fetch"))],
        selection=Selection.model_validate_json(text("match")),
        module=ModulePrediction.model_validate_json(text("classify")),
        characteristics=CharacteristicValues.model_validate_json(text("characteristics")),
        reasoning=Reasoning.model_validate_json(text("reason")),
    )


def load_failures(path: Path) -> dict[str, RowFailure]:
    if not path.exists():
        return {}
    failures: dict[str, RowFailure] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            failure = RowFailure.model_validate_json(line)
            failures[failure.row_uid] = failure
    return failures


def _host(url: str | None) -> str:
    if not url:
        return "-"
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def render_text(card: RowCard) -> str:
    """One row as terminal text. Every line names the stage it came from."""
    q = card.query
    lines = [
        f"=== {card.row_uid}  {q.brand} | {q.desc_raw}",
        f"  [normalize]  desc_clean={q.desc_clean!r}  "
        f"size={q.tokens.size_value}{q.tokens.size_unit or ''}  count={q.tokens.count}  "
        f"hints={q.tokens.format_hints}  barcode={q.barcode or 'none/corrupt'}",
        f"  [registry]   {card.tier}"
        + (f"  entity={card.registry.entity.entity_id}" if card.registry.entity else ""),
    ]
    if not card.registry.hit:
        by_strategy: dict[str, int] = {}
        for candidate in card.candidates:
            by_strategy[candidate.source_query] = by_strategy.get(candidate.source_query, 0) + 1
        lines.append(
            f"  [retrieve]   {len(card.candidates)} candidates  {by_strategy}  "
            f"brand signal {card.brand_signal:.0%}"
        )
        statuses: dict[str, int] = {}
        for item in card.evidence:
            statuses[item.fetch_status] = statuses.get(item.fetch_status, 0) + 1
        with_gtin = sum(1 for item in card.evidence if item.gtin)
        lines.append(
            f"  [fetch]      {len(card.evidence)} fetched  {statuses}  "
            f"pages with a GTIN: {with_gtin}"
        )
        s = card.selection
        features = s.features
        lines.append(
            f"  [match]      {_host(s.url)}  score {s.confidence:.2f}  gap {s.runner_up_gap:.2f}"
            + (
                f"  gtin_exact={features.barcode_exact} size={features.size_match} "
                f"count={features.count_match} flags={features.negative_flags} "
                f"calibrated={features.calibrated_prob:.2f}"
                if features is not None
                else ""
            )
            + ("  [Tier 3]" if s.adjudicated_by_llm else "")
        )
        if s.url:
            lines.append(f"               {s.url}")
    m = card.module
    lines.append(
        f"  [classify]   {m.module}  ({m.source}, conf {m.confidence:.2f}"
        + (f", nearest {m.nearest_example_row_uid}" if m.nearest_example_row_uid else "")
        + ")"
    )
    c = card.characteristics
    coded = [(k, v) for k, v in c.values.items() if v is not None]
    lines.append(
        f"  [characteristics]  {c.source}: {len(c.applicable)} applicable, {len(coded)} coded"
        + (f", {len(c.rejected)} refused" if c.rejected else "")
    )
    for name, value in coded:
        lines.append(f"               {name} = {value}")
    lines.append(f"  [reason]     {card.reasoning.text}")
    return "\n".join(lines)


def render_failure(failure: RowFailure) -> str:
    return (
        f"=== {failure.row_uid}  FAILED at {failure.stage}: {failure.error_type}: "
        f"{failure.message[:160]}"
    )


# --- HTML -----------------------------------------------------------------------


_STYLE = """
body{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#fafaf8;color:#1a1a1a}
h1{font-size:20px;margin:0 0 4px} .sub{color:#666;margin-bottom:20px}
.card{background:#fff;border:1px solid #e3e3df;border-radius:8px;padding:14px 16px;margin:12px 0}
.card h2{font-size:15px;margin:0 0 8px}
.stage{display:grid;grid-template-columns:130px 1fr;gap:4px 12px;font-size:13px}
.stage b{color:#555;font-weight:600}
.tier{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;background:#eef}
.tier.tier0_exact,.tier.tier1_ann{background:#e6f7e6}.tier.tier3_llm{background:#fff2cc}
.reason{margin-top:8px;padding:10px;background:#f6f6f2;border-radius:6px;font-size:13px}
.fail{background:#fff0f0;border-color:#f3c0c0}
table{border-collapse:collapse;font-size:13px}
td,th{border:1px solid #e3e3df;padding:3px 8px;text-align:left}
code{font-size:12px}
"""


def render_html(
    title: str, cards: list[RowCard], failures: list[RowFailure], summary_lines: list[str]
) -> str:
    def e(value: object) -> str:
        return html.escape(str(value))

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{e(title)}</title><style>{_STYLE}</style></head><body>",
        f"<h1>{e(title)}</h1><div class='sub'>NIMO — the Product Truth Agent. Every line below "
        "names the pipeline stage it came from; nothing here is generated after the fact.</div>",
        "<div class='card'><h2>Run summary</h2><pre>"
        + e("\n".join(summary_lines))
        + "</pre></div>",
    ]
    for card in cards:
        q, s, m, c = card.query, card.selection, card.module, card.characteristics
        rows = [
            (
                "normalize",
                f"{e(q.desc_clean)} · size {q.tokens.size_value}{q.tokens.size_unit or ''} · "
                f"count {q.tokens.count} · barcode {e(q.barcode or 'none/corrupt')}",
            ),
            ("registry", f"<span class='tier {e(card.tier)}'>{e(card.tier)}</span>"),
        ]
        if not card.registry.hit:
            rows.append(
                (
                    "retrieve",
                    f"{len(card.candidates)} candidates · brand signal {card.brand_signal:.0%}",
                )
            )
            with_gtin = sum(1 for item in card.evidence if item.gtin)
            rows.append(("fetch", f"{len(card.evidence)} fetched · {with_gtin} with a GTIN"))
            link = f"<a href='{e(s.url)}'>{e(_host(s.url))}</a>" if s.url else "abstained"
            features = s.features
            detail = (
                f" · score {s.confidence:.2f} · gap {s.runner_up_gap:.2f}"
                f" · gtin_exact {features.barcode_exact}"
                f" · size {e(features.size_match)} · calibrated {features.calibrated_prob:.2f}"
                if features is not None
                else ""
            )
            rows.append(("match", link + detail + (" · Tier 3" if s.adjudicated_by_llm else "")))
        rows.append(("classify", f"{e(m.module)} · {e(m.source)} · conf {m.confidence:.2f}"))
        coded = "".join(
            f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in c.values.items() if v is not None
        )
        rows.append(
            (
                "characteristics",
                f"{e(c.source)} · {len(c.applicable)} applicable"
                + (f"<table>{coded}</table>" if coded else " · no values in this run"),
            )
        )
        stage_html = "".join(f"<b>{e(k)}</b><div>{v}</div>" for k, v in rows)
        parts.append(
            f"<div class='card'><h2>{e(card.row_uid)} — {e(q.brand)} · {e(q.desc_raw)}</h2>"
            f"<div class='stage'>{stage_html}</div>"
            f"<div class='reason'>{e(card.reasoning.text)}</div></div>"
        )
    for failure in failures:
        parts.append(
            f"<div class='card fail'><h2>{e(failure.row_uid)} — failed at {e(failure.stage)}</h2>"
            f"<code>{e(failure.error_type)}: {e(failure.message[:300])}</code></div>"
        )
    parts.append("</body></html>")
    return "\n".join(parts)
