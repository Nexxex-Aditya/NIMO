"""P16 UI tests — `specs/ui.md`. The app over an OFFLINE pipeline: zero
network, and every route is exercised through FastAPI's test client."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nimo.run.compose import Pipeline
from nimo.ui import AdhocRecord, UiService, create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    pipeline = Pipeline.create(live=False, out_dir=tmp_path_factory.mktemp("ui"))
    return TestClient(create_app(UiService.create(pipeline)))


def test_the_page_is_self_contained(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200 and "<!doctype html>" in page.text
    assert "http://" not in page.text.split("<script>")[0]  # no external assets
    assert "/api/run" in page.text and "/api/lookup" in page.text


def test_status_reports_the_mode(client: TestClient) -> None:
    status = client.get("/api/status").json()
    assert status["live"] is False and status["characteristics"] is False
    assert isinstance(status["registry_entities"], int)


def test_rows_lists_the_sheet_and_rejects_an_unknown_one(client: TestClient) -> None:
    rows = client.get("/api/rows?sheet=qa").json()
    assert len(rows) == 412 and rows[0]["row_uid"] == "qa:0" and rows[0]["complete"] is False
    assert client.get("/api/rows?sheet=nope").status_code == 404


def test_an_unrun_row_has_no_card_until_it_is_run(client: TestClient) -> None:
    assert client.get("/api/rows/dev/dev:0").status_code == 404
    card = client.post("/api/run", json={"sheet": "dev", "row_uid": "dev:0"}).json()
    assert card["row_uid"] == "dev:0" and card["tier"] == "tier2_retrieval"
    assert card["classify"]["module"] and card["reason"]["text"]
    assert card["characteristics"]["source"] == "gate_only"
    assert card["run"]["succeeded"] == 1 and card["run"]["failed"] == 0
    assert client.get("/api/rows/dev/dev:0").status_code == 200
    assert client.get("/api/rows?sheet=dev").json()[0]["complete"] is True


def test_force_reruns_a_complete_row(client: TestClient) -> None:
    first = client.post("/api/run", json={"sheet": "dev", "row_uid": "dev:1"}).json()
    again = client.post("/api/run", json={"sheet": "dev", "row_uid": "dev:1", "force": True}).json()
    assert again["reason"]["text"] == first["reason"]["text"]  # deterministic (`04` §5)
    assert again["run"]["succeeded"] == 1


def test_an_unknown_row_is_a_400(client: TestClient) -> None:
    response = client.post("/api/run", json={"sheet": "dev", "row_uid": "dev:9999"})
    assert response.status_code == 400 and "not a row" in response.json()["detail"]


def test_lookup_runs_an_adhoc_record_through_the_same_pipeline(client: TestClient) -> None:
    card = client.post(
        "/api/lookup",
        json={
            "desc": "aquafresh whitening pump 100ml",
            "brand": "AQUAFRESH (HALEON)",
            "barcode": "5014697056627",
        },
    ).json()
    assert card["row_uid"].startswith("adhoc:")
    assert card["query"]["brand"] == "AQUAFRESH" and card["query"]["barcode"] == "5014697056627"
    assert card["query"]["tokens"]["size_ml_equiv"] == 100.0
    assert card["classify"]["module"]
    # the same record is the same row: deterministic id, re-run in place
    again = client.post(
        "/api/lookup",
        json={
            "desc": "aquafresh whitening pump 100ml",
            "brand": "AQUAFRESH (HALEON)",
            "barcode": "5014697056627",
        },
    ).json()
    assert again["row_uid"] == card["row_uid"]


def test_lookup_without_a_description_is_refused(client: TestClient) -> None:
    assert client.post("/api/lookup", json={"desc": "   ", "brand": "X"}).status_code == 400


def test_adhoc_row_uses_the_loaders_field_rules() -> None:
    """A rounded barcode is nulled and flagged, a known retailer maps to its
    name, an unknown one passes through — the loader's rules, not new ones."""
    pipeline = Pipeline.create(live=False, out_dir=Path("unused"))
    service = UiService.create(pipeline)
    row = service.adhoc_row(
        AdhocRecord(
            desc="x paste",
            brand="COLGATE (CP)",
            barcode="5000000000000",
            retailer="P00R4 (GB) BOOTS",
            country="GB",
        )
    )
    assert row.barcode is None and row.barcode_corrupt and row.barcode_raw == "5000000000000"
    assert row.brand == "COLGATE" and row.brand_owner == "CP" and row.retailer == "BOOTS"
    other = service.adhoc_row(
        AdhocRecord(desc="x", brand="", barcode=None, retailer="MY SHOP", country=None)
    )
    assert other.retailer == "MY SHOP" and other.countries == ["GB"] and other.brand == "UNKNOWN"


def test_registry_endpoint_summarises(client: TestClient) -> None:
    summary = client.get("/api/registry").json()
    assert {"entities", "with_module", "with_characteristics", "recent"} <= set(summary)
