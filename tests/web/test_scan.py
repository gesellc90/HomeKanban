from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect
from app.repo import items as items_repo
from app.repo import movements as movements_repo


def _current_stock(settings: Settings, item_id: int) -> int:
    connection = connect(settings.db_path)
    try:
        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        return item.stock
    finally:
        connection.close()


_IDEMPOTENCY_KEY_RE = re.compile(r'name="idempotency_key" value="([^"]+)"')


def _create_item(
    client: TestClient,
    *,
    name: str = "Testartikel",
    unit: str = "Packung",
    stock: int = 5,
    reorder_level: int = 2,
    target_stock: int = 5,
    pack_size: int = 1,
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
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[-1])


def _token_for(client: TestClient, item_id: int) -> str:
    detail = client.get(f"/artikel/{item_id}")
    match = re.search(r"/e/([A-Za-z0-9_-]+)", detail.text)
    assert match is not None, detail.text
    return match.group(1)


def _quick_idempotency_key(scan_page_html: str) -> str:
    match = _IDEMPOTENCY_KEY_RE.search(scan_page_html)
    assert match is not None, scan_page_html
    return match.group(1)


def _shift_movement_created_at(settings: Settings, movement_id: int, *, minutes: int) -> None:
    """Verschiebt `created_at` einer Bewegung in die Vergangenheit, ohne echte Zeit verstreichen
    zu lassen — über eine zweite Verbindung auf dieselbe (dateibasierte) Test-Datenbank."""
    connection = connect(settings.db_path)
    try:
        movement = movements_repo.get_by_id(connection, movement_id)
        assert movement is not None
        original = datetime.fromisoformat(movement.created_at.replace("Z", "+00:00"))
        shifted = original - timedelta(minutes=minutes)
        stamp = shifted.strftime("%Y-%m-%dT%H:%M:%S.") + f"{shifted.microsecond // 1000:03d}Z"
        connection.execute("UPDATE movements SET created_at = ? WHERE id = ?", (stamp, movement_id))
    finally:
        connection.close()


class TestScanPage:
    def test_unknown_token_returns_friendly_404(self, client: TestClient) -> None:
        response = client.get("/e/unbekanntes-token")

        assert response.status_code == 404
        assert "Unbekannter Code" in response.text

    def test_archived_item_returns_friendly_410_and_does_not_offer_booking(
        self, client: TestClient
    ) -> None:
        item_id = _create_item(client, name="Kaffee")
        token = _token_for(client, item_id)
        client.post(f"/artikel/{item_id}/archivieren", follow_redirects=False)

        response = client.get(f"/e/{token}")

        assert response.status_code == 410
        assert "archiviert" in response.text
        assert "entnommen" not in response.text

    def test_get_sets_no_store_and_does_not_change_stock(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3)
        token = _token_for(client, item_id)

        response = client.get(f"/e/{token}")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "3 Packung" in client.get(f"/artikel/{item_id}").text

    def test_shows_name_stock_and_primary_button(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3)
        token = _token_for(client, item_id)

        response = client.get(f"/e/{token}")

        assert "Kaffee" in response.text
        assert "3 Packung" in response.text
        assert "−1 entnommen" in response.text
        assert "Bestand korrigieren" in response.text


class TestTokenUnguessability:
    def test_tokens_have_the_expected_length_and_are_not_sequential(
        self, client: TestClient
    ) -> None:
        first_id = _create_item(client, name="Artikel A")
        second_id = _create_item(client, name="Artikel B")

        first_token = _token_for(client, first_id)
        second_token = _token_for(client, second_id)

        assert len(first_token) == 22  # secrets.token_urlsafe(16), keine Auffüllung
        assert len(second_token) == 22
        assert first_token != second_token
        # Kein gemeinsames Präfix und keine erkennbare Nähe zueinander wie bei einer laufenden
        # Nummer — das Token darf aus der Artikel-ID nicht ableitbar sein.
        assert first_token[:4] != second_token[:4]


