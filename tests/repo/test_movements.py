from __future__ import annotations

import sqlite3

from app.repo import movements as movements_repo
from app.services import stock


def test_no_violations_on_healthy_ledger(connection: sqlite3.Connection) -> None:
    item_id = stock.create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        stock=3,
        reorder_level=1,
        target_stock=5,
        position=0,
    )
    stock.withdraw(connection, item_id=item_id, quantity=1, source="qr")

    assert movements_repo.find_ledger_invariant_violations(connection) == []


def test_detects_mismatch_between_ledger_sum_and_cached_stock(
    connection: sqlite3.Connection,
) -> None:
    item_id = stock.create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        stock=3,
        reorder_level=1,
        target_stock=5,
        position=0,
    )
    # Direkter Schreibzugriff an den Services vorbei, um eine Inkonsistenz zu simulieren —
    # genau das, was die Invariante in der Produktion erkennen soll.
    connection.execute("UPDATE items SET stock = 99 WHERE id = ?", (item_id,))

    assert movements_repo.find_ledger_invariant_violations(connection) == [item_id]


def test_list_for_item_returns_newest_first_and_respects_limit(
    connection: sqlite3.Connection,
) -> None:
    item_id = stock.create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        stock=3,
        reorder_level=1,
        target_stock=5,
        position=0,
    )
    stock.withdraw(connection, item_id=item_id, quantity=1, source="qr")
    stock.restock(connection, item_id=item_id, quantity=2, source="board")

    movements = movements_repo.list_for_item(connection, item_id, limit=2)

    assert [m.kind for m in movements] == ["restock", "withdrawal"]


def test_get_by_idempotency_key_finds_the_matching_movement(
    connection: sqlite3.Connection,
) -> None:
    item_id = stock.create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        stock=3,
        reorder_level=1,
        target_stock=5,
        position=0,
    )
    movement_id = stock.withdraw(
        connection, item_id=item_id, quantity=1, source="qr", idempotency_key="scan-1"
    )

    found = movements_repo.get_by_idempotency_key(connection, "scan-1")

    assert found is not None
    assert found.id == movement_id


def test_get_by_idempotency_key_returns_none_when_unknown(
    connection: sqlite3.Connection,
) -> None:
    assert movements_repo.get_by_idempotency_key(connection, "unbekannt") is None


def test_list_for_item_only_returns_movements_for_that_item(
    connection: sqlite3.Connection,
) -> None:
    item_id = stock.create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        stock=1,
        reorder_level=0,
        target_stock=1,
        position=0,
    )
    other_id = stock.create_item(
        connection, name="Tee", unit="Packung", stock=1, reorder_level=0, target_stock=1, position=1
    )

    movements = movements_repo.list_for_item(connection, item_id)

    assert {m.item_id for m in movements} == {item_id}
    assert other_id not in {m.item_id for m in movements}
