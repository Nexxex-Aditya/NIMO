"""The UI's service layer — `specs/ui.md`.

Everything the web app does goes through here, and everything here goes
through the same `Pipeline` the CLI runs. The UI adds exactly two things the
CLI does not have: running ONE row on demand (resumable — a complete row
costs nothing; `force` clears it first so the warm-start path can be shown)
and an ad-hoc product record typed by a person, which becomes a `RawRow`
under the `adhoc` sheet through the loader's own field parsers.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from nimo.contracts import RawRow, RowFailure
from nimo.demo.cards import RowCard, load_card, load_failures
from nimo.loader import load_rows
from nimo.loader.fields import parse_barcode, parse_brand, parse_countries, repair_encoding
from nimo.registry import read_entities
from nimo.retrieval import brand_signal_rate
from nimo.run.artifacts import clear_artifacts, is_row_complete
from nimo.run.compose import REGISTRY_DIR, RETAILERS, WORKBOOK, Pipeline

SHEETS = ("qa", "dev")
ADHOC = "adhoc"


class UiError(Exception):
    """A request the service cannot honour — surfaced as a 4xx by the app."""


@dataclass(frozen=True)
class AdhocRecord:
    """What a person types into the lookup form."""

    desc: str
    brand: str
    barcode: str | None
    retailer: str | None
    country: str | None


@dataclass
class UiService:
    pipeline: Pipeline
    rows: dict[str, list[RawRow]]
    retailer_names: dict[str, str]

    @classmethod
    def create(cls, pipeline: Pipeline) -> "UiService":
        raw = yaml.safe_load(RETAILERS.read_text(encoding="utf-8"))
        names = (
            {str(key): str(entry["name"]) for key, entry in raw.items() if isinstance(entry, dict)}
            if isinstance(raw, dict)
            else {}
        )
        return cls(
            pipeline=pipeline,
            rows={sheet: load_rows(WORKBOOK, sheet, RETAILERS) for sheet in SHEETS},
            retailer_names=names,
        )

    # --- listing --------------------------------------------------------------------

    def list_rows(self, sheet: str) -> list[dict[str, Any]]:
        if sheet not in self.rows:
            raise UiError(f"unknown sheet {sheet!r}; one of {SHEETS}")
        root = self.pipeline.paths_for(sheet).artifacts
        failures = load_failures(self.pipeline.paths_for(sheet).failures)
        listing: list[dict[str, Any]] = []
        for row in self.rows[sheet]:
            complete = is_row_complete(root, row.row_uid)
            entry: dict[str, Any] = {
                "row_uid": row.row_uid,
                "brand": row.brand,
                "desc": row.desc_raw,
                "barcode": row.barcode,
                "complete": complete,
                "failed_at": failures[row.row_uid].stage
                if not complete and row.row_uid in failures
                else None,
            }
            listing.append(entry)
        return listing

    # --- one row -----------------------------------------------------------------------

    def card(self, sheet: str, row_uid: str) -> dict[str, Any] | None:
        paths = self.pipeline.paths_for(sheet)
        card = load_card(paths.artifacts, row_uid)
        if card is None:
            failure = load_failures(paths.failures).get(row_uid)
            return _failure_dict(failure) if failure is not None else None
        return card_to_dict(card)

    def run_row(self, sheet: str, row_uid: str, *, force: bool) -> dict[str, Any]:
        """Run one row through the pipeline (resumable). `force` clears its
        artifacts first, which is how the registry warm-start is shown: the
        second run of a GTIN-confirmed row is a Tier 0 hit."""
        row = self._row(sheet, row_uid)
        paths = self.pipeline.paths_for(sheet)
        if force:
            clear_artifacts(paths.artifacts, row_uid)
        before = self.pipeline.registry_size
        summary = self.pipeline.run_rows([row], sheet, f"ui-{sheet}")
        card = self.card(sheet, row_uid)
        if card is None:
            raise UiError(f"{row_uid}: the run produced neither artifacts nor a failure record")
        card["run"] = {
            "succeeded": summary.rows_succeeded,
            "failed": summary.rows_failed,
            "wall_time_s": round(summary.wall_time_s, 2),
            "registry_before": before,
            "registry_after": self.pipeline.registry_size,
            "llm_calls": summary.llm_calls,
            "llm_tokens": summary.llm_tokens,
        }
        return card

    def lookup(self, record: AdhocRecord) -> dict[str, Any]:
        """A product typed by a person, run as a row of the `adhoc` sheet."""
        row = self.adhoc_row(record)
        self.rows.setdefault(ADHOC, [])
        if all(existing.row_uid != row.row_uid for existing in self.rows[ADHOC]):
            self.rows[ADHOC].append(row)
        return self.run_row(ADHOC, row.row_uid, force=True)

    def adhoc_row(self, record: AdhocRecord) -> RawRow:
        """Build a `RawRow` the way the loader would (`specs/loader.md`),
        keyed under `adhoc:<hash>` so it can never collide with a sheet row."""
        desc = " ".join(record.desc.split())
        if not desc:
            raise UiError("a product description is required")
        brand_raw = " ".join(record.brand.split()) or "UNKNOWN"
        barcode, barcode_raw, corrupt = parse_barcode(
            record.barcode.strip() if record.barcode and record.barcode.strip() else None
        )
        brand_fixed, brand_suspect = repair_encoding(brand_raw)
        desc_fixed, desc_suspect = repair_encoding(desc)
        brand, owner = parse_brand(brand_fixed)
        retailer_raw = (record.retailer or "").strip()
        retailer = self.retailer_names.get(retailer_raw, retailer_raw or "UNKNOWN")
        countries = parse_countries(record.country.strip() if record.country else "GB") or ["GB"]
        digest = hashlib.sha256(
            f"{desc_fixed}|{brand_fixed}|{barcode_raw}|{retailer_raw}".encode()
        ).hexdigest()
        return RawRow(
            row_uid=f"{ADHOC}:{int(digest[:8], 16)}",
            nan_key=0,
            item_code=0,
            barcode=barcode,
            barcode_raw=barcode_raw,
            barcode_corrupt=corrupt,
            brand_raw=brand_fixed,
            brand=brand,
            brand_owner=owner,
            brand_encoding_suspect=brand_suspect,
            retailer_raw=retailer_raw or "UNKNOWN",
            retailer=retailer,
            countries=countries,
            desc_raw=desc_fixed,
            desc_encoding_suspect=desc_suspect,
        )

    # --- registry ---------------------------------------------------------------------

    def registry(self) -> dict[str, Any]:
        entities = read_entities(REGISTRY_DIR / "entities.jsonl")
        recent = sorted(entities, key=lambda e: e.updated_at, reverse=True)[:12]
        return {
            "entities": len(entities),
            "with_module": sum(1 for e in entities if e.module),
            "with_characteristics": sum(1 for e in entities if e.characteristics),
            "recent": [
                {
                    "entity_id": e.entity_id,
                    "brand": e.brand,
                    "barcode": e.barcode,
                    "module": e.module,
                    "resolved_url": e.resolved_url,
                    "members": e.member_row_uids,
                    "tier": e.resolution_tier,
                }
                for e in recent
            ],
        }

    def status(self) -> dict[str, Any]:
        return {
            "live": self.pipeline.live,
            "adjudicate": self.pipeline.adjudicate,
            "characteristics": self.pipeline.characteristics,
            "curve": self.pipeline.curve is not None,
            "tau_abstain": self.pipeline.tau_abstain,
            "out_dir": str(self.pipeline.out_dir),
            "registry_entities": self.pipeline.registry_size,
            "llm_calls": self.pipeline.llm_counter.calls,
            "llm_tokens": self.pipeline.llm_counter.tokens,
        }

    def _row(self, sheet: str, row_uid: str) -> RawRow:
        for row in self.rows.get(sheet, []):
            if row.row_uid == row_uid:
                return row
        raise UiError(f"{row_uid} is not a row of {sheet!r}")


# --- serialisation -------------------------------------------------------------------------


def card_to_dict(card: RowCard) -> dict[str, Any]:
    """The card as JSON: the contracts' own dumps plus the derived facts the
    page shows (tier, brand signal, host). Nothing computed beyond that."""
    query = card.query
    selection = card.selection
    return {
        "row_uid": card.row_uid,
        "tier": card.tier,
        "query": {
            "brand": query.brand,
            "desc_raw": query.desc_raw,
            "desc_clean": query.desc_clean,
            "barcode": query.barcode,
            "barcode_corrupt": query.barcode_corrupt,
            "retailer": query.retailer,
            "countries": query.countries,
            "tokens": query.tokens.model_dump(),
        },
        "registry": card.registry.model_dump(mode="json"),
        "retrieve": {
            "candidates": [c.model_dump() for c in card.candidates],
            "brand_signal": round(brand_signal_rate(card.candidates, query.brand), 3),
        },
        "fetch": [
            {
                "url": e.url,
                "fetch_status": e.fetch_status,
                "title": e.title,
                "gtin": e.gtin,
                "has_jsonld": bool(e.jsonld_product),
                "body_chars": len(e.body_text),
            }
            for e in card.evidence
        ],
        "match": selection.model_dump(mode="json"),
        "classify": card.module.model_dump(),
        "characteristics": card.characteristics.model_dump(),
        "reason": card.reasoning.model_dump(),
    }


def _failure_dict(failure: RowFailure) -> dict[str, Any]:
    return {"row_uid": failure.row_uid, "failure": failure.model_dump(mode="json")}


def artifacts_root(pipeline: Pipeline, sheet: str) -> Path:
    return pipeline.paths_for(sheet).artifacts
