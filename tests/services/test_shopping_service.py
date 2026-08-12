"""Dienst-Ebene der Einkaufsliste: Abgleich, Abhaken, Zurücknehmen, Abschließen (§6, §11)."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from app.db import connect
from app.domain.status import ItemStatus, derive_status
from app.migrate import migrate
from app.repo import items as items_repo
from app.repo import movements as movements_repo
from app.repo import shopping_lists as lists_repo
from app.repo import taxonomy as taxonomy_repo
from app.services import shopping, stock

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def _create_item(
    connection: sqlite3.Connection,
    *,
    name: str = "Klopapier",
    unit: str = "Rolle",
    initial_stock: int = 0,
    reorder_level: int = 1,
    target_stock: int = 10,
    pack_size: int = 10,
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


def _status(connection: sqlite3.Connection, item_id: int) -> ItemStatus:
    item = items_repo.get_by_id(connection, item_id)
    assert item is not None
    return derive_status(
        stock=item.stock,
        reorder_level=item.reorder_level,
        has_open_list_line=lists_repo.has_open_unchecked_line(connection, item_id),
    )


def _stock(connection: sqlite3.Connection, item_id: int) -> int:
    item = items_repo.get_by_id(connection, item_id)
    assert item is not None
    return item.stock


def _open_lines(
    connection: sqlite3.Connection, list_id: int
) -> list[lists_repo.ShoppingListLineRow]:
    return [line for line in lists_repo.list_lines(connection, list_id) if line.is_open]


def _assert_ledger_invariant(connection: sqlite3.Connection) -> None:
    assert movements_repo.find_ledger_invariant_violations(connection) == []


# --- Erzeugen und Abgleichen -------------------------------------------------------------------


def test_creating_a_list_collects_everything_in_reorder(connection: sqlite3.Connection) -> None:
    _create_item(connection, name="Klopapier", initial_stock=0)
    _create_item(connection, name="Genug da", initial_stock=9, reorder_level=1, position=1)

    list_row, plan = shopping.create_or_reconcile_list(connection)

    assert list_row.status == "open"
    assert len(plan.to_append) == 1
    lines = _open_lines(connection, list_row.id)
    assert [line.name_snapshot for line in lines] == ["Klopapier"]
    assert lines[0].suggested_qty == 10


def test_second_call_reconciles_instead_of_creating_a_second_list(
    connection: sqlite3.Connection,
) -> None:
    """§6: Es gibt nie zwei konkurrierende Listen, sondern eine, die den aktuellen Bedarf zeigt."""
    first, _ = shopping.create_or_reconcile_list(connection)
    _create_item(connection, name="Später dazugekommen", initial_stock=0)

    second, plan = shopping.create_or_reconcile_list(connection)

    assert second.id == first.id
    assert connection.execute("SELECT COUNT(*) FROM shopping_lists").fetchone()[0] == 1
    assert len(plan.to_append) == 1


def test_item_back_above_threshold_is_dropped_from_the_open_list(
    connection: sqlite3.Connection,
) -> None:
    """Szenario 4: spontan mitgebracht — die Position verschwindet von selbst."""
    item_id = _create_item(connection, initial_stock=0)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    assert _status(connection, item_id) is ItemStatus.ON_LIST

    stock.apply_inventory(connection, item_id=item_id, expected_stock=0, actual_stock=10)
    shopping.reconcile(connection, list_row.id)

    assert _open_lines(connection, list_row.id) == []
    assert _status(connection, item_id) is ItemStatus.OK


def test_reconcile_recalculates_quantities_of_open_lines(connection: sqlite3.Connection) -> None:
    item_id = _create_item(
        connection, initial_stock=1, reorder_level=5, target_stock=6, pack_size=1
    )
    list_row, _ = shopping.create_or_reconcile_list(connection)
    assert _open_lines(connection, list_row.id)[0].suggested_qty == 5

    stock.withdraw(connection, item_id=item_id, quantity=1, source="qr")
    shopping.reconcile(connection, list_row.id)

    assert _open_lines(connection, list_row.id)[0].suggested_qty == 6


def test_two_concurrent_creations_produce_exactly_one_list() -> None:
    """`ux_shopping_lists_one_open` ist die eigentliche Garantie (ADR 0005) — zwei echte
    Verbindungen, kein gemeinsamer Prozess-Lock in der Datenbank."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "homekanban.db"
        setup = connect(db_path)
        migrate(setup, MIGRATIONS_DIR)
        _create_item(setup, initial_stock=0)
        setup.close()

        connections = [connect(db_path) for _ in range(2)]
        barrier = threading.Barrier(len(connections))
        errors: list[BaseException] = []

        def create(conn: sqlite3.Connection) -> None:
            try:
                barrier.wait()
                shopping.create_or_reconcile_list(conn)
            except BaseException as error:  # noqa: BLE001 — im Test bewusst alles einsammeln
                errors.append(error)

        threads = [threading.Thread(target=create, args=(conn,)) for conn in connections]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        checker = connect(db_path)
        assert checker.execute("SELECT COUNT(*) FROM shopping_lists").fetchone()[0] == 1
        # Und genau eine Position je Artikel, nicht zwei.
        assert checker.execute("SELECT COUNT(*) FROM shopping_list_lines").fetchone()[0] == 1
        checker.close()
        for conn in connections:
            conn.close()


