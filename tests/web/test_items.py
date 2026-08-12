from __future__ import annotations

from fastapi.testclient import TestClient


def _create_item(
    client: TestClient,
    *,
    name: str = "Testartikel",
    unit: str = "Packung",
    stock: int = 5,
    reorder_level: int = 2,
    target_stock: int = 5,
    pack_size: int = 1,
    note: str = "",
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
            "note": note,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[-1])


class TestNewItemForm:
    def test_returns_200_with_empty_form(self, client: TestClient) -> None:
        response = client.get("/artikel/neu")

        assert response.status_code == 200
        assert "Neuer Artikel" in response.text


class TestCreateItem:
    def test_valid_submission_creates_item_and_redirects(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)

        response = client.get(f"/artikel/{item_id}")
        assert response.status_code == 200
        assert "Kaffee" in response.text
        assert "Anfangsbestand" in response.text or "3 Packung" in response.text

    def test_empty_name_is_rejected_with_german_message_and_non_500(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/artikel",
            data={
                "name": "",
                "unit": "Packung",
                "stock": "1",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
            },
        )

        assert response.status_code == 422
        assert "Name" in response.text

    def test_target_stock_not_above_reorder_level_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/artikel",
            data={
                "name": "Ungültig",
                "unit": "Packung",
                "stock": "1",
                "reorder_level": "5",
                "target_stock": "5",
                "pack_size": "1",
            },
        )

        assert response.status_code == 422
        assert "Sollbestand" in response.text

    def test_pack_size_below_one_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/artikel",
            data={
                "name": "Ungültig",
                "unit": "Packung",
                "stock": "1",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "0",
            },
        )

        assert response.status_code == 422
        assert "Kaufeinheit" in response.text

    def test_negative_stock_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/artikel",
            data={
                "name": "Ungültig",
                "unit": "Packung",
                "stock": "-1",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
            },
        )

        assert response.status_code == 422
        assert "Bestand" in response.text

    def test_duplicate_name_case_insensitive_is_rejected_with_german_message(
        self, client: TestClient
    ) -> None:
        _create_item(client, name="Kaffee")

        response = client.post(
            "/artikel",
            data={
                "name": "KAFFEE",
                "unit": "Packung",
                "stock": "1",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
            },
        )

        assert response.status_code == 422
        assert "bereits" in response.text


class TestItemDetail:
    def test_returns_200_with_name_status_and_history(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)

        response = client.get(f"/artikel/{item_id}")

        assert response.status_code == 200
        assert "Kaffee" in response.text
        assert "Ausreichend" in response.text
        assert "Anfangsbestand" in response.text  # Verlauf zeigt die opening-Bewegung

    def test_unknown_item_returns_404(self, client: TestClient) -> None:
        response = client.get("/artikel/999999")

        assert response.status_code == 404


