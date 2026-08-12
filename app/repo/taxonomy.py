"""Dünne SQL-Schicht für `categories` und `stores` (L5, ADR 0003).

Beide Tabellen sind schematisch identisch (`id`, `name`, `position`) und unterscheiden sich nur im
Namen — deshalb eine gemeinsame Implementierung, parametrisiert über den Tabellennamen, statt
zweimal denselben Code zu pflegen. Kein Fachwissen, kein ORM: Die Reihenfolge steuert der Aufrufer
(`app/web/taxonomy.py`), hier steht nur Lesen/Schreiben.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from app.db import transaction

TableName = Literal["categories", "stores"]

# `items` verweist mit einer eigenen Spalte je Tabelle darauf — ohne `ON DELETE` (docs/PLAN.md §3),
# ein Löschversuch bei noch zugeordneten Artikeln liefe also in einen `IntegrityError`. Die Web-
# Schicht prüft deshalb vorher über `count_assigned_items` (M7, Frage 3 der Fragerunde).
_ITEM_FOREIGN_KEY_COLUMN: dict[TableName, str] = {
    "categories": "category_id",
    "stores": "store_id",
}


@dataclass(frozen=True)
class TaxonomyRow:
    id: int
    name: str
    position: int


def _row_to_taxonomy(row: sqlite3.Row) -> TaxonomyRow:
    return TaxonomyRow(id=row["id"], name=row["name"], position=row["position"])


def list_all(connection: sqlite3.Connection, table: TableName) -> list[TaxonomyRow]:
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY position, id").fetchall()
    return [_row_to_taxonomy(row) for row in rows]


def get_by_id(
    connection: sqlite3.Connection, table: TableName, entry_id: int
) -> TaxonomyRow | None:
    row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_taxonomy(row) if row is not None else None


def next_position(connection: sqlite3.Connection, table: TableName) -> int:
    """Nächste freie Position für einen neuen Eintrag (nach dem Muster von `items_repo`)."""
    row = connection.execute(
        f"SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM {table}"
    )
    return int(row.fetchone()["next_position"])


def insert(connection: sqlite3.Connection, table: TableName, *, name: str, position: int) -> int:
    cursor = connection.execute(
        f"INSERT INTO {table} (name, position) VALUES (?, ?)", (name, position)
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def rename(connection: sqlite3.Connection, table: TableName, entry_id: int, *, name: str) -> None:
    connection.execute(f"UPDATE {table} SET name = ? WHERE id = ?", (name, entry_id))


def count_assigned_items(connection: sqlite3.Connection, table: TableName, entry_id: int) -> int:
    """Wie viele Artikel — archiviert eingeschlossen — hängen noch an diesem Eintrag?

    Archivierte zählen mit: Sie tragen ihre `category_id`/`store_id` weiter, und ein Löschen
    würde sonst am `IntegrityError` der Fremdschlüssel-Spalte scheitern, statt an der
    verständlichen Meldung, die diese Zählung ermöglicht.
    """
    column = _ITEM_FOREIGN_KEY_COLUMN[table]
    row = connection.execute(
        f"SELECT COUNT(*) AS n FROM items WHERE {column} = ?", (entry_id,)
    ).fetchone()
    return int(row["n"])


def delete(connection: sqlite3.Connection, table: TableName, entry_id: int) -> None:
    connection.execute(f"DELETE FROM {table} WHERE id = ?", (entry_id,))


def swap_positions(
    connection: sqlite3.Connection,
    table: TableName,
    *,
    first_id: int,
    first_position: int,
    second_id: int,
    second_position: int,
) -> None:
    """Vertauscht die `position` zweier Einträge — der Kern von Hoch/Runter (§7).

    Der Aufrufer übergibt beide aktuellen Positionen (er hat sie ohnehin gerade über `list_all`
    gelesen, um die Nachbarn zu bestimmen). Zwei einfache `UPDATE`-Anweisungen mit Literalwerten
    statt einer selbstbezüglichen Unterabfrage: SQLite wertet Unterabfragen auf derselben Tabelle
    innerhalb einer `UPDATE`-Anweisung zeilenweise aus und kann dabei bereits geänderte Zeilen
    sehen — ein `CASE`-Tausch über eine Unterabfrage auf sich selbst ist deshalb nicht sicher.
    """
    with transaction(connection):
        connection.execute(
            f"UPDATE {table} SET position = ? WHERE id = ?", (second_position, first_id)
        )
        connection.execute(
            f"UPDATE {table} SET position = ? WHERE id = ?", (first_position, second_id)
        )
