from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.db import connect
from app.repo import items as items_repo
from app.services import stock as stock_service


def _create_item(
    client: TestClient,
    *,
    name: str = "Testartikel",
    unit: str = "Packung",
    stock: int = 10,
    reorder_level: int = 1,
    target_stock: int = 20,
    pack_size: int = 1,
    lead_days: int = 7,
) -> int:
    response = client.post(
        "/artikel",
        data={
            "name": name,
            "unit": unit,
            "stock": str(stock),
            "reorder_level": str(reorder_level),
            "target_stock": str(target_stock),
            "pack_size": str(pack_size),
            "lead_days": str(lead_days),
            "note": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[-1])


def _days_ago(days: int) -> str:
    return stock_service.format_utc_iso(datetime.now(UTC) - timedelta(days=days))


def _book_rich_history(client: TestClient, item_id: int, *, quantity: int = 1) -> None:
    """4 Entnahmen über 45 Tage — genug für eine Prognose (§9: >=3 Entnahmen, >=14 Tage)."""
    connection = connect(client.app.state.settings.db_path)  # type: ignore[attr-defined]
    try:
        for days in (45, 30, 15, 0):
            stock_service.withdraw(
                connection, item_id=item_id, quantity=quantity, source="qr", now=_days_ago(days)
            )
    finally:
        connection.close()


class TestHouseholdOverview:
    def test_empty_household_renders_without_crashing(self, client: TestClient) -> None:
        response = client.get("/verlauf")

        assert response.status_code == 200

    def test_archived_items_are_not_listed(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee")
        client.post(f"/artikel/{item_id}/archivieren", follow_redirects=False)

        response = client.get("/verlauf")

        assert "Kaffee" not in response.text

    def test_splits_items_into_forecast_and_too_little_data_sections(
        self, client: TestClient
    ) -> None:
        with_history_id = _create_item(client, name="Kaffee", stock=10)
        _book_rich_history(client, with_history_id)
        _create_item(client, name="Zahnpasta")

        response = client.get("/verlauf")

        assert response.status_code == 200
        assert "Kaffee" in response.text
        assert "Zahnpasta" in response.text
        assert "Zu wenig Daten" in response.text
        # Der Artikel ohne Historie steht im "Zu wenig Daten"-Abschnitt, nicht in der
        # sortierten Reichweiten-Liste davor.
        assert response.text.index("Kaffee") < response.text.index("Zu wenig Daten")
        assert response.text.index("Zu wenig Daten") < response.text.index("Zahnpasta")


class TestItemHistoryPage:
    def test_unknown_item_returns_404(self, client: TestClient) -> None:
        response = client.get("/artikel/999999/verlauf")

        assert response.status_code == 404

    def test_shows_full_journal_and_forecast_for_item_with_enough_data(
        self, client: TestClient
    ) -> None:
        item_id = _create_item(client, name="Kaffee", stock=10, reorder_level=0)
        _book_rich_history(client, item_id)

        response = client.get(f"/artikel/{item_id}/verlauf")

        assert response.status_code == 200
        assert "Reichweite" in response.text
        assert "Verbrauchsrate" in response.text
        # 1 opening + 4 Entnahmen = 5 Journal-Einträge.
        assert response.text.count("movement-list__item") >= 5

    def test_shows_too_little_data_message_for_a_fresh_item(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Zahnpasta")

        response = client.get(f"/artikel/{item_id}/verlauf")

        assert response.status_code == 200
        assert "Zu wenig Daten" in response.text

    def test_archived_item_hides_forecast_but_keeps_the_journal(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=10)
        _book_rich_history(client, item_id)
        client.post(f"/artikel/{item_id}/archivieren", follow_redirects=False)

        response = client.get(f"/artikel/{item_id}/verlauf")

        assert response.status_code == 200
        assert "Archiviert" in response.text
        assert "<h2>Verbrauchsprognose</h2>" not in response.text
        assert "/verlauf/uebernehmen" not in response.text
        assert response.text.count("movement-list__item") >= 5


class TestTakeOverSuggestion:
    def test_writes_the_suggestion_and_redirects(self, client: TestClient) -> None:
        # reorder_level=0 bewusst weit unter dem zu erwartenden Vorschlag, damit die Übernahme
        # sichtbar etwas ändert.
        item_id = _create_item(
            client, name="Kaffee", stock=10, reorder_level=0, target_stock=20, lead_days=7
        )
        _book_rich_history(client, item_id)

        response = client.post(f"/artikel/{item_id}/verlauf/uebernehmen", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == f"/artikel/{item_id}/verlauf"
        connection = connect(client.app.state.settings.db_path)  # type: ignore[attr-defined]
        try:
            item = items_repo.get_by_id(connection, item_id)
        finally:
            connection.close()
        assert item is not None
        assert item.reorder_level > 0

    def test_without_enough_data_returns_409(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Zahnpasta")

        response = client.post(f"/artikel/{item_id}/verlauf/uebernehmen", follow_redirects=False)

        assert response.status_code == 409
        assert "zu wenig daten" in response.text.lower()

    def test_suggestion_conflicting_with_target_stock_returns_422(self, client: TestClient) -> None:
        # Hohe Verbrauchsmengen bei niedrigem Sollbestand: Der rechnerisch korrekte Vorschlag
        # verletzt `target_stock > reorder_level` (§3) und muss verständlich abgelehnt werden.
        # Rate = (40 - 10) / 14 = 30/14; Vorschlag = ceil(30/14 * 7) = 15 >= target_stock (3).
        item_id = _create_item(
            client, name="Kaffee", stock=50, reorder_level=1, target_stock=3, lead_days=7
        )
        connection = connect(client.app.state.settings.db_path)  # type: ignore[attr-defined]
        try:
            for days, quantity in ((14, 10), (9, 10), (4, 10), (0, 10)):
                stock_service.withdraw(
                    connection, item_id=item_id, quantity=quantity, source="qr", now=_days_ago(days)
                )

            response = client.post(
                f"/artikel/{item_id}/verlauf/uebernehmen", follow_redirects=False
            )

            assert response.status_code == 422
            item = items_repo.get_by_id(connection, item_id)
            assert item is not None
            assert item.reorder_level == 1  # unverändert — nichts wurde geschrieben
        finally:
            connection.close()

    def test_archived_item_returns_409(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=10)
        _book_rich_history(client, item_id)
        client.post(f"/artikel/{item_id}/archivieren", follow_redirects=False)

        response = client.post(f"/artikel/{item_id}/verlauf/uebernehmen", follow_redirects=False)

        assert response.status_code == 409

    def test_unknown_item_returns_404(self, client: TestClient) -> None:
        response = client.post("/artikel/999999/verlauf/uebernehmen", follow_redirects=False)

        assert response.status_code == 404
