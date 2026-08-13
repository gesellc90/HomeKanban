"""Bereitschafts-Endpoint.

Prüft zusätzlich die Invariante `SUM(movements.delta) == items.stock` (docs/PLAN.md L2,
ADR 0002) je Artikel. Ein Verstoß liefert `503` statt eines stillen `200` — genau die
Fehlerklasse, die diese Invariante eigentlich ausschließt, soll sichtbar bleiben.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.deps import DbConnection
from app.repo.movements import find_ledger_invariant_violations

router = APIRouter()


@router.get("/healthz")
def healthz(connection: DbConnection) -> JSONResponse:
    connection.execute("SELECT 1")

    violating_item_ids = find_ledger_invariant_violations(connection)
    if violating_item_ids:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "detail": "Invariante SUM(movements.delta) == items.stock verletzt",
                "item_ids": violating_item_ids,
            },
        )

    return JSONResponse(status_code=200, content={"status": "ok"})