# --- Abhaken -----------------------------------------------------------------------------------


def test_check_without_quantity_sets_stock_to_target(connection: sqlite3.Connection) -> None:
    item_id = _create_item(connection, initial_stock=0, target_stock=10, pack_size=10)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]

    result = shopping.check_line(connection, list_id=list_row.id, line_id=line.id)

    assert _stock(connection, item_id) == 10
    assert result.purchased_qty == 10
    movement = movements_repo.get_by_id(connection, result.movement_id or 0)
    assert movement is not None
    assert movement.kind == "restock"
    assert movement.source == "shopping_list"
    assert movement.line_id == line.id
    assert movement.delta == 10
    _assert_ledger_invariant(connection)


def test_check_without_quantity_bridges_only_the_gap_to_target(
    connection: sqlite3.Connection,
) -> None:
    """„Auf `target_stock` setzen“ ist nicht „`suggested_qty` addieren“.

    Der Bestand ist zwischenzeitlich auf 4 gestiegen; die vorgeschlagene Menge war 10. Gebucht
    werden 6, nicht 10 — sonst stünden am Ende 14 Rollen im Schrank.
    """
    item_id = _create_item(connection, initial_stock=0, target_stock=10, pack_size=10)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    stock.apply_inventory(connection, item_id=item_id, expected_stock=0, actual_stock=4)

    shopping.check_line(connection, list_id=list_row.id, line_id=line.id)

    assert _stock(connection, item_id) == 10
    _assert_ledger_invariant(connection)


def test_check_with_quantity_adds_to_stock(connection: sqlite3.Connection) -> None:
    item_id = _create_item(
        connection, initial_stock=2, reorder_level=3, target_stock=8, pack_size=1
    )
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]

    result = shopping.check_line(connection, list_id=list_row.id, line_id=line.id, purchased_qty=3)

    assert _stock(connection, item_id) == 5  # 2 + 3, nicht auf 8 gesetzt
    assert result.purchased_qty == 3
    _assert_ledger_invariant(connection)


def test_check_without_quantity_books_nothing_when_stock_already_at_target(
    connection: sqlite3.Connection,
) -> None:
    """Randfall: `restock()` lehnt `quantity <= 0` ab — eine 500er-Seite wäre keine Antwort."""
    item_id = _create_item(connection, initial_stock=0, target_stock=10, pack_size=10)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    stock.apply_inventory(connection, item_id=item_id, expected_stock=0, actual_stock=12)

    result = shopping.check_line(connection, list_id=list_row.id, line_id=line.id)

    assert result.movement_id is None
    assert result.purchased_qty == 0
    assert result.note is not None
    assert _stock(connection, item_id) == 12
    checked = lists_repo.get_line(connection, line.id)
    assert checked is not None and checked.is_checked
    _assert_ledger_invariant(connection)


def test_checking_twice_books_exactly_once(connection: sqlite3.Connection) -> None:
    item_id = _create_item(connection, initial_stock=0, target_stock=10, pack_size=10)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]

    shopping.check_line(connection, list_id=list_row.id, line_id=line.id)
    with pytest.raises(shopping.LineAlreadyCheckedError):
        shopping.check_line(connection, list_id=list_row.id, line_id=line.id)

    assert _stock(connection, item_id) == 10
    restocks = connection.execute(
        "SELECT COUNT(*) FROM movements WHERE kind = 'restock' AND item_id = ?", (item_id,)
    ).fetchone()[0]
    assert restocks == 1
    _assert_ledger_invariant(connection)


