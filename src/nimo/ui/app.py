"""The FastAPI app — `specs/ui.md`. Thin: every route is one service call.

Local, single-user, no auth (`04` non-goals: no service, no auth). Binds to
127.0.0.1 by default in `__main__`. Errors from the service are 4xx with the
message; anything else is a 500 the way FastAPI reports it — never masked.
"""

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from nimo.ui.page import PAGE
from nimo.ui.service import AdhocRecord, UiError, UiService


class LookupRequest(BaseModel):
    desc: str
    brand: str = ""
    barcode: str | None = None
    retailer: str | None = None
    country: str | None = None


class RunRequest(BaseModel):
    sheet: str
    row_uid: str
    force: bool = False


def create_app(service: UiService) -> FastAPI:
    app = FastAPI(title="NIMO — the Product Truth Agent", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return service.status()

    @app.get("/api/rows")
    def rows(sheet: str = "qa") -> list[dict[str, Any]]:
        try:
            return service.list_rows(sheet)
        except UiError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/rows/{sheet}/{row_uid}")
    def card(sheet: str, row_uid: str) -> JSONResponse:
        found = service.card(sheet, row_uid)
        if found is None:
            raise HTTPException(status_code=404, detail=f"{row_uid}: no artifacts yet — run it")
        return JSONResponse(found)

    @app.post("/api/run")
    def run(request: RunRequest) -> JSONResponse:
        try:
            return JSONResponse(
                service.run_row(request.sheet, request.row_uid, force=request.force)
            )
        except UiError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/lookup")
    def lookup(request: LookupRequest) -> JSONResponse:
        try:
            return JSONResponse(
                service.lookup(
                    AdhocRecord(
                        desc=request.desc,
                        brand=request.brand,
                        barcode=request.barcode,
                        retailer=request.retailer,
                        country=request.country,
                    )
                )
            )
        except UiError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/registry")
    def registry() -> dict[str, Any]:
        return service.registry()

    return app
