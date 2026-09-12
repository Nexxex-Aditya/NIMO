"""The static results explorer — one self-contained HTML file over a run's
artifact tree (`specs/site.md`).

Evaluators cannot run the pipeline: the model endpoint is NIQ-internal and
the search layer is a container. What they can do is read what it produced —
every row, every stage's record, the registry, the numbers — in a page that
needs no server and no install. This module renders exactly the JSON card the
live UI renders (`nimo.ui.service.card_to_dict`) for every complete row, embeds
it, and lets the browser search and filter. Nothing here computes a new fact;
it is P15's principle (a renderer over the artifacts) at full scale.

The page carries NIQ's dataset rows. Where it is published is the owner's
decision, not this module's — it writes a file.
"""

import html
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nimo.contracts import CanonicalEntity, RawRow
from nimo.demo.cards import load_card, load_failures
from nimo.registry import read_entities
from nimo.run.artifacts import config_hash
from nimo.site.page import TEMPLATE
from nimo.ui.page import CARD_JS, STYLE
from nimo.ui.service import card_to_dict


@dataclass(frozen=True)
class SiteReport:
    path: Path
    rows_total: int
    rows_complete: int
    rows_failed: int
    entities: int
    bytes: int


def _summary(cards: list[dict[str, Any]], failures: int, total: int) -> dict[str, Any]:
    """Counts a reader can check against the cards themselves."""
    tiers = Counter(c["tier"] for c in cards)
    gtin_confirmed = sum(
        1
        for c in cards
        if c["tier"] in ("tier0_exact", "tier1_ann")
        or ((c["match"].get("features") or {}).get("barcode_exact") is True)
    )
    adjudicated = sum(1 for c in cards if c["match"].get("adjudicated_by_llm"))
    decided_by_model = sum(1 for c in cards if c["match"].get("resolution_tier") == "tier3_llm")
    sources = Counter(c["characteristics"]["source"] for c in cards)
    applicable = sum(len(c["characteristics"]["applicable"]) for c in cards)
    coded = sum(
        1
        for c in cards
        for name in c["characteristics"]["applicable"]
        if c["characteristics"]["values"].get(name) is not None
    )
    with_image = sum(1 for c in cards if c["characteristics"].get("image_sha256"))
    modules = Counter(c["classify"]["module"] for c in cards)
    return {
        "rows_total": total,
        "rows_complete": len(cards),
        "rows_failed": failures,
        "tiers": dict(sorted(tiers.items())),
        "gtin_confirmed": gtin_confirmed,
        "adjudicated": adjudicated,  # rows the model was asked about (Tier 3)
        "decided_by_model": decided_by_model,  # of those, rows where it pointed at a candidate
        "characteristics_sources": dict(sorted(sources.items())),
        "applicable_cells": applicable,
        "coded_cells": coded,
        "rows_with_image": with_image,
        "modules": len(modules),
        "top_modules": modules.most_common(8),
    }


def _entity_dict(entity: CanonicalEntity) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "brand": entity.brand,
        "barcode": entity.barcode,
        "module": entity.module,
        "resolved_url": entity.resolved_url,
        "page_title": entity.page_title,
        "characteristics": entity.characteristics,
        "members": entity.member_row_uids,
        "tier": entity.resolution_tier,
    }


def build_site(
    *,
    rows: list[RawRow],
    sheet: str,
    artifacts: Path,
    failures_path: Path,
    registry_path: Path,
    config_dir: Path,
    out: Path,
    title: str,
    notes: list[str],
) -> SiteReport:
    """Write the explorer for one sheet's run. `notes` are lines the page
    shows verbatim under the numbers — the run's caveats, stated by the
    person who made the run, never inferred here."""
    cards = [card for row in rows if (card := load_card(artifacts, row.row_uid)) is not None]
    complete = {card.row_uid for card in cards}
    # `failures.jsonl` is append-only across sheets and resumes: keep this
    # sheet's rows that are STILL incomplete — a row that failed once and
    # succeeded on a resume is a success, not a failure.
    failures = {
        uid: failure
        for uid, failure in load_failures(failures_path).items()
        if uid.startswith(f"{sheet}:") and uid not in complete
    }
    entities = read_entities(registry_path) if registry_path.exists() else []
    card_dicts = [card_to_dict(card) for card in cards]
    data = {
        "title": title,
        "sheet": sheet,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config_hash": config_hash(config_dir),
        "notes": notes,
        "summary": _summary(card_dicts, len(failures), len(rows)),
        "rows": card_dicts,
        "failures": [
            {
                "row_uid": f.row_uid,
                "stage": f.stage,
                "error_type": f.error_type,
                "message": f.message,
            }
            for f in failures.values()
        ],
        "registry": [_entity_dict(e) for e in entities],
    }
    # `</script>` inside a JSON string would end the data block early; JSON
    # allows `<\/`, and browsers read it back as `</`.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (
        TEMPLATE.replace("__TITLE__", html.escape(title))
        .replace("__STYLE__", STYLE)
        .replace("__CARD_JS__", CARD_JS)
        .replace("__DATA__", payload)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return SiteReport(
        path=out,
        rows_total=len(rows),
        rows_complete=len(cards),
        rows_failed=len(failures),
        entities=len(entities),
        bytes=out.stat().st_size,
    )
