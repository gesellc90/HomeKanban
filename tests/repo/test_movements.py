from __future__ import annotations

import sqlite3

from app.repo import movements as movements_repo
from app.services import stock

_LONG_AGO = "2020-01-01T00:00:00.000Z"
_RECENT = "2026-01-01T00:00:00.000Z"


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


def test_list_for_item_with_limit_none_returns_the_full_journal(
    connection: sqlite3.Connection,
) -> None:
    item_id = stock.create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        stock=5,
        reorder_level=1,
        target_stock=10,
        position=0,
    )
    for _ in range(25):
        stock.withdraw(connection, item_id=item_id, quantity=1, source="qr")
        stock.restock(connection, item_id=item_id, quantity=1, source="board")

    movements = movements_repo.list_for_item(connection, item_id, limit=None)

    assert len(movements) == 51  # 1 opening + 25 * (withdrawal + restock)
    assert movements[0].id > movements[-1].id  # neueste zuerst


class TestUnrevertedWithdrawals:
    """`list_unreverted_withdrawals_for_item_since` / `list_unreverted_withdrawals_since`
    (M8, docs/PLAN.md §9): Grundlage der Verbrauchsrate — Gegenbuchungen und ihre Ursprünge
    dürfen nicht doppelt zählen."""

    def test_excludes_both_sides_of_a_reversed_withdrawal(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = stock.create_item(
            connection,
            name="Kaffee",
            unit="Packung",
            stock=5,
            reorder_level=1,
            target_stock=10,
            position=0,
        )
        reverted_id = stock.withdraw(connection, item_id=item_id, quantity=1, source="qr")
        stock.undo(connection, movement_id=reverted_id, source="qr", window_minutes=10)
        kept_id = stock.withdraw(connection, item_id=item_id, quantity=2, source="qr")

        result = movements_repo.list_unreverted_withdrawals_for_item_since(
            connection, item_id, since=_LONG_AGO
        )

        assert [m.id for m in result] == [kept_id]

    def test_only_withdrawals_are_returned_not_restocks_or_adjustments(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = stock.create_item(
            connection,
            name="Kaffee",
            unit="Packung",
            stock=5,
            reorder_level=1,
            target_stock=10,
            position=0,
        )
        withdrawal_id = stock.withdraw(connection, item_id=item_id, quantity=1, source="qr")
        stock.restock(connection, item_id=item_id, quantity=3, source="board")
        stock.apply_inventory(connection, item_id=item_id, expected_stock=7, actual_stock=6)

        result = movements_repo.list_unreverted_withdrawals_for_item_since(
            connection, item_id, since=_LONG_AGO
        )

        assert [m.id for m in result] == [withdrawal_id]

    def test_since_cutoff_excludes_older_withdrawals(self, connection: sqlite3.Connection) -> None:
        item_id = stock.create_item(
            connection,
            name="Kaffee",
            unit="Packung",
            stock=5,
            reorder_level=1,
            target_stock=10,
            position=0,
        )
        stock.withdraw(connection, item_id=item_id, quantity=1, source="qr", now=_LONG_AGO)
        recent_id = stock.withdraw(
            connection, item_id=item_id, quantity=1, source="qr", now=_RECENT
        )

        result = movements_repo.list_unreverted_withdrawals_for_item_since(
            connection, item_id, since="2025-01-01T00:00:00.000Z"
        )

        assert [m.id for m in result] == [recent_id]

    def test_result_is_ordered_oldest_first(self, connection: sqlite3.Connection) -> None:
        item_id = stock.create_item(
            connection,
            name="Kaffee",
            unit="Packung",
            stock=5,
            reorder_level=1,
            target_stock=10,
            position=0,
        )
        later_id = stock.withdraw(
            connection, item_id=item_id, quantity=1, source="qr", now="2026-06-01T00:00:00.000Z"
        )
        earlier_id = stock.withdraw(
            connection, item_id=item_id, quantity=1, source="qr", now="2026-01-01T00:00:00.000Z"
        )

        result = movements_repo.list_unreverted_withdrawals_for_item_since(
            connection, item_id, since=_LONG_AGO
        )

        assert [m.id for m in result] == [earlier_id, later_id]

    def test_household_wide_query_groups_across_items_in_a_single_call(
        self, connection: sqlite3.Connection
    ) -> None:
        item_a = stock.create_item(
            connection,
            name="Kaffee",
            unit="Packung",
            stock=5,
            reorder_level=1,
            target_stock=10,
            position=0,
        )
        item_b = stock.create_item(
            connection,
            name="Tee",
            unit="Packung",
            stock=5,
            reorder_level=1,
            target_stock=10,
            position=1,
        )
        a_withdrawal = stock.withdraw(connection, item_id=item_a, quantity=1, source="qr")
        b_withdrawal = stock.withdraw(connection, item_id=item_b, quantity=1, source="qr")
        reverted = stock.withdraw(connection, item_id=item_a, quantity=1, source="qr")
        stock.undo(connection, movement_id=reverted, source="qr", window_minutes=10)

        result = movements_repo.list_unreverted_withdrawals_since(connection, since=_LONG_AGO)

        assert {m.id for m in result} == {a_withdrawal, b_withdrawal}