def test_checking_a_dropped_line_is_refused(connection: sqlite3.Connection) -> None:
    item_id = _create_item(connection, initial_stock=0)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    stock.apply_inventory(connection, item_id=item_id, expected_stock=0, actual_stock=10)
    shopping.reconcile(connection, list_row.id)

    with pytest.raises(shopping.LineDroppedError):
        shopping.check_line(connection, list_id=list_row.id, line_id=line.id)


def test_checking_a_line_of_another_list_is_refused(connection: sqlite3.Connection) -> None:
    """Eine Zeilen-ID aus einer alten Liste darf nicht über die aktuelle Liste buchbar sein."""
    _create_item(connection, initial_stock=0)
    old_list, _ = shopping.create_or_reconcile_list(connection)
    old_line = _open_lines(connection, old_list.id)[0]
    shopping.complete_list(connection, old_list.id)
    new_list, _ = shopping.create_or_reconcile_list(connection)

    with pytest.raises(shopping.LineNotFoundError):
        shopping.check_line(connection, list_id=new_list.id, line_id=old_line.id)


def test_checking_against_an_unknown_list_is_refused(connection: sqlite3.Connection) -> None:
    _create_item(connection, initial_stock=0)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]

    with pytest.raises(shopping.ShoppingListNotFoundError):
        shopping.check_line(connection, list_id=list_row.id + 999, line_id=line.id)


@pytest.mark.parametrize("quantity", [0, -3, shopping.MAX_PURCHASED_QTY + 1])
def test_nonsensical_quantities_are_refused(connection: sqlite3.Connection, quantity: int) -> None:
    item_id = _create_item(connection, initial_stock=0)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]

    with pytest.raises(shopping.InvalidQuantityError):
        shopping.check_line(
            connection, list_id=list_row.id, line_id=line.id, purchased_qty=quantity
        )

    assert _stock(connection, item_id) == 0
    unchanged = lists_repo.get_line(connection, line.id)
    assert unchanged is not None and not unchanged.is_checked


def test_check_all_open_lines_books_every_line(connection: sqlite3.Connection) -> None:
    """O1: „Alles gekauft“ ist der Standardweg nach dem Einkauf (R2)."""
    first = _create_item(connection, name="Klopapier", initial_stock=0, position=0)
    second = _create_item(
        connection,
        name="Kaffee",
        initial_stock=1,
        reorder_level=2,
        target_stock=4,
        pack_size=1,
        position=1,
    )
    list_row, _ = shopping.create_or_reconcile_list(connection)

    results = shopping.check_all_open_lines(connection, list_row.id)

    assert len(results) == 2
    assert _stock(connection, first) == 10
    assert _stock(connection, second) == 4
    assert _open_lines(connection, list_row.id) == []
    _assert_ledger_invariant(connection)


def test_check_all_skips_already_checked_lines(connection: sqlite3.Connection) -> None:
    item_id = _create_item(connection, initial_stock=0)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    shopping.check_line(connection, list_id=list_row.id, line_id=line.id)

    assert shopping.check_all_open_lines(connection, list_row.id) == []
    assert _stock(connection, item_id) == 10


# --- Regel 5: Teilkauf -------------------------------------------------------------------------


def test_partial_purchase_falls_straight_back_to_reorder(connection: sqlite3.Connection) -> None:
    """Pflichtfall 5 (§11) und Szenario 2: nur eine statt zwei Packungen Kaffee bekommen."""
    item_id = _create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        initial_stock=0,
        reorder_level=1,
        target_stock=2,
        pack_size=1,
    )
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    assert line.suggested_qty == 2

    shopping.check_line(connection, list_id=list_row.id, line_id=line.id, purchased_qty=1)

    assert _stock(connection, item_id) == 1
    assert _status(connection, item_id) is ItemStatus.REORDER
    _assert_ledger_invariant(connection)


