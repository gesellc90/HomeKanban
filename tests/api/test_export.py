"""Export-Schnittstelle für den Kurzbefehl (docs/PLAN.md §6, §7, L12).

Der Testfokus aus §9: Textformat zeichengenau, zweiter Export ohne zweite Liste, API-Key.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect
from app.main import create_app

API_KEY = "geheim-fuer-den-kurzbefehl"


def _connection(client: TestClient) -> sqlite3.Connection:
    return connect(client.app.state.settings.db_path)  # type: ignore[attr-defined]


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, db_path=tmp_path / "homekanban.db", api_key=API_KEY)


@pytest.fixture
def api_client(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(api_settings)) as test_client:
        yield test_client


@pytest.fixture
def keyless_client(tmp_path: Path) -> Iterator[TestClient]:
    """Ein Server, auf dem `HOMEKANBAN_API_KEY` schlicht fehlt (§8)."""
    settings = Settings(_env_file=None, db_path=tmp_path / "homekanban.db", api_key=None)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _create_item(
    client: TestClient,
    *,
    name: str,
    unit: str,
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


def _create_store(client: TestClient, name: str) -> int:
    client.post("/laeden", data={"name": name})
    connection = _connection(client)
    try:
        row = connection.execute("SELECT id FROM stores WHERE name = ?", (name,)).fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row["id"])


def _assign_store(client: TestClient, item_id: int, store_id: int) -> None:
    from app.repo import items as items_repo

    connection = _connection(client)
    try:
        item = items_repo.get_by_id(connection, item_id)
    finally:
        connection.close()
    assert item is not None
    response = client.post(
        f"/artikel/{item_id}",
        data={
            "name": item.name,
            "unit": item.unit,
            "reorder_level": str(item.reorder_level),
            "target_stock": str(item.target_stock),
            "pack_size": str(item.pack_size),
            "store_id": str(store_id),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def _list_row(client: TestClient) -> tuple[str | None, int]:
    connection = _connection(client)
    try:
        row = connection.execute(
            "SELECT exported_at, export_count FROM shopping_lists WHERE status = 'open'"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return row["exported_at"], int(row["export_count"])


# --- API-Key ----------------------------------------------------------------------------------


def test_missing_key_is_401(api_client: TestClient) -> None:
    assert api_client.get("/api/shopping-list").status_code == 401
    assert api_client.post("/api/shopping-list/export").status_code == 401


def test_wrong_key_is_401(api_client: TestClient) -> None:
    response = api_client.get("/api/shopping-list", headers={"X-API-Key": "falsch"})

    assert response.status_code == 401
    assert "API-Schlüssel" in response.json()["detail"]


def test_correct_key_in_header_is_200(api_client: TestClient) -> None:
    response = api_client.get("/api/shopping-list", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200


def test_correct_key_as_query_parameter_is_200(api_client: TestClient) -> None:
    """`?key=` lässt sich im Kurzbefehl leichter zusammenbauen als ein Header (L12)."""
    response = api_client.get(f"/api/shopping-list?key={API_KEY}")

    assert response.status_code == 200


def test_unconfigured_server_answers_503_not_401(keyless_client: TestClient) -> None:
    """Ein fehlender Schlüssel auf dem Server ist ein Konfigurationsfehler des Betreibers,
    keine fehlgeschlagene Authentifizierung (§8)."""
    response = keyless_client.get("/api/shopping-list", headers={"X-API-Key": API_KEY})

    assert response.status_code == 503
    assert "HOMEKANBAN_API_KEY" in response.json()["detail"]


def test_the_rest_of_the_app_stays_open(api_client: TestClient) -> None:
    """L12: Nur der Export ist authentifiziert — jede Hürde in der UI bräche den Zwei-Tap-
    Anspruch."""
    assert api_client.get("/").status_code == 200
    assert api_client.get("/liste").status_code == 200


def test_unknown_format_is_400(api_client: TestClient) -> None:
    response = api_client.get("/api/shopping-list?format=xml", headers={"X-API-Key": API_KEY})

    assert response.status_code == 400
    assert "text und json" in response.json()["detail"]


# --- GET verändert nichts ----------------------------------------------------------------------


def test_get_has_no_side_effect(api_client: TestClient) -> None:
    _create_item(api_client, name="Klopapier", unit="Rolle")
    api_client.post("/liste/erzeugen", follow_redirects=False)
    before = _list_row(api_client)

    api_client.get("/api/shopping-list", headers={"X-API-Key": API_KEY})

    assert _list_row(api_client) == before
    assert before == (None, 0)


def test_get_does_not_create_a_list(api_client: TestClient) -> None:
    _create_item(api_client, name="Klopapier", unit="Rolle")

    response = api_client.get("/api/shopping-list", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert response.text == ""
    connection = _connection(api_client)
    try:
        count = connection.execute("SELECT COUNT(*) AS n FROM shopping_lists").fetchone()["n"]
    finally:
        connection.close()
    assert count == 0


def test_post_records_the_export(api_client: TestClient) -> None:
    _create_item(api_client, name="Klopapier", unit="Rolle")

    api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})
    exported_at, export_count = _list_row(api_client)

    assert exported_at is not None
    assert export_count == 1


def test_second_export_reconciles_instead_of_creating_a_second_list(
    api_client: TestClient,
) -> None:
    _create_item(api_client, name="Klopapier", unit="Rolle")
    api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})
    _create_item(api_client, name="Kaffee", unit="Packung", target_stock=2, pack_size=1)

    response = api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})

    assert response.text == "Klopapier — 10 Rollen\nKaffee — 2 Packungen"
    connection = _connection(api_client)
    try:
        count = connection.execute("SELECT COUNT(*) AS n FROM shopping_lists").fetchone()["n"]
    finally:
        connection.close()
    assert count == 1
    assert _list_row(api_client)[1] == 2


# --- Textformat -------------------------------------------------------------------------------


def test_text_format_matches_the_plan_character_for_character(api_client: TestClient) -> None:
    """Das Beispiel aus docs/PLAN.md §6, inklusive Plural (§9: „zeichengenau“)."""
    _create_item(
        api_client,
        name="Spülmaschinentabs",
        unit="Packung",
        reorder_level=1,
        target_stock=2,
        pack_size=1,
        stock=1,
    )
    _create_item(api_client, name="Klopapier", unit="Rolle", target_stock=10, pack_size=10)
    _create_item(
        api_client, name="Kaffee", unit="Packung", reorder_level=1, target_stock=2, pack_size=2
    )

    response = api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == (
        "Spülmaschinentabs — 1 Packung\nKlopapier — 10 Rollen\nKaffee — 2 Packungen"
    )


def test_empty_list_exports_empty_text(api_client: TestClient) -> None:
    """Eine leere Liste ist ein gültiges Ergebnis, kein Fehler (§6). Ohne abschließenden
    Zeilenumbruch — sonst entstünde im Kurzbefehl ein leerer Punkt in der Notiz."""
    response = api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert response.text == ""


def test_checked_lines_do_not_appear_in_the_export(api_client: TestClient) -> None:
    _create_item(api_client, name="Klopapier", unit="Rolle")
    api_client.post("/liste/erzeugen", follow_redirects=False)
    connection = _connection(api_client)
    try:
        row = connection.execute("SELECT id, list_id FROM shopping_list_lines").fetchone()
    finally:
        connection.close()
    api_client.post(
        f"/liste/{row['list_id']}/zeilen/{row['id']}/abhaken", data={}, follow_redirects=False
    )

    response = api_client.get("/api/shopping-list", headers={"X-API-Key": API_KEY})

    assert response.text == ""


# --- JSON -------------------------------------------------------------------------------------


def test_json_format(api_client: TestClient) -> None:
    _create_item(api_client, name="Klopapier", unit="Rolle")
    api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})

    payload = api_client.get(
        "/api/shopping-list?format=json", headers={"X-API-Key": API_KEY}
    ).json()

    assert payload["export_count"] == 1
    assert payload["exported_at"] is not None
    assert len(payload["lines"]) == 1
    line = payload["lines"][0]
    assert line["name"] == "Klopapier"
    assert line["unit"] == "Rolle"
    assert line["unit_display"] == "Rollen"
    assert line["quantity"] == 10
    assert line["text"] == "Klopapier — 10 Rollen"


def test_json_without_open_list(api_client: TestClient) -> None:
    payload = api_client.get(
        "/api/shopping-list?format=json", headers={"X-API-Key": API_KEY}
    ).json()

    assert payload["list_id"] is None
    assert payload["lines"] == []


# --- Gruppierung nach Laden (M7) ----------------------------------------------------------------


def test_text_format_without_any_store_has_no_group_headers(api_client: TestClient) -> None:
    """M7, Frage 2: Eine einzelne "Sonstiges"-Gruppe — hier: gar kein Laden im Haushalt angelegt —
    bekommt keine Überschrift, sonst wäre jede Liste ohne Taxonomie-Pflege mit einem
    überflüssigen Punkt verunstaltet."""
    _create_item(api_client, name="Klopapier", unit="Rolle")
    _create_item(api_client, name="Kaffee", unit="Packung", target_stock=2, pack_size=1)

    response = api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})

    assert "Sonstiges" not in response.text
    assert response.text == "Klopapier — 10 Rollen\nKaffee — 2 Packungen"


def test_text_format_groups_by_store_with_header_lines(api_client: TestClient) -> None:
    """§9 M7 Definition of Done: Export gruppiert nach Laden. M7, Frage 2: Der Ladenname steht als
    eigene Zeile — auch wenn der Kurzbefehl daraus einen abhakbaren Punkt macht."""
    rewe_id = _create_store(api_client, "REWE")
    aldi_id = _create_store(api_client, "Aldi")
    klopapier_id = _create_item(api_client, name="Klopapier", unit="Rolle")
    kaffee_id = _create_item(api_client, name="Kaffee", unit="Packung", target_stock=2, pack_size=1)
    seife_id = _create_item(api_client, name="Seife", unit="Stück", target_stock=3, pack_size=1)
    _assign_store(api_client, klopapier_id, rewe_id)
    _assign_store(api_client, kaffee_id, aldi_id)
    # Seife bleibt ohne Laden → landet in "Sonstiges".
    assert seife_id > 0

    response = api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})

    assert response.text == (
        "REWE\nKlopapier — 10 Rollen\nAldi\nKaffee — 2 Packungen\nSonstiges\nSeife — 3 Stück"
    )


def test_json_format_includes_groups(api_client: TestClient) -> None:
    rewe_id = _create_store(api_client, "REWE")
    item_id = _create_item(api_client, name="Klopapier", unit="Rolle")
    _assign_store(api_client, item_id, rewe_id)

    payload = api_client.post(
        "/api/shopping-list/export?format=json", headers={"X-API-Key": API_KEY}
    ).json()

    assert len(payload["groups"]) == 1
    assert payload["groups"][0]["label"] == "REWE"
    assert len(payload["groups"][0]["lines"]) == 1
    assert payload["groups"][0]["lines"][0]["name"] == "Klopapier"
    # Die flache Liste bleibt zusätzlich erhalten (Debugging/Rückwärtskompatibilität).
    assert len(payload["lines"]) == 1


# --- Schnappschuss ----------------------------------------------------------------------------


def test_export_keeps_the_name_the_item_had_when_the_list_was_created(
    api_client: TestClient,
) -> None:
    """§3: Wird ein Artikel umbenannt, während die Liste im Supermarkt offen ist, behält die
    Liste den alten Namen."""
    item_id = _create_item(api_client, name="Klopapier", unit="Rolle")
    api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})

    api_client.post(
        f"/artikel/{item_id}",
        data={
            "name": "Toilettenpapier",
            "unit": "Packung",
            "reorder_level": "1",
            "target_stock": "10",
            "pack_size": "10",
        },
        follow_redirects=False,
    )
    response = api_client.post("/api/shopping-list/export", headers={"X-API-Key": API_KEY})

    assert response.text == "Klopapier — 10 Rollen"
