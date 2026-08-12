from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("path", ["/kategorien", "/laeden"])
class TestListPage:
    def test_returns_200_when_empty(self, client: TestClient, path: str) -> None:
        response = client.get(path)

        assert response.status_code == 200
        assert "Noch keine" in response.text


@pytest.mark.parametrize("path", ["/kategorien", "/laeden"])
class TestCreate:
    def test_creates_and_redirects(self, client: TestClient, path: str) -> None:
        response = client.post(path, data={"name": "Drogerie"}, follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == path

        listing = client.get(path)
        assert "Drogerie" in listing.text

    def test_empty_name_is_rejected_with_german_message_and_non_500(
        self, client: TestClient, path: str
    ) -> None:
        response = client.post(path, data={"name": "   "})

        assert response.status_code == 422
        assert "Name darf nicht leer sein." in response.text

    def test_duplicate_name_is_rejected_with_german_message_and_non_500(
        self, client: TestClient, path: str
    ) -> None:
        client.post(path, data={"name": "REWE"})

        response = client.post(path, data={"name": "REWE"})

        assert response.status_code == 422
        assert "bereits" in response.text


@pytest.mark.parametrize("path", ["/kategorien", "/laeden"])
class TestRename:
    def test_renames_and_redirects(self, client: TestClient, path: str) -> None:
        client.post(path, data={"name": "Alt"})
        entry_id = _entry_id_by_name(client, path, "Alt")

        response = client.post(f"{path}/{entry_id}", data={"name": "Neu"}, follow_redirects=False)

        assert response.status_code == 303
        listing = client.get(path)
        assert "Neu" in listing.text
        assert "Alt" not in listing.text

    def test_unknown_id_is_a_friendly_404(self, client: TestClient, path: str) -> None:
        response = client.post(f"{path}/999999", data={"name": "Irgendwas"})

        assert response.status_code == 404
        assert "nicht gefunden" in response.text

    def test_rename_to_duplicate_name_is_rejected_with_non_500(
        self, client: TestClient, path: str
    ) -> None:
        client.post(path, data={"name": "REWE"})
        client.post(path, data={"name": "Aldi"})
        aldi_id = _entry_id_by_name(client, path, "Aldi")

        response = client.post(f"{path}/{aldi_id}", data={"name": "REWE"})

        assert response.status_code == 422
        assert "bereits" in response.text


@pytest.mark.parametrize("path", ["/kategorien", "/laeden"])
class TestReorder:
    def test_moving_first_entry_up_is_a_harmless_noop(self, client: TestClient, path: str) -> None:
        for name in ["A", "B", "C"]:
            client.post(path, data={"name": name})
        first_id = _entry_id_by_name(client, path, "A")

        response = client.post(f"{path}/{first_id}/hoch", follow_redirects=False)

        assert response.status_code == 303
        assert _ordered_names(client, path) == ["A", "B", "C"]

    def test_moving_last_entry_down_is_a_harmless_noop(self, client: TestClient, path: str) -> None:
        for name in ["A", "B", "C"]:
            client.post(path, data={"name": name})
        last_id = _entry_id_by_name(client, path, "C")

        response = client.post(f"{path}/{last_id}/runter", follow_redirects=False)

        assert response.status_code == 303
        assert _ordered_names(client, path) == ["A", "B", "C"]

    def test_moving_up_and_down_stays_gapless(self, client: TestClient, path: str) -> None:
        for name in ["A", "B", "C"]:
            client.post(path, data={"name": name})
        first_id = _entry_id_by_name(client, path, "A")

        client.post(f"{path}/{first_id}/runter")
        assert _ordered_names(client, path) == ["B", "A", "C"]

        client.post(f"{path}/{first_id}/hoch")
        assert _ordered_names(client, path) == ["A", "B", "C"]

    def test_unknown_id_is_a_friendly_404(self, client: TestClient, path: str) -> None:
        response = client.post(f"{path}/999999/hoch")

        assert response.status_code == 404
        assert "nicht gefunden" in response.text


@pytest.mark.parametrize("path", ["/kategorien", "/laeden"])
class TestDelete:
    def test_deletes_an_unused_entry_and_redirects(self, client: TestClient, path: str) -> None:
        client.post(path, data={"name": "REWE"})
        entry_id = _entry_id_by_name(client, path, "REWE")

        response = client.post(f"{path}/{entry_id}/loeschen", follow_redirects=False)

        assert response.status_code == 303
        listing = client.get(path)
        assert "REWE" not in listing.text

    def test_unknown_id_is_a_friendly_404(self, client: TestClient, path: str) -> None:
        response = client.post(f"{path}/999999/loeschen")

        assert response.status_code == 404
        assert "nicht gefunden" in response.text

    def test_deleting_an_assigned_entry_is_rejected_with_item_count_and_non_500(
        self, client: TestClient, path: str
    ) -> None:
        client.post(path, data={"name": "REWE"})
        entry_id = _entry_id_by_name(client, path, "REWE")
        _create_item_assigned_to(client, path, entry_id)

        response = client.post(f"{path}/{entry_id}/loeschen")

        assert response.status_code == 422
        assert "REWE" in response.text
        assert "1" in response.text
        listing = client.get(path)
        assert "REWE" in listing.text  # nicht gelöscht


def _create_item_assigned_to(client: TestClient, path: str, entry_id: int) -> int:
    from app.services import stock

    connection = client.app.state.db  # type: ignore[attr-defined]
    kwargs = {"category_id": entry_id} if path == "/kategorien" else {"store_id": entry_id}
    return stock.create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        stock=1,
        reorder_level=1,
        target_stock=5,
        position=0,
        **kwargs,
    )


def _ordered_names(client: TestClient, path: str) -> list[str]:
    from app.repo import taxonomy as taxonomy_repo

    table: taxonomy_repo.TableName = "categories" if path == "/kategorien" else "stores"
    connection = client.app.state.db  # type: ignore[attr-defined]
    return [entry.name for entry in taxonomy_repo.list_all(connection, table)]


def _entry_id_by_name(client: TestClient, path: str, name: str) -> int:
    from app.repo import taxonomy as taxonomy_repo

    table: taxonomy_repo.TableName = "categories" if path == "/kategorien" else "stores"
    connection = client.app.state.db  # type: ignore[attr-defined]
    entries = taxonomy_repo.list_all(connection, table)
    return next(entry.id for entry in entries if entry.name == name)
