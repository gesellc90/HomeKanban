from __future__ import annotations

import random
import sqlite3

import pytest

from app.repo import items as items_repo
from app.repo import movements as movements_repo
from app.services import stock


def _create_item(
    connection: sqlite3.Connection,
    *,
    name: str = "Testartikel",
    unit: str = "Packung",
    initial_stock: int = 5,
    reorder_level: int = 2,
    target_stock: int = 5,
    pack_size: int = 1,
    position: int = 0,
) -> int:
    return stock.create_item(
        connection,
        name=name,
        unit=unit,
        stock=initial_stock,
        reorder_level=reorder_level,
        target_stock=target_stock,
        pack_size=pack_size,
        position=position,
    )


def _sum_delta(connection: sqlite3.Connection, item_id: int) -> int:
    return movements_repo.sum_delta_for_item(connection, item_id)


class TestCreateItem:
    def test_creates_opening_movement_matching_initial_stock(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = _create_item(connection, initial_stock=7)

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 7
        assert item.qr_token
        assert _sum_delta(connection, item_id) == 7

    def test_qr_tokens_are_unique_across_items(self, connection: sqlite3.Connection) -> None:
        first_id = _create_item(connection, name="Artikel A", position=0)
        second_id = _create_item(connection, name="Artikel B", position=1)

        first = items_repo.get_by_id(connection, first_id)
        second = items_repo.get_by_id(connection, second_id)
        assert first is not None
        assert second is not None
        assert first.qr_token != second.qr_token

    def test_negative_initial_stock_is_rejected(self, connection: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            _create_item(connection, initial_stock=-1)

    def test_target_stock_not_greater_than_reorder_level_violates_check(
        self, connection: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            _create_item(connection, reorder_level=5, target_stock=5)


class TestWithdraw:
    def test_reduces_stock_and_records_negative_delta(self, connection: sqlite3.Connection) -> None:
        item_id = _create_item(connection, initial_stock=5)

        movement_id = stock.withdraw(connection, item_id=item_id, quantity=2, source="qr")

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 3
        movement = movements_repo.get_by_id(connection, movement_id)
        assert movement is not None
        assert movement.kind == "withdrawal"
        assert movement.delta == -2
        assert movement.stock_after == 3
        assert _sum_delta(connection, item_id) == 3

    def test_withdrawing_below_zero_is_rejected_by_check_constraint(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = _create_item(connection, initial_stock=1)

        with pytest.raises(sqlite3.IntegrityError):
            stock.withdraw(connection, item_id=item_id, quantity=2, source="qr")

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 1  # Transaktion wurde vollständig zurückgerollt.
        assert _sum_delta(connection, item_id) == 1

    def test_zero_quantity_is_rejected(self, connection: sqlite3.Connection) -> None:
        item_id = _create_item(connection, initial_stock=5)

        with pytest.raises(ValueError):
            stock.withdraw(connection, item_id=item_id, quantity=0, source="qr")

    def test_unknown_item_raises(self, connection: sqlite3.Connection) -> None:
        with pytest.raises(stock.ItemNotFoundError):
            stock.withdraw(connection, item_id=999_999, quantity=1, source="qr")


class TestRestock:
    def test_increases_stock_and_records_positive_delta(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = _create_item(connection, initial_stock=1, reorder_level=1, target_stock=5)

        movement_id = stock.restock(connection, item_id=item_id, quantity=4, source="shopping_list")

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 5
        movement = movements_repo.get_by_id(connection, movement_id)
        assert movement is not None
        assert movement.kind == "restock"
        assert movement.delta == 4
        assert movement.stock_after == 5

    def test_zero_quantity_is_rejected(self, connection: sqlite3.Connection) -> None:
        item_id = _create_item(connection, initial_stock=1)

        with pytest.raises(ValueError):
            stock.restock(connection, item_id=item_id, quantity=0, source="board")


class TestApplyInventory:
    def test_matching_expected_stock_writes_adjustment_with_difference(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = _create_item(connection, initial_stock=3, reorder_level=1, target_stock=5)

        movement_id = stock.apply_inventory(
            connection, item_id=item_id, expected_stock=3, actual_stock=1
        )

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 1
        movement = movements_repo.get_by_id(connection, movement_id)
        assert movement is not None
        assert movement.kind == "adjustment"
        assert movement.delta == -2
        assert movement.stock_after == 1

    def test_matching_expected_stock_can_increase_stock(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = _create_item(connection, initial_stock=1, reorder_level=1, target_stock=5)

        stock.apply_inventory(connection, item_id=item_id, expected_stock=1, actual_stock=3)

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 3

    def test_stale_expected_stock_is_rejected_and_leaves_stock_untouched(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = _create_item(connection, initial_stock=3, reorder_level=1, target_stock=5)
        stock.withdraw(connection, item_id=item_id, quantity=1, source="qr")  # Bestand jetzt: 2

        with pytest.raises(stock.StaleInventoryError):
            stock.apply_inventory(connection, item_id=item_id, expected_stock=3, actual_stock=0)

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 2
        assert _sum_delta(connection, item_id) == 2


class TestUndo:
    def test_reverts_a_withdrawal(self, connection: sqlite3.Connection) -> None:
        item_id = _create_item(connection, initial_stock=5)
        movement_id = stock.withdraw(connection, item_id=item_id, quantity=2, source="qr")

        reversal_id = stock.undo(connection, movement_id=movement_id, source="qr")

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 5
        reversal = movements_repo.get_by_id(connection, reversal_id)
        assert reversal is not None
        assert reversal.delta == 2
        assert reversal.reverts_movement_id == movement_id
        assert _sum_delta(connection, item_id) == 5

    def test_reverts_a_restock(self, connection: sqlite3.Connection) -> None:
        item_id = _create_item(connection, initial_stock=1, reorder_level=1, target_stock=10)
        movement_id = stock.restock(connection, item_id=item_id, quantity=5, source="board")

        stock.undo(connection, movement_id=movement_id, source="board")

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 1

    def test_double_undo_is_rejected(self, connection: sqlite3.Connection) -> None:
        item_id = _create_item(connection, initial_stock=5)
        movement_id = stock.withdraw(connection, item_id=item_id, quantity=2, source="qr")
        stock.undo(connection, movement_id=movement_id, source="qr")

        with pytest.raises(stock.AlreadyRevertedError):
            stock.undo(connection, movement_id=movement_id, source="qr")

        item = items_repo.get_by_id(connection, item_id)
        assert item is not None
        assert item.stock == 5  # unverändert seit der ersten (einzigen) Gegenbuchung

    def test_undo_unknown_movement_raises(self, connection: sqlite3.Connection) -> None:
        with pytest.raises(stock.MovementNotFoundError):
            stock.undo(connection, movement_id=999_999, source="qr")


class TestLedgerInvariant:
    def test_holds_over_random_sequence_of_bookings_across_items(
        self, connection: sqlite3.Connection
    ) -> None:
        rng = random.Random(20260811)
        item_ids = [
            _create_item(
                connection,
                name=f"Artikel {i}",
                initial_stock=rng.randint(0, 20),
                reorder_level=2,
                target_stock=50,
                pack_size=1,
                position=i,
            )
            for i in range(3)
        ]

        for _ in range(300):
            item_id = rng.choice(item_ids)
            item = items_repo.get_by_id(connection, item_id)
            assert item is not None
            action = rng.choice(["withdraw", "restock", "inventory"])

            if action == "withdraw" and item.stock > 0:
                quantity = rng.randint(1, item.stock)
                stock.withdraw(connection, item_id=item_id, quantity=quantity, source="qr")
            elif action == "restock":
                stock.restock(
                    connection, item_id=item_id, quantity=rng.randint(1, 10), source="board"
                )
            elif action == "inventory":
                new_stock = max(0, item.stock + rng.randint(-3, 3))
                stock.apply_inventory(
                    connection,
                    item_id=item_id,
                    expected_stock=item.stock,
                    actual_stock=new_stock,
                )
            # "withdraw" bei stock == 0 wird übersprungen: es gibt nichts zu entnehmen.

        for item_id in item_ids:
            item = items_repo.get_by_id(connection, item_id)
            assert item is not None
            assert _sum_delta(connection, item_id) == item.stock
