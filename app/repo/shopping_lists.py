"""Minimale SQL-Schicht für `shopping_lists`/`shopping_list_lines`.

M1 liefert nur, was die Statusableitung (Regel 3, `app/domain/status.py`) braucht. Abgleich,
Abhaken und Export folgen in M4.
"""

from __future__ import annotations

import sqlite3


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
