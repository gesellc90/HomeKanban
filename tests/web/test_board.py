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


def test_board_renders_empty_columns(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Ausreichend" in response.text
    assert "Nachkaufen" in response.text
    assert "Auf Liste" in response.text
    assert "Noch leer" in response.text  # Placeholder für die leere "Auf Liste"-Spalte


def test_item_above_reorder_level_lands_in_ok_column(client: TestClient) -> None:
    _create_item(client, name="Genug da", stock=6, reorder_level=5, target_stock=10)

    response = client.get("/")

    assert "Genug da" in response.text


def test_item_exactly_on_reorder_level_lands_in_reorder_column(client: TestClient) -> None:
    """Regel 2 aus docs/PLAN.md §4: `stock <= reorder_level` → NACHKAUFEN, auch auf der Schwelle."""
    _create_item(client, name="Genau auf Schwelle", stock=5, reorder_level=5, target_stock=10)

    response = client.get("/")

    assert "Genau auf Schwelle" in response.text
    assert "Vorschlag:" in response.text


def test_item_one_above_reorder_level_lands_in_ok_column(client: TestClient) -> None:
    _create_item(client, name="Knapp drüber", stock=6, reorder_level=5, target_stock=10)

    response = client.get("/")
    body = response.text
    # "Knapp drüber" darf nicht mit einem Nachkauf-Vorschlag auftauchen.
    card_start = body.index("Knapp drüber")
    card_snippet = body[card_start : card_start + 300]
    assert "Vorschlag:" not in card_snippet


def test_archived_items_do_not_appear_on_board(client: TestClient) -> None:
    item_id = _create_item(client, name="Wird archiviert")

    archive_response = client.post(f"/artikel/{item_id}/archivieren", follow_redirects=False)
    assert archive_response.status_code == 303

    response = client.get("/")
    assert "Wird archiviert" not in response.text


def test_reorder_column_shows_reorder_quantity(client: TestClient) -> None:
    _create_item(
        client,
        name="Klopapier",
        unit="Rolle",
        stock=0,
        reorder_level=1,
        target_stock=10,
        pack_size=10,
    )

    response = client.get("/")

    assert "Vorschlag: 10 Rolle" in response.text