def test_remainder_comes_with_the_next_list_not_this_one(connection: sqlite3.Connection) -> None:
    """Der mit dem Nutzer entschiedene Weg zur Restmenge (§4 Regel 5).

    In derselben Liste bekommt der teilweise gekaufte Artikel **keine** zweite Position — das
    verbietet `ux_shopping_list_lines_active`. Nach dem Abschließen ist er sofort wieder dabei.
    """
    item_id = _create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        initial_stock=0,
        reorder_level=1,
        target_stock=2,
        pack_size=1,
    )
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    shopping.check_line(connection, list_id=list_row.id, line_id=line.id, purchased_qty=1)

    plan = shopping.reconcile(connection, list_row.id)
    assert plan.is_empty  # keine zweite Position in derselben Liste

    shopping.complete_list(connection, list_row.id)
    next_list, next_plan = shopping.create_or_reconcile_list(connection)

    assert next_list.id != list_row.id
    assert [line.item_id for line in _open_lines(connection, next_list.id)] == [item_id]
    assert next_plan.to_append[0].suggested_qty == 1  # der Rest


# --- Zurücknehmen ------------------------------------------------------------------------------


def test_uncheck_books_the_reversal_and_clears_checked_at(
    connection: sqlite3.Connection,
) -> None:
    item_id = _create_item(connection, initial_stock=0, target_stock=10, pack_size=10)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    result = shopping.check_line(connection, list_id=list_row.id, line_id=line.id)

    reversal_id = shopping.uncheck_line(connection, list_id=list_row.id, line_id=line.id)

    assert reversal_id is not None
    reversal = movements_repo.get_by_id(connection, reversal_id)
    assert reversal is not None
    assert reversal.reverts_movement_id == result.movement_id
    assert reversal.delta == -10
    assert _stock(connection, item_id) == 0
    after = lists_repo.get_line(connection, line.id)
    assert after is not None
    assert after.checked_at is None
    assert after.purchased_qty is None
    assert _status(connection, item_id) is ItemStatus.ON_LIST
    _assert_ledger_invariant(connection)


def test_uncheck_is_not_bound_by_the_undo_window(connection: sqlite3.Connection) -> None:
    """„Doch nicht gekauft“ Stunden nach dem Einkauf ist legitim (§5 gilt nur im QR-Flow)."""
    item_id = _create_item(connection, initial_stock=0, target_stock=10, pack_size=10)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    result = shopping.check_line(connection, list_id=list_row.id, line_id=line.id)
    connection.execute(
        "UPDATE movements SET created_at = '2020-01-01T00:00:00.000Z' WHERE id = ?",
        (result.movement_id,),
    )

    assert shopping.uncheck_line(connection, list_id=list_row.id, line_id=line.id) is not None
    assert _stock(connection, item_id) == 0

    # Zum Vergleich: derselbe Zeitabstand wäre über den QR-Weg am Fenster gescheitert.
    aged = stock.restock(connection, item_id=item_id, quantity=1, source="qr")
    connection.execute(
        "UPDATE movements SET created_at = '2020-01-01T00:00:00.000Z' WHERE id = ?", (aged,)
    )
    with pytest.raises(stock.UndoWindowExpiredError):
        stock.undo(connection, movement_id=aged, source="qr", window_minutes=10)


def test_unchecking_twice_is_harmless(connection: sqlite3.Connection) -> None:
    item_id = _create_item(connection, initial_stock=0, target_stock=10, pack_size=10)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    shopping.check_line(connection, list_id=list_row.id, line_id=line.id)
    shopping.uncheck_line(connection, list_id=list_row.id, line_id=line.id)

    assert shopping.uncheck_line(connection, list_id=list_row.id, line_id=line.id) is None
    assert _stock(connection, item_id) == 0
    _assert_ledger_invariant(connection)


def test_check_uncheck_check_books_again(connection: sqlite3.Connection) -> None:
    """Ein aus der `line_id` abgeleiteter Idempotenzschlüssel würde hier die zweite, völlig
    legitime Buchung verschlucken — deshalb schützt das bedingte UPDATE, nicht ein Schlüssel."""
    item_id = _create_item(connection, initial_stock=0, target_stock=10, pack_size=10)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]

    shopping.check_line(connection, list_id=list_row.id, line_id=line.id)
    shopping.uncheck_line(connection, list_id=list_row.id, line_id=line.id)
    shopping.check_line(connection, list_id=list_row.id, line_id=line.id)

    assert _stock(connection, item_id) == 10
    _assert_ledger_invariant(connection)


