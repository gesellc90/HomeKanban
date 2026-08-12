from __future__ import annotations

import sqlite3

from app.repo import shopping_lists as shopping_lists_repo
from app.services import stock

_NOW = "2026-01-01T00:00:00.000Z"


def _create_item(connection: sqlite3.Connection, *, name: str, position: int) -> int:
    return stock.create_item(
        connection,
        name=name,
        unit="Packung",
        stock=3,
        reorder_level=1,
        target_stock=5,
        position=position,
    )


def _open_line(connection: sqlite3.Connection, *, item_id: int) -> None:
    list_id = connection.execute(
        "INSERT INTO shopping_lists (status, created_at) VALUES ('open', ?)", (_NOW,)
    ).lastrowid
    connection.execute(
        """
        INSERT INTO shopping_list_lines (
            list_id, item_id, suggested_qty, name_snapshot, unit_snapshot, position
        ) VALUES (?, ?, 1, 'Kaffee', 'Packung', 0)
        """,
        (list_id, item_id),
    )


def test_open_unchecked_item_ids_returns_empty_set_for_empty_input(
    connection: sqlite3.Connection,
) -> None:
    assert shopping_lists_repo.open_unchecked_item_ids(connection, []) == set()


def test_open_unchecked_item_ids_finds_only_items_with_open_lines(
    connection: sqlite3.Connection,
) -> None:
    with_line = _create_item(connection, name="Kaffee", position=0)
    without_line = _create_item(connection, name="Tee", position=1)
    _open_line(connection, item_id=with_line)

    result = shopping_lists_repo.open_unchecked_item_ids(connection, [with_line, without_line])

    assert result == {with_line}


def test_open_unchecked_item_ids_ignores_ids_not_in_the_query(
    connection: sqlite3.Connection,
) -> None:
    with_line = _create_item(connection, name="Kaffee", position=0)
    _open_line(connection, item_id=with_line)

    assert shopping_lists_repo.open_unchecked_item_ids(connection, []) == set()


def test_insert_line_persists_store_and_category_snapshot(connection: sqlite3.Connection) -> None:
    item_id = _create_item(connection, name="Kaffee", position=0)
    list_id = connection.execute(
        "INSERT INTO shopping_lists (status, created_at) VALUES ('open', ?)", (_NOW,)
    ).lastrowid
    assert list_id is not None

    line_id = shopping_lists_repo.insert_line(
        connection,
        list_id=list_id,
        item_id=item_id,
        suggested_qty=1,
        name_snapshot="Kaffee",
        unit_snapshot="Packung",
        position=0,
        store_snapshot="REWE",
        store_position_snapshot=0,
        category_snapshot="Kühlregal",
        category_position_snapshot=2,
    )

    line = shopping_lists_repo.get_line(connection, line_id)
    assert line is not None
    assert line.store_snapshot == "REWE"
    assert line.store_position_snapshot == 0
    assert line.category_snapshot == "Kühlregal"
    assert line.category_position_snapshot == 2
    # Aliase für das Groupable-Protokoll aus app/domain/grouping.py (M7).
    assert line.store_name == "REWE"
    assert line.store_position == 0
    assert line.category_name == "Kühlregal"
    assert line.category_position == 2
    assert line.sort_position == 0


def test_insert_line_without_snapshot_defaults_to_none(connection: sqlite3.Connection) -> None:
    item_id = _create_item(connection, name="Kaffee", position=0)
    list_id = connection.execute(
        "INSERT INTO shopping_lists (status, created_at) VALUES ('open', ?)", (_NOW,)
    ).lastrowid
    assert list_id is not None

    line_id = shopping_lists_repo.insert_line(
        connection,
        list_id=list_id,
        item_id=item_id,
        suggested_qty=1,
        name_snapshot="Kaffee",
        unit_snapshot="Packung",
        position=0,
    )

    line = shopping_lists_repo.get_line(connection, line_id)
    assert line is not None
    assert line.store_snapshot is None
    assert line.category_name is None
