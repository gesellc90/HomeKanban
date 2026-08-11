"""Anwendungsfälle für Bestandsbuchungen: Entnahme, Zugang, Inventur, Rückgängig.

Journal und `items.stock` werden immer in derselben Transaktion geschrieben (L2, ADR 0002).
Jeder neue Artikel bekommt eine `opening`-Bewegung, damit `SUM(delta) == stock` ausnahmslos
gilt. Die Inventur prüft `expected_stock` optimistisch (L10) und bucht eine `adjustment`-
Bewegung mit der Differenz — nie ein direktes Schreiben auf `items.stock`. Rückgängig ist eine
Gegenbewegung mit `reverts_movement_id`, kein DELETE (L3); der Unique-Index auf dieser Spalte
verhindert doppeltes Rückgängigmachen zusätzlich auf Datenbankebene.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime

from app.db import transaction
from app.repo import items as items_repo
from app.repo import movements as movements_repo


class ItemNotFoundError(Exception):
    """Ein Artikel mit dieser ID existiert nicht."""


class MovementNotFoundError(Exception):
    """Eine Bewegung mit dieser ID existiert nicht."""


class AlreadyRevertedError(Exception):
    """Diese Bewegung wurde bereits rückgängig gemacht."""


class StaleInventoryError(Exception):
    """Der erwartete Bestand stimmt nicht mehr mit dem aktuellen überein (L10)."""

    def __init__(self, *, expected_stock: int, current_stock: int) -> None:
        self.expected_stock = expected_stock
        self.current_stock = current_stock
        super().__init__(
            f"Bestand hat sich zwischenzeitlich geändert: erwartet {expected_stock}, "
            f"tatsächlich {current_stock}"
        )


def utc_now_iso() -> str:
    """Ein einziger Zeitstempel-Helfer: UTC, ISO-8601 mit `Z`, Millisekunden (L9)."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _require_item(connection: sqlite3.Connection, item_id: int) -> items_repo.ItemRow:
    item = items_repo.get_by_id(connection, item_id)
    if item is None:
        raise ItemNotFoundError(f"Artikel {item_id} existiert nicht")
    return item


def create_item(
    connection: sqlite3.Connection,
    *,
    name: str,
    unit: str,
    stock: int,
    reorder_level: int,
    target_stock: int,
    pack_size: int = 1,
    category_id: int | None = None,
    store_id: int | None = None,
    note: str | None = None,
    position: int,
    source: str = "board",
) -> int:
    """Legt einen Artikel an und bucht die anfängliche `opening`-Bewegung.

    `qr_token` wird hier vergeben (`secrets.token_urlsafe(16)`); benutzt wird er erst in M3.
    """
    if stock < 0:
        raise ValueError("Anfangsbestand darf nicht negativ sein")

    with transaction(connection):
        now = utc_now_iso()
        qr_token = secrets.token_urlsafe(16)
        item_id = items_repo.insert(
            connection,
            name=name,
            unit=unit,
            note=note,
            stock=stock,
            reorder_level=reorder_level,
            target_stock=target_stock,
            pack_size=pack_size,
            category_id=category_id,
            store_id=store_id,
            qr_token=qr_token,
            position=position,
            created_at=now,
            updated_at=now,
        )
        movements_repo.insert(
            connection,
            item_id=item_id,
            kind="opening",
            delta=stock,
            stock_after=stock,
            source=source,
            created_at=now,
        )
    return item_id


def withdraw(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    source: str,
    idempotency_key: str | None = None,
    note: str | None = None,
) -> int:
    """Bucht eine Entnahme. `quantity` ist die entnommene Menge (positive Zahl)."""
    if quantity <= 0:
        raise ValueError("Entnahmemenge muss größer als 0 sein")

    with transaction(connection):
        item = _require_item(connection, item_id)
        new_stock = item.stock - quantity
        now = utc_now_iso()
        movement_id = movements_repo.insert(
            connection,
            item_id=item_id,
            kind="withdrawal",
            delta=-quantity,
            stock_after=new_stock,
            source=source,
            idempotency_key=idempotency_key,
            note=note,
            created_at=now,
        )
        items_repo.update_stock(connection, item_id, new_stock, now)
    return movement_id


def restock(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    source: str,
    line_id: int | None = None,
    idempotency_key: str | None = None,
    note: str | None = None,
) -> int:
    """Bucht einen Zugang. `quantity` ist die zugegangene Menge (positive Zahl)."""
    if quantity <= 0:
        raise ValueError("Zugangsmenge muss größer als 0 sein")

    with transaction(connection):
        item = _require_item(connection, item_id)
        new_stock = item.stock + quantity
        now = utc_now_iso()
        movement_id = movements_repo.insert(
            connection,
            item_id=item_id,
            kind="restock",
            delta=quantity,
            stock_after=new_stock,
            source=source,
            line_id=line_id,
            idempotency_key=idempotency_key,
            note=note,
            created_at=now,
        )
        items_repo.update_stock(connection, item_id, new_stock, now)
    return movement_id


def apply_inventory(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    expected_stock: int,
    actual_stock: int,
    source: str = "board",
    note: str | None = "Inventur",
) -> int:
    """Setzt den Bestand über eine `adjustment`-Bewegung, nie direkt auf `items.stock` (L10).

    Prüft `expected_stock` optimistisch gegen den aktuellen Bestand: Weicht er ab, wird nicht
    stillschweigend überschrieben, sondern `StaleInventoryError` geworfen.
    """
    if actual_stock < 0:
        raise ValueError("Bestand darf nicht negativ sein")

    with transaction(connection):
        item = _require_item(connection, item_id)
        if item.stock != expected_stock:
            raise StaleInventoryError(expected_stock=expected_stock, current_stock=item.stock)

        delta = actual_stock - item.stock
        now = utc_now_iso()
        movement_id = movements_repo.insert(
            connection,
            item_id=item_id,
            kind="adjustment",
            delta=delta,
            stock_after=actual_stock,
            source=source,
            note=note,
            created_at=now,
        )
        items_repo.update_stock(connection, item_id, actual_stock, now)
    return movement_id


def undo(connection: sqlite3.Connection, *, movement_id: int, source: str) -> int:
    """Bucht eine ausgleichende Gegenbewegung zu `movement_id` (L3) — kein DELETE."""
    with transaction(connection):
        movement = movements_repo.get_by_id(connection, movement_id)
        if movement is None:
            raise MovementNotFoundError(f"Bewegung {movement_id} existiert nicht")
        if movements_repo.find_reversal(connection, movement_id) is not None:
            raise AlreadyRevertedError(f"Bewegung {movement_id} wurde bereits rückgängig gemacht")

        item = _require_item(connection, movement.item_id)
        new_stock = item.stock - movement.delta
        now = utc_now_iso()
        reversal_id = movements_repo.insert(
            connection,
            item_id=movement.item_id,
            kind=movement.kind,
            delta=-movement.delta,
            stock_after=new_stock,
            source=source,
            reverts_movement_id=movement_id,
            created_at=now,
        )
        items_repo.update_stock(connection, movement.item_id, new_stock, now)
    return reversal_id
