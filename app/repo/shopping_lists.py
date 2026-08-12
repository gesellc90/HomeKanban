"""Dünne SQL-Schicht für `shopping_lists`/`shopping_list_lines` (L5, ADR 0003).

Kein Fachwissen — der Abgleich entscheidet in `app/domain/shopping.py`, die Transaktionsführung
liegt in `app/services/shopping.py`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

STATUS_OPEN = "open"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"


@dataclass(frozen=True)
class ShoppingListRow:
    id: int
    status: str
    created_at: str
    closed_at: str | None
    exported_at: str | None
    export_count: int


@dataclass(frozen=True)
class ShoppingListLineRow:
    id: int
    list_id: int
    item_id: int
    suggested_qty: int
    purchased_qty: int | None
    name_snapshot: str
    unit_snapshot: str
    position: int
    checked_at: str | None
    dropped_at: str | None
    store_snapshot: str | None = None
    store_position_snapshot: int | None = None
    category_snapshot: str | None = None
    category_position_snapshot: int | None = None

    @property
    def is_checked(self) -> bool:
        return self.checked_at is not None

    @property
    def is_dropped(self) -> bool:
        return self.dropped_at is not None

    @property
    def is_open(self) -> bool:
        """Offen = weder abgehakt noch verworfen — das sind die Positionen im Export."""
        return not self.is_checked and not self.is_dropped

    # Aliase auf die Laden-/Kategorie-Schnappschussfelder, damit eine `ShoppingListLineRow` direkt
    # das `Groupable`-Protokoll aus `app/domain/grouping.py` erfüllt (M7, §7/§9) — ohne dass die
    # Web-/API-Schicht dafür ein eigenes Zwischenobjekt bauen muss.

    @property
    def store_name(self) -> str | None:
        return self.store_snapshot

    @property
    def store_position(self) -> int | None:
        return self.store_position_snapshot

    @property
    def category_name(self) -> str | None:
        return self.category_snapshot

    @property
    def category_position(self) -> int | None:
        return self.category_position_snapshot

    @property
    def sort_position(self) -> int:
        return self.position


def _row_to_list(row: sqlite3.Row) -> ShoppingListRow:
    return ShoppingListRow(
        id=row["id"],
        status=row["status"],
        created_at=row["created_at"],
        closed_at=row["closed_at"],
        exported_at=row["exported_at"],
        export_count=row["export_count"],
    )


def _row_to_line(row: sqlite3.Row) -> ShoppingListLineRow:
    return ShoppingListLineRow(
        id=row["id"],
        list_id=row["list_id"],
        item_id=row["item_id"],
        suggested_qty=row["suggested_qty"],
        purchased_qty=row["purchased_qty"],
        name_snapshot=row["name_snapshot"],
        unit_snapshot=row["unit_snapshot"],
        position=row["position"],
        checked_at=row["checked_at"],
        dropped_at=row["dropped_at"],
        store_snapshot=row["store_snapshot"],
        store_position_snapshot=row["store_position_snapshot"],
        category_snapshot=row["category_snapshot"],
        category_position_snapshot=row["category_position_snapshot"],
    )


def has_open_unchecked_line(connection: sqlite3.Connection, item_id: int) -> bool:
    """Ob eine offene, nicht abgehakte und nicht verworfene Position für den Artikel existiert."""
    row = connection.execute(
        """
        SELECT 1
        FROM shopping_list_lines l
        JOIN shopping_lists s ON s.id = l.list_id
        WHERE l.item_id = ?
          AND s.status = 'open'
          AND l.dropped_at IS NULL
          AND l.checked_at IS NULL
        LIMIT 1
        """,
        (item_id,),
    ).fetchone()
    return row is not None


def open_unchecked_item_ids(connection: sqlite3.Connection, item_ids: Iterable[int]) -> set[int]:
    """Sammelabfrage für das Board: welche der übergebenen Artikel haben eine offene, nicht
    abgehakte Position? Ein Aufruf für beliebig viele Artikel statt einer je Artikel, damit das
    Board mit zwei Abfragen auskommt (docs/PLAN.md M2)."""
    ids = list(item_ids)
    if not ids:
        return set()

    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"""
        SELECT DISTINCT l.item_id AS item_id
        FROM shopping_list_lines l
        JOIN shopping_lists s ON s.id = l.list_id
        WHERE s.status = 'open'
          AND l.dropped_at IS NULL
          AND l.checked_at IS NULL
          AND l.item_id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    return {int(row["item_id"]) for row in rows}


# --- Listen ----------------------------------------------------------------------------------


def get_open_list(connection: sqlite3.Connection) -> ShoppingListRow | None:
    """Die eine offene Liste, falls es sie gibt (`ux_shopping_lists_one_open`, §3)."""
    row = connection.execute(
        "SELECT * FROM shopping_lists WHERE status = 'open' LIMIT 1"
    ).fetchone()
    return _row_to_list(row) if row is not None else None


def get_list(connection: sqlite3.Connection, list_id: int) -> ShoppingListRow | None:
    row = connection.execute("SELECT * FROM shopping_lists WHERE id = ?", (list_id,)).fetchone()
    return _row_to_list(row) if row is not None else None