# --- Abschließen -------------------------------------------------------------------------------


def test_completing_a_half_done_list_leaves_open_items_in_reorder(
    connection: sqlite3.Connection,
) -> None:
    """Definition of Done für M4 (§9)."""
    bought = _create_item(connection, name="Klopapier", initial_stock=0, position=0)
    forgotten = _create_item(
        connection,
        name="Kaffee",
        initial_stock=0,
        reorder_level=1,
        target_stock=4,
        pack_size=1,
        position=1,
    )
    list_row, _ = shopping.create_or_reconcile_list(connection)
    first_line = _open_lines(connection, list_row.id)[0]
    shopping.check_line(connection, list_id=list_row.id, line_id=first_line.id)

    dropped = shopping.complete_list(connection, list_row.id)

    assert dropped == 1
    closed = lists_repo.get_list(connection, list_row.id)
    assert closed is not None
    assert closed.status == "done"
    assert closed.closed_at is not None
    assert _status(connection, bought) is ItemStatus.OK
    assert _status(connection, forgotten) is ItemStatus.REORDER

    # Und beim nächsten Abgleich ist der vergessene Artikel wieder dabei.
    next_list, _ = shopping.create_or_reconcile_list(connection)
    assert [line.item_id for line in _open_lines(connection, next_list.id)] == [forgotten]
    _assert_ledger_invariant(connection)


def test_completing_twice_is_refused(connection: sqlite3.Connection) -> None:
    list_row, _ = shopping.create_or_reconcile_list(connection)
    shopping.complete_list(connection, list_row.id)

    with pytest.raises(shopping.ListClosedError):
        shopping.complete_list(connection, list_row.id)


def test_unknown_list_is_refused(connection: sqlite3.Connection) -> None:
    with pytest.raises(shopping.ShoppingListNotFoundError):
        shopping.complete_list(connection, 4711)


def test_checked_lines_survive_completing(connection: sqlite3.Connection) -> None:
    _create_item(connection, initial_stock=0)
    list_row, _ = shopping.create_or_reconcile_list(connection)
    line = _open_lines(connection, list_row.id)[0]
    shopping.check_line(connection, list_id=list_row.id, line_id=line.id)

    shopping.complete_list(connection, list_row.id)

    after = lists_repo.get_line(connection, line.id)
    assert after is not None
    assert after.is_checked
    assert not after.is_dropped


# --- Journal-Invariante über den ganzen Ablauf --------------------------------------------------


def test_ledger_invariant_holds_across_a_full_shopping_cycle(
    connection: sqlite3.Connection,
) -> None:
    """§11, Pflichtfall 7 — über Erzeugen, Abhaken, Zurücknehmen, Teilabhaken, Abschließen."""
    paper = _create_item(connection, name="Klopapier", initial_stock=0, position=0)
    coffee = _create_item(
        connection,
        name="Kaffee",
        unit="Packung",
        initial_stock=0,
        reorder_level=1,
        target_stock=2,
        pack_size=1,
        position=1,
    )
    tabs = _create_item(
        connection,
        name="Tabs",
        initial_stock=1,
        reorder_level=2,
        target_stock=6,
        pack_size=1,
        position=2,
    )

    list_row, _ = shopping.create_or_reconcile_list(connection)
    lines = {line.item_id: line.id for line in _open_lines(connection, list_row.id)}
    assert set(lines) == {paper, coffee, tabs}

    shopping.check_line(connection, list_id=list_row.id, line_id=lines[paper])
    _assert_ledger_invariant(connection)

    shopping.uncheck_line(connection, list_id=list_row.id, line_id=lines[paper])
    _assert_ledger_invariant(connection)

    shopping.check_line(connection, list_id=list_row.id, line_id=lines[paper])
    shopping.check_line(connection, list_id=list_row.id, line_id=lines[coffee], purchased_qty=1)
    _assert_ledger_invariant(connection)

    shopping.complete_list(connection, list_row.id)
    _assert_ledger_invariant(connection)

    assert _stock(connection, paper) == 10
    assert _stock(connection, coffee) == 1
    assert _stock(connection, tabs) == 1
    assert _status(connection, paper) is ItemStatus.OK
    assert _status(connection, coffee) is ItemStatus.REORDER
    assert _status(connection, tabs) is ItemStatus.REORDER

    next_list, _ = shopping.create_or_reconcile_list(connection)
    assert {line.item_id for line in _open_lines(connection, next_list.id)} == {coffee, tabs}
    _assert_ledger_invariant(connection)


