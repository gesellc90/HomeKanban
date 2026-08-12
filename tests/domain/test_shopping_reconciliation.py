"""Der Abgleich als reine Entscheidung — tabellengetrieben, ohne Datenbank (docs/PLAN.md §6)."""

from __future__ import annotations

import pytest

from app.domain.shopping import (
    ReconciliationItem,
    ReconciliationLine,
    format_export_line,
    format_export_text,
    plan_reconciliation,
)


def _item(
    item_id: int = 1,
    *,
    name: str = "Klopapier",
    unit: str = "Rolle",
    stock: int = 0,
    reorder_level: int = 1,
    target_stock: int = 10,
    pack_size: int = 10,
) -> ReconciliationItem:
    return ReconciliationItem(
        item_id=item_id,
        name=name,
        unit=unit,
        stock=stock,
        reorder_level=reorder_level,
        target_stock=target_stock,
        pack_size=pack_size,
    )


def _line(
    line_id: int = 100,
    *,
    item_id: int = 1,
    suggested_qty: int = 10,
    is_checked: bool = False,
    is_dropped: bool = False,
) -> ReconciliationLine:
    return ReconciliationLine(
        line_id=line_id,
        item_id=item_id,
        suggested_qty=suggested_qty,
        is_checked=is_checked,
        is_dropped=is_dropped,
    )


# --- Die vier Fälle aus §6 ---------------------------------------------------------------------


def test_case_1_item_below_threshold_without_line_is_appended() -> None:
    plan = plan_reconciliation(items=[_item(stock=0)], lines=[], next_position=0)

    assert len(plan.to_append) == 1
    appended = plan.to_append[0]
    assert appended.item_id == 1
    assert appended.suggested_qty == 10
    assert appended.name_snapshot == "Klopapier"
    assert appended.unit_snapshot == "Rolle"
    assert appended.position == 0
    assert plan.to_drop == ()


def test_case_2_line_whose_item_is_no_longer_below_threshold_is_dropped() -> None:
    """Szenario 4: Jemand bringt spontan Kaffee mit — die Position verschwindet von selbst."""
    plan = plan_reconciliation(
        items=[_item(stock=8, reorder_level=1)], lines=[_line()], next_position=1
    )

    assert plan.to_drop == (100,)
    assert plan.to_append == ()


def test_case_3_checked_line_stays_untouched() -> None:
    """Auch wenn der Artikel wieder über der Schwelle liegt: abgehakt heißt gekauft."""
    plan = plan_reconciliation(
        items=[_item(stock=10, reorder_level=1)],
        lines=[_line(is_checked=True)],
        next_position=1,
    )

    assert plan.to_drop == ()
    assert plan.to_requantify == ()
    assert plan.to_append == ()


def test_case_4_open_line_quantity_is_recalculated() -> None:
    plan = plan_reconciliation(
        items=[_item(stock=0, target_stock=10, pack_size=10)],
        lines=[_line(suggested_qty=4)],
        next_position=1,
    )

    assert len(plan.to_requantify) == 1
    assert plan.to_requantify[0].line_id == 100
    assert plan.to_requantify[0].suggested_qty == 10


def test_unchanged_quantity_produces_no_update() -> None:
    """Kein Schreibzugriff ohne Änderung — die SD-Karte im Pi dankt es (CLAUDE.md §4)."""
    plan = plan_reconciliation(
        items=[_item(stock=0, target_stock=10, pack_size=10)],
        lines=[_line(suggested_qty=10)],
        next_position=1,
    )

    assert plan.to_requantify == ()
    assert plan.is_empty


# --- Der fünfte Fall, den §6 nicht nennt -------------------------------------------------------


def test_line_of_archived_item_is_dropped() -> None:
    """§4 Regel 4: Archivierte Artikel erscheinen nirgends — auch nicht als Karteileiche."""
    plan = plan_reconciliation(items=[], lines=[_line()], next_position=1)

    assert plan.to_drop == (100,)


def test_checked_line_of_archived_item_stays() -> None:
    """Sie ist gebucht; ein Verwerfen würde die Historie der Liste verfälschen."""
    plan = plan_reconciliation(items=[], lines=[_line(is_checked=True)], next_position=1)

    assert plan.to_drop == ()


# --- Regel 5: Teilkauf -------------------------------------------------------------------------


