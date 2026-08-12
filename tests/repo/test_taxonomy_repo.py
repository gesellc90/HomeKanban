from __future__ import annotations

import sqlite3

import pytest

from app.repo import taxonomy as taxonomy_repo
from app.services import stock

_TABLES: tuple[taxonomy_repo.TableName, ...] = ("categories", "stores")


def _create_item_with(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName, entry_id: int
) -> int:
    kwargs = {"category_id": entry_id} if table == "categories" else {"store_id": entry_id}
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


@pytest.mark.parametrize("table", _TABLES)
def test_next_position_starts_at_zero_when_empty(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    assert taxonomy_repo.next_position(connection, table) == 0


@pytest.mark.parametrize("table", _TABLES)
def test_next_position_increments_past_existing_entries(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    taxonomy_repo.insert(connection, table, name="Erste", position=0)
    taxonomy_repo.insert(connection, table, name="Zweite", position=5)

    assert taxonomy_repo.next_position(connection, table) == 6


@pytest.mark.parametrize("table", _TABLES)
def test_list_all_orders_by_position(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    third_id = taxonomy_repo.insert(connection, table, name="C", position=2)
    first_id = taxonomy_repo.insert(connection, table, name="A", position=0)
    second_id = taxonomy_repo.insert(connection, table, name="B", position=1)

    entries = taxonomy_repo.list_all(connection, table)

    assert [entry.id for entry in entries] == [first_id, second_id, third_id]


@pytest.mark.parametrize("table", _TABLES)
def test_get_by_id_returns_none_for_unknown_id(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    assert taxonomy_repo.get_by_id(connection, table, 999) is None


@pytest.mark.parametrize("table", _TABLES)
def test_rename_changes_name_but_not_position(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    entry_id = taxonomy_repo.insert(connection, table, name="Alt", position=0)

    taxonomy_repo.rename(connection, table, entry_id, name="Neu")

    entry = taxonomy_repo.get_by_id(connection, table, entry_id)
    assert entry is not None
    assert entry.name == "Neu"
    assert entry.position == 0


@pytest.mark.parametrize("table", _TABLES)
def test_insert_duplicate_name_violates_unique_index(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    taxonomy_repo.insert(connection, table, name="REWE", position=0)

    with pytest.raises(sqlite3.IntegrityError):
        taxonomy_repo.insert(connection, table, name="REWE", position=1)


@pytest.mark.parametrize("table", _TABLES)
def test_rename_to_duplicate_name_violates_unique_index(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    taxonomy_repo.insert(connection, table, name="REWE", position=0)
    other_id = taxonomy_repo.insert(connection, table, name="Aldi", position=1)

    with pytest.raises(sqlite3.IntegrityError):
        taxonomy_repo.rename(connection, table, other_id, name="REWE")


@pytest.mark.parametrize("table", _TABLES)
def test_swap_positions_exchanges_both_entries(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    first_id = taxonomy_repo.insert(connection, table, name="A", position=0)
    second_id = taxonomy_repo.insert(connection, table, name="B", position=1)

    taxonomy_repo.swap_positions(
        connection,
        table,
        first_id=first_id,
        first_position=0,
        second_id=second_id,
        second_position=1,
    )

    entries = {entry.id: entry.position for entry in taxonomy_repo.list_all(connection, table)}
    assert entries[first_id] == 1
    assert entries[second_id] == 0


@pytest.mark.parametrize("table", _TABLES)
def test_count_assigned_items_is_zero_for_an_unused_entry(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    entry_id = taxonomy_repo.insert(connection, table, name="REWE", position=0)

    assert taxonomy_repo.count_assigned_items(connection, table, entry_id) == 0


@pytest.mark.parametrize("table", _TABLES)
def test_count_assigned_items_counts_archived_items_too(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    """Ein archivierter Artikel trägt seine Zuordnung weiter (docs/PLAN.md §3) — ein Löschen
    dürfte ohne diese Zählung in einen `IntegrityError` laufen (Frage 3 der M7-Fragerunde)."""
    from app.repo import items as items_repo

    entry_id = taxonomy_repo.insert(connection, table, name="REWE", position=0)
    item_id = _create_item_with(connection, table, entry_id)
    items_repo.archive(connection, item_id, "2026-01-01T00:00:00.000Z")

    assert taxonomy_repo.count_assigned_items(connection, table, entry_id) == 1


@pytest.mark.parametrize("table", _TABLES)
def test_delete_removes_an_unused_entry(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    entry_id = taxonomy_repo.insert(connection, table, name="REWE", position=0)

    taxonomy_repo.delete(connection, table, entry_id)

    assert taxonomy_repo.get_by_id(connection, table, entry_id) is None


@pytest.mark.parametrize("table", _TABLES)
def test_delete_of_an_assigned_entry_violates_the_foreign_key(
    connection: sqlite3.Connection, table: taxonomy_repo.TableName
) -> None:
    """Die Web-Schicht prüft vorher über `count_assigned_items` — hier nur der Nachweis, dass die
    Datenbank selbst ohne diese Prüfung nicht stillschweigend inkonsistent würde."""
    entry_id = taxonomy_repo.insert(connection, table, name="REWE", position=0)
    _create_item_with(connection, table, entry_id)

    with pytest.raises(sqlite3.IntegrityError):
        taxonomy_repo.delete(connection, table, entry_id)