# --- Schnappschuss -----------------------------------------------------------------------------


def test_renaming_an_item_does_not_change_the_open_list(connection: sqlite3.Connection) -> None:
    """§3: Wird ein Artikel umbenannt, während die Liste im Supermarkt offen ist, soll die Liste
    nicht plötzlich anders heißen."""
    item_id = _create_item(connection, name="Klopapier", unit="Rolle", initial_stock=0)
    list_row, _ = shopping.create_or_reconcile_list(connection)

    items_repo.update(
        connection,
        item_id,
        name="Toilettenpapier",
        unit="Packung",
        note=None,
        reorder_level=1,
        target_stock=10,
        pack_size=10,
        category_id=None,
        store_id=None,
        updated_at=stock.utc_now_iso(),
    )
    shopping.reconcile(connection, list_row.id)

    line = _open_lines(connection, list_row.id)[0]
    assert line.name_snapshot == "Klopapier"
    assert line.unit_snapshot == "Rolle"


def test_appending_a_line_freezes_the_items_store_and_category(
    connection: sqlite3.Connection,
) -> None:
    """M7, Frage 1: Laden/Kategorie werden wie Name/Einheit beim Anfügen eingefroren."""
    category_id = taxonomy_repo.insert(connection, "categories", name="Kühlregal", position=0)
    store_id = taxonomy_repo.insert(connection, "stores", name="REWE", position=0)
    item_id = _create_item(connection, name="Milch", initial_stock=0)
    items_repo.update(
        connection,
        item_id,
        name="Milch",
        unit="Rolle",
        note=None,
        reorder_level=1,
        target_stock=10,
        pack_size=10,
        category_id=category_id,
        store_id=store_id,
        updated_at=stock.utc_now_iso(),
    )

    list_row, _ = shopping.create_or_reconcile_list(connection)

    line = _open_lines(connection, list_row.id)[0]
    assert line.store_snapshot == "REWE"
    assert line.store_position_snapshot == 0
    assert line.category_snapshot == "Kühlregal"
    assert line.category_position_snapshot == 0


def test_reassigning_an_item_does_not_change_the_open_lines_group(
    connection: sqlite3.Connection,
) -> None:
    """Der Kern von Frage 1: Ändert sich zu Hause die Laden-Zuordnung, während die Liste im
    Supermarkt offen ist, bleibt die bereits angefügte Position bei ihrer eingefrorenen Gruppe."""
    rewe_id = taxonomy_repo.insert(connection, "stores", name="REWE", position=0)
    aldi_id = taxonomy_repo.insert(connection, "stores", name="Aldi", position=1)
    item_id = _create_item(connection, name="Milch", initial_stock=0)
    items_repo.update(
        connection,
        item_id,
        name="Milch",
        unit="Rolle",
        note=None,
        reorder_level=1,
        target_stock=10,
        pack_size=10,
        category_id=None,
        store_id=rewe_id,
        updated_at=stock.utc_now_iso(),
    )
    list_row, _ = shopping.create_or_reconcile_list(connection)

    items_repo.update(
        connection,
        item_id,
        name="Milch",
        unit="Rolle",
        note=None,
        reorder_level=1,
        target_stock=10,
        pack_size=10,
        category_id=None,
        store_id=aldi_id,
        updated_at=stock.utc_now_iso(),
    )
    shopping.reconcile(connection, list_row.id)

    line = _open_lines(connection, list_row.id)[0]
    assert line.store_snapshot == "REWE"


def test_line_of_item_without_store_or_category_has_no_snapshot(
    connection: sqlite3.Connection,
) -> None:
    """Definition of Done §9 M7: unzugeordnete Artikel verschwinden nicht — sie landen später in
    „Sonstiges“ (app/domain/grouping.py), hier zunächst nur: kein Absturz, keine Fantasiewerte."""
    _create_item(connection, name="Klopapier", initial_stock=0)

    list_row, _ = shopping.create_or_reconcile_list(connection)

    line = _open_lines(connection, list_row.id)[0]
    assert line.store_snapshot is None
    assert line.store_position_snapshot is None
    assert line.category_snapshot is None
    assert line.category_position_snapshot is None
