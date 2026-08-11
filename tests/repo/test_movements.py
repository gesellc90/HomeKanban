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