class TestBookWithdrawal:
    def test_single_tap_books_minus_one_and_redirects_to_result(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)
        token = _token_for(client, item_id)
        scan_page = client.get(f"/e/{token}")
        key = _quick_idempotency_key(scan_page.text)

        response = client.post(
            f"/e/{token}/entnahme",
            data={"quantity": "1", "idempotency_key": key},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/e/{token}/ok/2"  # 1 = opening, 2 = withdrawal
        assert "2 Packung" in client.get(f"/artikel/{item_id}").text

    def test_double_submit_with_same_key_books_exactly_once(
        self, client: TestClient, settings: Settings
    ) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)
        token = _token_for(client, item_id)
        scan_page = client.get(f"/e/{token}")
        key = _quick_idempotency_key(scan_page.text)

        first = client.post(
            f"/e/{token}/entnahme",
            data={"quantity": "1", "idempotency_key": key},
            follow_redirects=False,
        )
        second = client.post(
            f"/e/{token}/entnahme",
            data={"quantity": "1", "idempotency_key": key},
            follow_redirects=False,
        )

        assert first.status_code == 303
        assert second.status_code == 303
        assert first.headers["location"] == second.headers["location"]

        detail = client.get(f"/artikel/{item_id}")
        assert "2 Packung" in detail.text  # nicht 1 Packung — nur eine Entnahme gebucht

        connection = connect(settings.db_path)
        try:
            movements = movements_repo.list_for_item(connection, item_id)
        finally:
            connection.close()
        assert [m.kind for m in movements].count("withdrawal") == 1

    def test_withdrawal_exceeding_stock_is_rejected_with_german_message_and_non_500(
        self, client: TestClient
    ) -> None:
        item_id = _create_item(client, name="Kaffee", stock=1, reorder_level=1, target_stock=5)
        token = _token_for(client, item_id)
        scan_page = client.get(f"/e/{token}")
        key = _quick_idempotency_key(scan_page.text)

        response = client.post(
            f"/e/{token}/entnahme",
            data={"quantity": "5", "idempotency_key": key},
        )

        assert response.status_code == 422
        assert "übersteigt den Bestand" in response.text
        assert "1 Packung" in client.get(f"/artikel/{item_id}").text  # unverändert

    def test_unknown_token_returns_friendly_404(self, client: TestClient) -> None:
        response = client.post(
            "/e/unbekanntes-token/entnahme", data={"quantity": "1", "idempotency_key": "x"}
        )

        assert response.status_code == 404
        assert "Unbekannter Code" in response.text

    def test_archived_item_returns_friendly_410_and_does_not_book(
        self, client: TestClient, settings: Settings
    ) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3)
        token = _token_for(client, item_id)
        client.post(f"/artikel/{item_id}/archivieren", follow_redirects=False)

        response = client.post(
            f"/e/{token}/entnahme", data={"quantity": "1", "idempotency_key": "x"}
        )

        assert response.status_code == 410
        assert _current_stock(settings, item_id) == 3  # unverändert


