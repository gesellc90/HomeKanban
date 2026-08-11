"""Dünne SQL-Schicht für `items` (L5, ADR 0003). Kein ORM, kein Fachwissen — nur Lesen/Schreiben."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ItemRow:
    id: int
    name: str
    unit: str
    note: str | None
    stock: int
    reorder_level: int
    target_stock: int
    pack_size: int
    category_id: int | None
    store_id: int | None
    qr_token: str
    position: int
    archived_at: str | None
    created_at: str
    updated_at: str


def _row_to_item(row: sqlite3.Row) -> ItemRow:
    return ItemRow(
        id=row["id"],
        name=row["name"],
        unit=row["unit"],
        note=row["note"],
        stock=row["stock"],
        reorder_level=row["reorder_level"],
        target_stock=row["target_stock"],
        pack_size=row["pack_size"],
        category_id=row["category_id"],
        store_id=row["store_id"],
        qr_token=row["qr_token"],
        position=row["position"],
        archived_at=row["archived_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def insert(
    connection: sqlite3.Connection,
    *,
    name: str,
    unit: str,
    note: str | None,
    stock: int,
    reorder_level: int,
    target_stock: int,
    pack_size: int,
    category_id: int | None,
    store_id: int | None,
    qr_token: str,
    position: int,
    created_at: str,
    updated_at: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO items (
            name, unit, note, stock, reorder_level, target_stock, pack_size,
            category_id, store_id, qr_token, position, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            unit,
            note,
            stock,
            reorder_level,
            target_stock,
            pack_size,
            category_id,
            store_id,
            qr_token,
            position,
            created_at,
            updated_at,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def get_by_id(connection: sqlite3.Connection, item_id: int) -> ItemRow | None:
    row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return _row_to_item(row) if row is not None else None


def get_by_qr_token(connection: sqlite3.Connection, qr_token: str) -> ItemRow | None:
    row = connection.execute("SELECT * FROM items WHERE qr_token = ?", (qr_token,)).fetchone()
    return _row_to_item(row) if row is not None else None


def list_active(connection: sqlite3.Connection) -> list[ItemRow]:
    rows = connection.execute(
        "SELECT * FROM items WHERE archived_at IS NULL ORDER BY position"
    ).fetchall()
    return [_row_to_item(row) for row in rows]


def update_stock(connection: sqlite3.Connection, item_id: int, stock: int, updated_at: str) -> None:
    connection.execute(
        "UPDATE items SET stock = ?, updated_at = ? WHERE id = ?",
        (stock, updated_at, item_id),
    )


def archive(connection: sqlite3.Connection, item_id: int, archived_at: str) -> None:
    connection.execute(
        "UPDATE items SET archived_at = ?, updated_at = ? WHERE id = ?",
        (archived_at, archived_at, item_id),
    )
