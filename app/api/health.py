"""Bereitschafts-Endpoint.

Ab M1, sobald das Bewegungsjournal existiert, prüft dieser Endpoint zusätzlich die Invariante
`SUM(movements.delta) == items.stock` (docs/PLAN.md L2). In M0 gibt es noch keine Tabellen dafür —
hier wird nur geprüft, dass die App läuft und die Datenbankverbindung erreichbar ist.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
def healthz(request: Request) -> dict[str, str]:
    request.app.state.db.execute("SELECT 1")
    return {"status": "ok"}