def test_partially_bought_item_gets_no_second_line_in_the_same_list() -> None:
    """Entschieden zu §4 Regel 5: Die Restmenge kommt mit der **nächsten** Liste.

    `ux_shopping_list_lines_active` lässt je Liste nur eine nicht verworfene Position pro Artikel
    zu, und eine abgehakte Position ist nicht verworfen. Ein zweiter Anlauf in derselben Liste
    liefe in einen IntegrityError.
    """
    plan = plan_reconciliation(
        items=[_item(stock=1, reorder_level=1, target_stock=10, pack_size=1)],
        lines=[_line(is_checked=True)],
        next_position=1,
    )

    assert plan.to_append == ()
    assert plan.is_empty


def test_partially_bought_item_returns_once_the_list_is_closed() -> None:
    """Nach dem Abschließen ist die Liste leer — der Artikel steht sofort wieder drin."""
    plan = plan_reconciliation(
        items=[_item(stock=1, reorder_level=1, target_stock=10, pack_size=1)],
        lines=[],
        next_position=0,
    )

    assert len(plan.to_append) == 1
    assert plan.to_append[0].suggested_qty == 9


def test_dropped_line_does_not_block_a_new_one() -> None:
    plan = plan_reconciliation(items=[_item()], lines=[_line(is_dropped=True)], next_position=1)

    assert len(plan.to_append) == 1
    assert plan.to_append[0].position == 1


# --- Zusammenspiel -----------------------------------------------------------------------------


def test_all_four_cases_in_one_pass() -> None:
    items = [
        _item(1, name="Klopapier", stock=0, reorder_level=1, target_stock=10, pack_size=10),
        _item(2, name="Kaffee", stock=9, reorder_level=2, target_stock=6, pack_size=1),
        _item(3, name="Tabs", stock=1, reorder_level=3, target_stock=6, pack_size=1),
        _item(4, name="Seife", stock=0, reorder_level=1, target_stock=4, pack_size=2),
    ]
    lines = [
        _line(101, item_id=1, suggested_qty=10, is_checked=True),  # abgehakt → bleibt
        _line(102, item_id=2, suggested_qty=1),  # nicht mehr unter Schwelle → verworfen
        _line(103, item_id=3, suggested_qty=2),  # offen → Menge neu (5)
    ]

    plan = plan_reconciliation(items=items, lines=lines, next_position=3)

    assert plan.to_drop == (102,)
    assert [(u.line_id, u.suggested_qty) for u in plan.to_requantify] == [(103, 5)]
    assert [(a.item_id, a.suggested_qty, a.position) for a in plan.to_append] == [(4, 4, 3)]


def test_appended_positions_continue_and_follow_item_order() -> None:
    items = [_item(7, name="A", stock=0), _item(3, name="B", stock=0)]

    plan = plan_reconciliation(items=items, lines=[], next_position=5)

    assert [(a.item_id, a.position) for a in plan.to_append] == [(7, 5), (3, 6)]


def test_item_above_threshold_without_line_is_ignored() -> None:
    plan = plan_reconciliation(items=[_item(stock=9, reorder_level=1)], lines=[], next_position=0)

    assert plan.is_empty


def test_item_exactly_on_threshold_is_appended() -> None:
    """§4 Regel 2: die Schwelle selbst zählt schon als Bedarf."""
    plan = plan_reconciliation(
        items=[_item(stock=2, reorder_level=2, target_stock=6, pack_size=1)],
        lines=[],
        next_position=0,
    )

    assert [a.suggested_qty for a in plan.to_append] == [4]


# --- Textformat --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "quantity", "unit", "expected"),
    [
        ("Spülmaschinentabs", 1, "Packung", "Spülmaschinentabs — 1 Packung"),
        ("Klopapier", 10, "Rolle", "Klopapier — 10 Rollen"),
        ("Kaffee", 2, "Packung", "Kaffee — 2 Packungen"),
    ],
)
def test_export_line_matches_the_example_in_the_plan(
    name: str, quantity: int, unit: str, expected: str
) -> None:
    """Zeichengenau, inklusive Geviertstrich mit Leerzeichen (docs/PLAN.md §6)."""
    assert format_export_line(name=name, quantity=quantity, unit=unit) == expected


def test_export_text_joins_without_trailing_newline() -> None:
    """Ein Umbruch am Ende ergäbe im Kurzbefehl einen leeren Punkt in der Notiz."""
    text = format_export_text(["Klopapier — 10 Rollen", "Kaffee — 2 Packungen"])

    assert text == "Klopapier — 10 Rollen\nKaffee — 2 Packungen"


def test_export_text_of_empty_list_is_empty() -> None:
    assert format_export_text([]) == ""
