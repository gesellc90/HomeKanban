"""Endpunkttests der Einkaufsliste (docs/PLAN.md §7, M4).

Geprüft wird, was der Nutzer erlebt: Statuscodes, Weiterleitungen, das HTMX-Partial, und dass
jede Fehlbedienung auf einer verständlichen deutschen Seite endet statt in einem Stacktrace.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

HTMX_HEADERS = {"HX-Request": "true"}


def _create_item(
    client: TestClient,
    *,
    name: str = "Klopapier",
    unit: str = "Rolle",
    stock: int = 0,
    reorder_level: int = 1,
    target_stock: int = 10,
    pack_size: int = 10,
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


def _create_list(client: TestClient) -> int:
    response = client.post("/liste/erzeugen", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/liste"
    row = client.app.state.db.execute(  # type: ignore[attr-defined]
        "SELECT id FROM shopping_lists WHERE status = 'open'"
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _line_ids(client: TestClient, list_id: int) -> list[int]:
    rows = client.app.state.db.execute(  # type: ignore[attr-defined]
        "SELECT id FROM shopping_list_lines WHERE list_id = ? AND dropped_at IS NULL "
        "ORDER BY position",
        (list_id,),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _stock(client: TestClient, item_id: int) -> int:
    row = client.app.state.db.execute(  # type: ignore[attr-defined]
        "SELECT stock FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    return int(row["stock"])


# --- Anzeige ----------------------------------------------------------------------------------


def test_list_page_without_open_list_is_friendly_not_404(client: TestClient) -> None:
    response = client.get("/liste")

    assert response.status_code == 200
    assert "keine offene Einkaufsliste" in response.text
    assert "Liste erzeugen" in response.text


def test_creating_a_list_shows_the_needed_items(client: TestClient) -> None:
    _create_item(client, name="Klopapier", unit="Rolle", stock=0)
    _create_item(client, name="Genug da", stock=9, reorder_level=1, target_stock=10)

    _create_list(client)
    response = client.get("/liste")

    assert response.status_code == 200
    assert "Klopapier" in response.text
    assert "10 Rollen" in response.text  # Plural im Text (§6)
    assert "Genug da" not in response.text
    assert "Alles gekauft" in response.text


def test_list_page_shows_a_sonstiges_heading_for_unassigned_items(client: TestClient) -> None:
    """Anders als im Kurzbefehl-Textexport (M7, Frage 2) kostet eine Überschrift in der
    Weboberfläche keinen Fremdpunkt — sie erscheint deshalb auch für die alleinige
    "Sonstiges"-Gruppe."""
    _create_item(client, name="Klopapier", unit="Rolle", stock=0)

    _create_list(client)
    response = client.get("/liste")

    assert "Sonstiges" in response.text


def test_list_page_groups_lines_by_store(client: TestClient) -> None:
    client.post("/laeden", data={"name": "REWE"})
    store_row = client.app.state.db.execute(  # type: ignore[attr-defined]
        "SELECT id FROM stores WHERE name = 'REWE'"
    ).fetchone()
    store_id = store_row["id"]
    item_id = _create_item(client, name="Klopapier", unit="Rolle", stock=0)
    client.post(
        f"/artikel/{item_id}",
        data={
            "name": "Klopapier",
            "unit": "Rolle",
            "reorder_level": "1",
            "target_stock": "10",
            "pack_size": "10",
            "store_id": str(store_id),
        },
    )
    _create_item(client, name="Seife", unit="Stück", stock=0, target_stock=3, pack_size=1)

    _create_list(client)
    response = client.get("/liste")

    assert response.status_code == 200
    assert response.text.index("REWE") < response.text.index("Klopapier")
    assert response.text.index("Sonstiges") < response.text.index("Seife")
    assert response.text.index("REWE") < response.text.index("Sonstiges")


def test_empty_list_says_so_instead_of_failing(client: TestClient) -> None:
    _create_list(client)

    response = client.get("/liste")

    assert response.status_code == 200
    assert "Nichts zu kaufen" in response.text


def test_board_links_to_the_list(client: TestClient) -> None:
    response = client.get("/")

    assert 'href="/liste"' in response.text


# --- Abhaken ----------------------------------------------------------------------------------


def test_check_without_javascript_redirects_to_the_list(client: TestClient) -> None:
    item_id = _create_item(client)
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]

    response = client.post(
        f"/liste/{list_id}/zeilen/{line_id}/abhaken", data={}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/liste"
    assert _stock(client, item_id) == 10


def test_check_with_htmx_returns_the_line_partial(client: TestClient) -> None:
    item_id = _create_item(client)
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]

    response = client.post(
        f"/liste/{list_id}/zeilen/{line_id}/abhaken", data={}, headers=HTMX_HEADERS
    )

    assert response.status_code == 200
    assert f'id="zeile-{line_id}"' in response.text
    assert "<!doctype html>" not in response.text.lower()  # Partial, keine ganze Seite
    assert "Doch nicht gekauft" in response.text
    assert 'hx-swap-oob="true"' in response.text  # Zählung oben wandert mit
    assert _stock(client, item_id) == 10


def test_check_with_quantity_adds_instead_of_setting(client: TestClient) -> None:
    item_id = _create_item(client, stock=2, reorder_level=3, target_stock=8, pack_size=1)
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]

    client.post(
        f"/liste/{list_id}/zeilen/{line_id}/abhaken",
        data={"purchased_qty": "3"},
        follow_redirects=False,
    )

    assert _stock(client, item_id) == 5


def test_checking_twice_answers_409_and_books_once(client: TestClient) -> None:
    item_id = _create_item(client)
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]
    client.post(f"/liste/{list_id}/zeilen/{line_id}/abhaken", data={}, follow_redirects=False)

    response = client.post(
        f"/liste/{list_id}/zeilen/{line_id}/abhaken", data={}, headers=HTMX_HEADERS
    )

    assert response.status_code == 409
    assert "schon abgehakt" in response.text
    assert _stock(client, item_id) == 10


def test_nonsensical_quantity_answers_422(client: TestClient) -> None:
    item_id = _create_item(client)
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]

    response = client.post(
        f"/liste/{list_id}/zeilen/{line_id}/abhaken",
        data={"purchased_qty": "drei"},
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 422
    assert "keine Menge" in response.text
    assert _stock(client, item_id) == 0


def test_negative_quantity_answers_422(client: TestClient) -> None:
    _create_item(client)
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]

    response = client.post(
        f"/liste/{list_id}/zeilen/{line_id}/abhaken",
        data={"purchased_qty": "-2"},
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "größer als 0" in response.text


def test_check_all_books_every_open_line(client: TestClient) -> None:
    first = _create_item(client, name="Klopapier")
    second = _create_item(
        client, name="Kaffee", unit="Packung", stock=1, reorder_level=2, target_stock=4, pack_size=1
    )
    list_id = _create_list(client)

    response = client.post(f"/liste/{list_id}/alles-gekauft", follow_redirects=False)

    assert response.status_code == 303
    assert _stock(client, first) == 10
    assert _stock(client, second) == 4


def test_unknown_line_answers_404(client: TestClient) -> None:
    list_id = _create_list(client)

    response = client.post(f"/liste/{list_id}/zeilen/4711/abhaken", data={})

    assert response.status_code == 404
    assert "Position" in response.text


def test_unknown_list_answers_404(client: TestClient) -> None:
    response = client.post("/liste/4711/abschliessen")

    assert response.status_code == 404
    assert "nicht gefunden" in response.text


# --- Zurücknehmen -----------------------------------------------------------------------------


def test_uncheck_restores_the_open_state(client: TestClient) -> None:
    item_id = _create_item(client)
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]
    client.post(f"/liste/{list_id}/zeilen/{line_id}/abhaken", data={}, follow_redirects=False)

    response = client.post(f"/liste/{list_id}/zeilen/{line_id}/zuruecknehmen", headers=HTMX_HEADERS)

    assert response.status_code == 200
    assert "Gekauft</button>" in response.text
    assert _stock(client, item_id) == 0


def test_unchecking_an_open_line_is_harmless(client: TestClient) -> None:
    item_id = _create_item(client)
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]

    response = client.post(
        f"/liste/{list_id}/zeilen/{line_id}/zuruecknehmen", follow_redirects=False
    )

    assert response.status_code == 303
    assert _stock(client, item_id) == 0


# --- Abschließen ------------------------------------------------------------------------------


def test_completing_leaves_open_items_in_reorder(client: TestClient) -> None:
    _create_item(client, name="Klopapier")
    _create_item(
        client, name="Kaffee", unit="Packung", reorder_level=1, target_stock=4, pack_size=1
    )
    list_id = _create_list(client)
    first_line = _line_ids(client, list_id)[0]
    client.post(f"/liste/{list_id}/zeilen/{first_line}/abhaken", data={}, follow_redirects=False)

    response = client.post(f"/liste/{list_id}/abschliessen", follow_redirects=False)

    assert response.status_code == 303
    board = client.get("/")
    assert "Kaffee" in board.text
    assert "Nachkaufen" in board.text
    # Der offene Artikel steht wieder im Nachkaufen und kommt mit der nächsten Liste zurück.
    new_list_id = _create_list(client)
    assert new_list_id != list_id
    assert "Kaffee" in client.get("/liste").text


def test_completing_twice_answers_409(client: TestClient) -> None:
    list_id = _create_list(client)
    client.post(f"/liste/{list_id}/abschliessen", follow_redirects=False)

    response = client.post(f"/liste/{list_id}/abschliessen")

    assert response.status_code == 409
    assert "abgeschlossen" in response.text


# --- Statusableitung über die echte Liste (§4 Regel 3) -----------------------------------------


def test_item_on_the_list_moves_to_the_on_list_column(client: TestClient) -> None:
    """Bis M3 lieferte `has_open_unchecked_line` immer False — ab jetzt nicht mehr."""
    _create_item(client, name="Klopapier")
    board_before = client.get("/").text
    assert "Nachkaufen" in board_before

    _create_list(client)
    board_after = client.get("/").text

    assert "Auf Liste" in board_after
    assert "item-card--on-list" in board_after


def test_checked_item_leaves_the_on_list_column(client: TestClient) -> None:
    _create_item(client, name="Klopapier")
    list_id = _create_list(client)
    line_id = _line_ids(client, list_id)[0]

    client.post(f"/liste/{list_id}/zeilen/{line_id}/abhaken", data={}, follow_redirects=False)

    assert "item-card--ok" in client.get("/").text
