"""Minimale SQL-Schicht für `shopping_lists`/`shopping_list_lines`.

M1/M2 liefern nur, was die Statusableitung (Regel 3, `app/domain/status.py`) braucht. Abgleich,
Abhaken und Export folgen in M4.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable


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
