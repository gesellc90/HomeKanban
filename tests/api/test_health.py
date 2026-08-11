from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_healthz_returns_200(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_reports_ledger_invariant_violation(settings: Settings) -> None:
    app: FastAPI = create_app(settings)
    with TestClient(app) as test_client:
        # Direkter Schreibzugriff an den Services vorbei: ein Artikel ohne passende
        # opening-Bewegung verletzt SUM(movements.delta) == items.stock.
        app.state.db.execute(
            """
            INSERT INTO items (
                name, unit, stock, reorder_level, target_stock, pack_size,
                qr_token, position, created_at, updated_at
            ) VALUES ('Kaffee', 'Packung', 5, 1, 10, 1, 'tok1', 0,
                      '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z')
            """
        )

        response = test_client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["item_ids"]