def insert_list(connection: sqlite3.Connection, *, created_at: str) -> int:
    cursor = connection.execute(
        "INSERT INTO shopping_lists (status, created_at, export_count) VALUES (?, ?, 0)",
        (STATUS_OPEN, created_at),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def close_list(connection: sqlite3.Connection, list_id: int, *, status: str, closed_at: str) -> int:
    """Schließt die Liste. Der `WHERE status = 'open'` ist der eigentliche Schutz gegen zweimaliges
    Abschließen: `rowcount == 0` heißt, dass jemand anders schneller war."""
    cursor = connection.execute(
        "UPDATE shopping_lists SET status = ?, closed_at = ? WHERE id = ? AND status = 'open'",
        (status, closed_at, list_id),
    )
    return cursor.rowcount


def mark_exported(connection: sqlite3.Connection, list_id: int, *, exported_at: str) -> None:
    connection.execute(
        "UPDATE shopping_lists SET exported_at = ?, export_count = export_count + 1 WHERE id = ?",
        (exported_at, list_id),
    )


# --- Positionen ------------------------------------------------------------------------------


def list_lines(
    connection: sqlite3.Connection, list_id: int, *, include_dropped: bool = True
) -> list[ShoppingListLineRow]:
    condition = "" if include_dropped else " AND dropped_at IS NULL"
    rows = connection.execute(
        f"SELECT * FROM shopping_list_lines WHERE list_id = ?{condition} ORDER BY position, id",
        (list_id,),
    ).fetchall()
    return [_row_to_line(row) for row in rows]


def get_line(connection: sqlite3.Connection, line_id: int) -> ShoppingListLineRow | None:
    row = connection.execute(
        "SELECT * FROM shopping_list_lines WHERE id = ?", (line_id,)
    ).fetchone()
    return _row_to_line(row) if row is not None else None


def insert_line(
    connection: sqlite3.Connection,
    *,
    list_id: int,
    item_id: int,
    suggested_qty: int,
    name_snapshot: str,
    unit_snapshot: str,
    position: int,
    store_snapshot: str | None = None,
    store_position_snapshot: int | None = None,
    category_snapshot: str | None = None,
    category_position_snapshot: int | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO shopping_list_lines (
            list_id, item_id, suggested_qty, name_snapshot, unit_snapshot, position,
            store_snapshot, store_position_snapshot, category_snapshot,
            category_position_snapshot
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            list_id,
            item_id,
            suggested_qty,
            name_snapshot,
            unit_snapshot,
            position,
            store_snapshot,
            store_position_snapshot,
            category_snapshot,
            category_position_snapshot,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def next_line_position(connection: sqlite3.Connection, list_id: int) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_position "
        "FROM shopping_list_lines WHERE list_id = ?",
        (list_id,),
    ).fetchone()
    return int(row["next_position"])


def update_suggested_qty(
    connection: sqlite3.Connection, line_id: int, *, suggested_qty: int
) -> None:
    connection.execute(
        "UPDATE shopping_list_lines SET suggested_qty = ? WHERE id = ?", (suggested_qty, line_id)
    )


def drop_line(connection: sqlite3.Connection, line_id: int, *, dropped_at: str) -> None:
    connection.execute(
        "UPDATE shopping_list_lines SET dropped_at = ? WHERE id = ? AND dropped_at IS NULL",
        (dropped_at, line_id),
    )


def drop_open_lines(connection: sqlite3.Connection, list_id: int, *, dropped_at: str) -> int:
    """Verwirft alle offenen Positionen der Liste — der Kern von „Einkauf abschließen“ (§6).
    Abgehakte Positionen bleiben stehen, sie sind ja gebucht."""
    cursor = connection.execute(
        """
        UPDATE shopping_list_lines SET dropped_at = ?
        WHERE list_id = ? AND dropped_at IS NULL AND checked_at IS NULL
        """,
        (dropped_at, list_id),
    )
    return cursor.rowcount


def mark_checked(
    connection: sqlite3.Connection, line_id: int, *, checked_at: str, purchased_qty: int
) -> int:
    """Hakt eine Position ab und liefert die Zahl der geänderten Zeilen.

    `WHERE checked_at IS NULL AND dropped_at IS NULL` ist bewusst Teil der Anweisung und nicht
    nur eine vorherige Prüfung: Die Bedingung wird innerhalb derselben Transaktion ausgewertet wie
    die Zugangsbuchung, ist also gegen zwei gleichzeitige Abhaken-Anfragen dicht (R7). `rowcount
    == 0` heißt „war schon abgehakt oder verworfen“ — der Aufrufer bricht dann ab, ohne zu buchen.
    """
    cursor = connection.execute(
        """
        UPDATE shopping_list_lines SET checked_at = ?, purchased_qty = ?
        WHERE id = ? AND checked_at IS NULL AND dropped_at IS NULL
        """,
        (checked_at, purchased_qty, line_id),
    )
    return cursor.rowcount


def clear_checked(connection: sqlite3.Connection, line_id: int) -> int:
    """Nimmt das Abhaken zurück („doch nicht gekauft“, §6)."""
    cursor = connection.execute(
        """
        UPDATE shopping_list_lines SET checked_at = NULL, purchased_qty = NULL
        WHERE id = ? AND checked_at IS NOT NULL
        """,
        (line_id,),
    )
    return cursor.rowcount