class TestUpdateItem:
    def test_valid_update_redirects_and_changes_stammdaten(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", reorder_level=1, target_stock=5)

        response = client.post(
            f"/artikel/{item_id}",
            data={
                "name": "Bio-Kaffee",
                "unit": "Packung",
                "note": "Marke egal",
                "reorder_level": "2",
                "target_stock": "6",
                "pack_size": "1",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        detail = client.get(f"/artikel/{item_id}")
        assert "Bio-Kaffee" in detail.text
        assert "Marke egal" in detail.text

    def test_invalid_update_is_rejected_with_non_500(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", reorder_level=1, target_stock=5)

        response = client.post(
            f"/artikel/{item_id}",
            data={
                "name": "Kaffee",
                "unit": "Packung",
                "note": "",
                "reorder_level": "5",
                "target_stock": "5",
                "pack_size": "1",
            },
        )

        assert response.status_code == 422
        assert "Sollbestand" in response.text

    def test_renaming_to_existing_active_name_is_rejected(self, client: TestClient) -> None:
        _create_item(client, name="Kaffee")
        other_id = _create_item(client, name="Tee")

        response = client.post(
            f"/artikel/{other_id}",
            data={
                "name": "KAFFEE",
                "unit": "Packung",
                "note": "",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
            },
        )

        assert response.status_code == 422
        assert "bereits" in response.text


class TestTaxonomyAssignment:
    """Regressionstest zur Lücke aus docs/PLAN.md §9 M7 Punkt 4: `items_repo.update()` kannte
    `category_id`/`store_id` bisher nicht, die Zuordnung fiel beim Speichern still unter den
    Tisch."""

    def test_category_and_store_survive_creation(self, client: TestClient) -> None:
        client.post("/kategorien", data={"name": "Vorrat"})
        client.post("/laeden", data={"name": "REWE"})
        category_id = _taxonomy_id(client, "categories", "Vorrat")
        store_id = _taxonomy_id(client, "stores", "REWE")

        item_id = _create_item(client, name="Kaffee")
        response = client.post(
            f"/artikel/{item_id}",
            data={
                "name": "Kaffee",
                "unit": "Packung",
                "note": "",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
                "category_id": str(category_id),
                "store_id": str(store_id),
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        from app.repo import items as items_repo

        item = items_repo.get_by_id(client.app.state.db, item_id)  # type: ignore[attr-defined]
        assert item is not None
        assert item.category_id == category_id
        assert item.store_id == store_id

    def test_none_selection_clears_assignment(self, client: TestClient) -> None:
        client.post("/kategorien", data={"name": "Vorrat"})
        category_id = _taxonomy_id(client, "categories", "Vorrat")
        item_id = _create_item(client, name="Kaffee")
        client.post(
            f"/artikel/{item_id}",
            data={
                "name": "Kaffee",
                "unit": "Packung",
                "note": "",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
                "category_id": str(category_id),
                "store_id": "",
            },
        )

        client.post(
            f"/artikel/{item_id}",
            data={
                "name": "Kaffee",
                "unit": "Packung",
                "note": "",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
                "category_id": "",
                "store_id": "",
            },
        )

        from app.repo import items as items_repo

        item = items_repo.get_by_id(client.app.state.db, item_id)  # type: ignore[attr-defined]
        assert item is not None
        assert item.category_id is None

    def test_unknown_category_id_is_rejected_with_german_message_and_non_500(
        self, client: TestClient
    ) -> None:
        item_id = _create_item(client, name="Kaffee")

        response = client.post(
            f"/artikel/{item_id}",
            data={
                "name": "Kaffee",
                "unit": "Packung",
                "note": "",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
                "category_id": "999999",
                "store_id": "",
            },
        )

        assert response.status_code == 422
        assert "Unbekannte Kategorie-Auswahl" in response.text

    def test_unknown_store_id_on_creation_is_rejected_with_german_message_and_non_500(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/artikel",
            data={
                "name": "Kaffee",
                "unit": "Packung",
                "stock": "1",
                "reorder_level": "1",
                "target_stock": "5",
                "pack_size": "1",
                "category_id": "",
                "store_id": "999999",
            },
        )

        assert response.status_code == 422
        assert "Unbekannte Laden-Auswahl" in response.text


def _taxonomy_id(client: TestClient, table: str, name: str) -> int:
    from app.repo import taxonomy as taxonomy_repo

    connection = client.app.state.db  # type: ignore[attr-defined]
    entries = taxonomy_repo.list_all(connection, table)  # type: ignore[arg-type]
    return next(entry.id for entry in entries if entry.name == name)


class TestApplyInventory:
    def test_matching_expected_stock_updates_and_redirects(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)

        response = client.post(
            f"/artikel/{item_id}/inventur",
            data={"expected_stock": "3", "actual_stock": "1"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        detail = client.get(f"/artikel/{item_id}")
        assert "1 Packung" in detail.text
        assert "Nachkaufen" in detail.text  # 1 <= reorder_level 1

    def test_stale_expected_stock_is_rejected_with_current_stock_shown(
        self, client: TestClient
    ) -> None:
        item_id = _create_item(client, name="Kaffee", stock=3, reorder_level=1, target_stock=5)

        response = client.post(
            f"/artikel/{item_id}/inventur",
            data={"expected_stock": "999", "actual_stock": "0"},
        )

        assert response.status_code == 409
        assert "geändert" in response.text
        assert "tatsächlich sind es 3" in response.text  # der jetzt gültige Bestand

        # Bestand bleibt unverändert — kein stilles Überschreiben (L10).
        detail = client.get(f"/artikel/{item_id}")
        assert "3 Packung" in detail.text


class TestArchiveAndReactivate:
    def test_archive_redirects_to_board_and_marks_item_archived(self, client: TestClient) -> None:
        item_id = _create_item(client, name="Kaffee")

        response = client.post(f"/artikel/{item_id}/archivieren", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/"
        detail = client.get(f"/artikel/{item_id}")
        assert "Archiviert am" in detail.text

    def test_reactivate_redirects_to_detail_and_clears_archived_at(
        self, client: TestClient
    ) -> None:
        item_id = _create_item(client, name="Kaffee")
        client.post(f"/artikel/{item_id}/archivieren", follow_redirects=False)

        response = client.post(f"/artikel/{item_id}/reaktivieren", follow_redirects=False)

        assert response.status_code == 303
        detail = client.get(f"/artikel/{item_id}")
        assert "Archiviert am" not in detail.text

    def test_reactivate_with_name_taken_in_the_meantime_is_rejected(
        self, client: TestClient
    ) -> None:
        original_id = _create_item(client, name="Kaffee")
        client.post(f"/artikel/{original_id}/archivieren", follow_redirects=False)
        _create_item(client, name="Kaffee")  # belegt den Namen jetzt aktiv

        response = client.post(f"/artikel/{original_id}/reaktivieren")

        assert response.status_code == 422
        assert "bereits" in response.text or "vergeben" in response.text
        detail = client.get(f"/artikel/{original_id}")
        assert "Archiviert am" in detail.text  # weiterhin archiviert
