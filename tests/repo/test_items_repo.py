from __future__ import annotations

import sqlite3

import pytest

from app.repo import items as items_repo
from app.repo import taxonomy as taxonomy_repo
from app.services import stock

_NOW = "2026-01-01T00:00:00.000Z"


def _create(connection: sqlite3.Connection, *, name: str = "Kaffee", position: int = 0) -> int:
    return stock.create_item(
        connection,
        name=name,
        unit="Packung",
        stock=3,
        reorder_level=1,
        target_stock=5,
        position=position,
    )


def test_next_position_starts_at_zero_when_empty(connection: sqlite3.Connection) -> None:
    assert items_repo.next_position(connection) == 0


def test_next_position_increments_past_existing_items(connection: sqlite3.Connection) -> None:
    _create(connection, name="Kaffee", position=0)
    _create(connection, name="Tee", position=5)

    assert items_repo.next_position(connection) == 6


def test_update_changes_stammdaten_but_not_stock(connection: sqlite3.Connection) -> None:
    item_id = _create(connection)

    items_repo.update(
        connection,
        item_id,
        name="Bio-Kaffee",
        unit="Beutel",
        note="Marke egal",
        reorder_level=2,
        target_stock=8,
        pack_size=2,
        lead_days=7,
        category_id=None,
        store_id=None,
        updated_at=_NOW,
    )

    item = items_repo.get_by_id(connection, item_id)
    assert item is not None
    assert item.name == "Bio-Kaffee"
    assert item.unit == "Beutel"
    assert item.note == "Marke egal"
    assert item.reorder_level == 2
    assert item.target_stock == 8
    assert item.pack_size == 2
    assert item.stock == 3  # unverändert — Bestand läuft nur über das Bewegungsjournal


def test_update_persists_category_and_store_assignment(connection: sqlite3.Connection) -> None:
    """Regressionstest zur Lücke aus docs/PLAN.md §9 M7 Punkt 4: `update()` kannte
    `category_id`/`store_id` bisher nicht, die Zuordnung fiel beim Speichern still unter den
    Tisch."""
    item_id = _create(connection)
    category_id = taxonomy_repo.insert(connection, "categories", name="Vorrat", position=0)
    store_id = taxonomy_repo.insert(connection, "stores", name="REWE", position=0)

    items_repo.update(
        connection,
        item_id,
        name="Kaffee",
        unit="Packung",
        note=None,
        reorder_level=1,
        target_stock=5,
        pack_size=1,
        lead_days=7,
        category_id=category_id,
        store_id=store_id,
        updated_at=_NOW,
    )

    item = items_repo.get_by_id(connection, item_id)
    assert item is not None
    assert item.category_id == category_id
    assert item.store_id == store_id


def test_update_to_duplicate_active_name_violates_check(connection: sqlite3.Connection) -> None:
    _create(connection, name="Kaffee", position=0)
    other_id = _create(connection, name="Tee", position=1)

    with pytest.raises(sqlite3.IntegrityError):
        items_repo.update(
            connection,
            other_id,
            name="KAFFEE",
            unit="Packung",
            note=None,
            reorder_level=1,
            target_stock=5,
            pack_size=1,
            lead_days=7,
            category_id=None,
            store_id=None,
            updated_at=_NOW,
        )


def test_create_item_defaults_lead_days_to_seven(connection: sqlite3.Connection) -> None:
    item_id = _create(connection)

    item = items_repo.get_by_id(connection, item_id)
    assert item is not None
    assert item.lead_days == 7


def test_update_changes_lead_days(connection: sqlite3.Connection) -> None:
    item_id = _create(connection)

    items_repo.update(
        connection,
        item_id,
        name="Kaffee",
        unit="Packung",
        note=None,
        reorder_level=1,
        target_stock=5,
        pack_size=1,
        lead_days=14,
        category_id=None,
        store_id=None,
        updated_at=_NOW,
    )

    item = items_repo.get_by_id(connection, item_id)
    assert item is not None
    assert item.lead_days == 14


def test_update_reorder_level_changes_only_that_field(connection: sqlite3.Connection) -> None:
    item_id = _create(connection)
    before = items_repo.get_by_id(connection, item_id)
    assert before is not None

    items_repo.update_reorder_level(connection, item_id, reorder_level=3, updated_at=_NOW)

    after = items_repo.get_by_id(connection, item_id)
    assert after is not None
    assert after.reorder_level == 3
    assert after.updated_at == _NOW
    assert after.name == before.name
    assert after.target_stock == before.target_stock
    assert after.pack_size == before.pack_size
    assert after.lead_days == before.lead_days


def test_reactivate_clears_archived_at(connection: sqlite3.Connection) -> None:
    item_id = _create(connection)
    items_repo.archive(connection, item_id, _NOW)

    items_repo.reactivate(connection, item_id, _NOW)

    item = items_repo.get_by_id(connection, item_id)
    assert item is not None
    assert item.archived_at is None


def test_reactivate_with_name_taken_by_active_item_violates_check(
    connection: sqlite3.Connection,
) -> None:
    archived_id = _create(connection, name="Kaffee", position=0)
    items_repo.archive(connection, archived_id, _NOW)
    _create(connection, name="Kaffee", position=1)  # belegt den Namen jetzt aktiv

    with pytest.raises(sqlite3.IntegrityError):
        items_repo.reactivate(connection, archived_id, _NOW)