class TestConcurrentDoubleTap:
    def test_two_concurrent_posts_with_the_same_key_book_once(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Der Fall, den ein reines Vorab-SELECT durchrutschen lässt (docs/PLAN.md §5/§11,4)."""
        item_id = _create_item(client, name="Kaffee", stock=5, reorder_level=1, target_stock=10)
        token = _token_for(client, item_id)
        scan_page = client.get(f"/e/{token}")
        key = _quick_idempotency_key(scan_page.text)

        responses: list[object] = []
        barrier = threading.Barrier(2)

        def submit() -> None:
            barrier.wait(timeout=5)
            responses.append(
                client.post(
                    f"/e/{token}/entnahme",
                    data={"quantity": "1", "idempotency_key": key},
                    follow_redirects=False,
                )
            )

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert all(r.status_code == 303 for r in responses)  # type: ignore[attr-defined]
        locations = {r.headers["location"] for r in responses}  # type: ignore[attr-defined]
        assert len(locations) == 1  # dieselbe Bewegung für beide Anfragen

        detail = client.get(f"/artikel/{item_id}")
        assert "4 Packung" in detail.text  # genau eine Entnahme, nicht zwei

        connection = connect(settings.db_path)
        try:
            movements = movements_repo.list_for_item(connection, item_id)
        finally:
            connection.close()
        assert [m.kind for m in movements].count("withdrawal") == 1


class TestScanResult:
    def _book_withdrawal(self, client: TestClient, token: str, *, quantity: int = 1) -> str:
        scan_page = client.get(f"/e/{token}")
        key = _quick_idempotency_key(scan_page.text)
        response = client.post(
            f"/e/{token}/entnahme",
            data={"quantity": str(quantity), "idempotency_key": key},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        assert isinstance(location, str)
        return location

    def test_shows_booking_and_offers_undo(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)
        token = _token_for(client, item_id)
        location = self._book_withdrawal(client, token)

        response = client.get(location)

        assert response.status_code == 200
        assert "Kaffee" in response.text
        assert "2 Packung" in response.text
        assert "Rückgängig" in response.text

    def test_movement_from_a_different_item_is_rejected(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee")
        other_id = _create_item(client, name="Tee")
        token = _token_for(client, item_id)
        other_token = _token_for(client, other_id)
        location = self._book_withdrawal(client, token)
        movement_id = location.rsplit("/", 1)[-1]

        response = client.get(f"/e/{other_token}/ok/{movement_id}")

        assert response.status_code == 404

    def test_unknown_movement_returns_friendly_404(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee")
        token = _token_for(client, item_id)

        response = client.get(f"/e/{token}/ok/999999")

        assert response.status_code == 404


class TestUndo:
    def _book_withdrawal(self, client: TestClient, token: str) -> tuple[str, int]:
        scan_page = client.get(f"/e/{token}")
        key = _quick_idempotency_key(scan_page.text)
        response = client.post(
            f"/e/{token}/entnahme",
            data={"quantity": "1", "idempotency_key": key},
            follow_redirects=False,
        )
        location = response.headers["location"]
        assert isinstance(location, str)
        return location, int(location.rsplit("/", 1)[-1])

    def test_undo_within_window_restores_stock_and_redirects_to_scan_page(
        self, client: TestClient
    ) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)
        token = _token_for(client, item_id)
        _location, movement_id = self._book_withdrawal(client, token)

        response = client.post(f"/bewegungen/{movement_id}/rueckgaengig", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == f"/e/{token}"
        assert "3 Packung" in client.get(f"/artikel/{item_id}").text

    def test_undo_after_window_expired_is_rejected_with_german_message(
        self, client: TestClient, settings: Settings
    ) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)
        token = _token_for(client, item_id)
        location, movement_id = self._book_withdrawal(client, token)
        _shift_movement_created_at(settings, movement_id, minutes=settings.undo_window_minutes + 1)

        response = client.post(f"/bewegungen/{movement_id}/rueckgaengig")

        assert response.status_code == 409
        assert "Zeitfenster" in response.text
        assert "Bestand korrigieren" in response.text  # der Korrekturweg wird genannt
        assert "2 Packung" in client.get(f"/artikel/{item_id}").text  # unverändert
        assert "2 Packung" in client.get(location).text  # Ergebnisseite bleibt erreichbar

    def test_double_undo_is_rejected_with_german_message(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)
        token = _token_for(client, item_id)
        _location, movement_id = self._book_withdrawal(client, token)
        client.post(f"/bewegungen/{movement_id}/rueckgaengig", follow_redirects=False)

        response = client.post(f"/bewegungen/{movement_id}/rueckgaengig")

        assert response.status_code == 409
        assert "bereits rückgängig" in response.text
        assert "3 Packung" in client.get(f"/artikel/{item_id}").text  # unverändert seit dem Undo

    def test_undo_unknown_movement_returns_friendly_404(self, client: TestClient) -> None:
        response = client.post("/bewegungen/999999/rueckgaengig")

        assert response.status_code == 404
        assert "Buchung nicht gefunden" in response.text


class TestLedgerInvariantAcrossScanFlow:
    def test_holds_over_withdrawals_double_submits_and_undo(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=10, reorder_level=1, target_stock=20)
        token = _token_for(client, item_id)

        # Normale Entnahme.
        scan_page = client.get(f"/e/{token}")
        key_a = _quick_idempotency_key(scan_page.text)
        client.post(
            f"/e/{token}/entnahme",
            data={"quantity": "2", "idempotency_key": key_a},
            follow_redirects=False,
        )

        # Doppeltes Absenden desselben Formulars.
        scan_page = client.get(f"/e/{token}")
        key_b = _quick_idempotency_key(scan_page.text)
        client.post(
            f"/e/{token}/entnahme",
            data={"quantity": "1", "idempotency_key": key_b},
            follow_redirects=False,
        )
        second = client.post(
            f"/e/{token}/entnahme",
            data={"quantity": "1", "idempotency_key": key_b},
            follow_redirects=False,
        )
        movement_id = int(second.headers["location"].rsplit("/", 1)[-1])

        # Rückgängig.
        client.post(f"/bewegungen/{movement_id}/rueckgaengig", follow_redirects=False)

        detail = client.get(f"/artikel/{item_id}")
        assert "8 Packung" in detail.text  # 10 - 2 - 1 (dedupliziert) + 1 (rückgängig)

        healthz = client.get("/healthz")
        assert healthz.status_code == 200
