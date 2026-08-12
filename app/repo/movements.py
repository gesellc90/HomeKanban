"""Dünne SQL-Schicht für `movements`, das append-only Bewegungsjournal (L5, ADR 0003)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class MovementRow:
    id: int
    item_id: int
    kind: str
    delta: int
    stock_after: int
    source: str
    line_id: int | None
    idempotency_key: str | None
    reverts_movement_id: int | None
    note: str | None
    created_at: str


def _row_to_movement(row: sqlite3.Row) -> MovementRow:
    return MovementRow(
        id=row["id"],
        item_id=row["item_id"],
        kind=row["kind"],
        delta=row["delta"],
        stock_after=row["stock_after"],
        source=row["source"],
        line_id=row["line_id"],
        idempotency_key=row["idempotency_key"],
        reverts_movement_id=row["reverts_movement_id"],
        note=row["note"],
        created_at=row["created_at"],
    )


def insert(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    kind: str,
    delta: int,
    stock_after: int,
    source: str,
    line_id: int | None = None,
    idempotency_key: str | None = None,
    reverts_movement_id: int | None = None,
    note: str | None = None,
    created_at: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO movements (
            item_id, kind, delta, stock_after, source, line_id,
            idempotency_key, reverts_movement_id, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            kind,
            delta,
            stock_after,
            source,
            line_id,
            idempotency_key,
            reverts_movement_id,
            note,
            created_at,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def get_by_id(connection: sqlite3.Connection, movement_id: int) -> MovementRow | None:
    row = connection.execute("SELECT * FROM movements WHERE id = ?", (movement_id,)).fetchone()
    return _row_to_movement(row) if row is not None else None


def get_by_idempotency_key(
    connection: sqlite3.Connection, idempotency_key: str
) -> MovementRow | None:
    row = connection.execute(
        "SELECT * FROM movements WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return _row_to_movement(row) if row is not None else None


def find_reversal(connection: sqlite3.Connection, movement_id: int) -> MovementRow | None:
    """Die Gegenbewegung zu `movement_id`, falls sie schon rückgängig gemacht wurde."""
    row = connection.execute(
        "SELECT * FROM movements WHERE reverts_movement_id = ?", (movement_id,)
    ).fetchone()
    return _row_to_movement(row) if row is not None else None


def find_unreverted_for_line(connection: sqlite3.Connection, line_id: int) -> MovementRow | None:
    """Die noch nicht zurückgenommene Buchung zu einer Listenposition (M4, §6).

    Nur eine Buchung kann es zu einem Zeitpunkt geben: Abhaken bucht, Zurücknehmen bucht die
    Gegenbewegung. Nach „abhaken → zurücknehmen → erneut abhaken“ liegen aber mehrere Bewegungen
    an derselben `line_id`; gesucht ist die aktuell gültige. Ausgeschlossen werden deshalb
    Gegenbewegungen selbst (`reverts_movement_id IS NOT NULL`) und bereits zurückgenommene
    Buchungen (der LEFT JOIN findet ihre Gegenbewegung).
    """
    row = connection.execute(
        """
        SELECT m.*
        FROM movements m
        LEFT JOIN movements r ON r.reverts_movement_id = m.id
        WHERE m.line_id = ?
          AND m.reverts_movement_id IS NULL
          AND r.id IS NULL
        ORDER BY m.id DESC
        LIMIT 1
        """,
        (line_id,),
    ).fetchone()
    return _row_to_movement(row) if row is not None else None


def sum_delta_for_item(connection: sqlite3.Connection, item_id: int) -> int:
    row = connection.execute(
        "SELECT COALESCE(SUM(delta), 0) AS total FROM movements WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    return int(row["total"])


def list_for_item(
    connection: sqlite3.Connection, item_id: int, *, limit: int = 20
) -> list[MovementRow]:
    """Verlauf für die Detailseite: neueste zuerst, begrenzt auf `limit` Einträge."""
    rows = connection.execute(
        "SELECT * FROM movements WHERE item_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (item_id, limit),
    ).fetchall()
    return [_row_to_movement(row) for row in rows]


def find_ledger_invariant_violations(connection: sqlite3.Connection) -> list[int]:
    """Item-IDs, bei denen `SUM(movements.delta) != items.stock` gilt (L2, ADR 0002)."""
    rows = connection.execute(
        """
        SELECT i.id AS id
        FROM items i
        LEFT JOIN movements m ON m.item_id = i.id
        GROUP BY i.id, i.stock
        HAVING i.stock != COALESCE(SUM(m.delta), 0)
        """
    ).fetchall()
    return [int(row["id"]) for row in rows]
