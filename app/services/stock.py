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
from app.domain.undo import is_within_undo_window
from app.repo import items as items_repo
from app.repo import movements as movements_repo


class ItemNotFoundError(Exception):
    """Ein Artikel mit dieser ID existiert nicht."""


class MovementNotFoundError(Exception):
    """Eine Bewegung mit dieser ID existiert nicht."""


class AlreadyRevertedError(Exception):
    """Diese Bewegung wurde bereits rückgängig gemacht."""


class UndoWindowExpiredError(Exception):
    """Das Rückgängig-Fenster (`undo_window_minutes`, §5) ist für diese Bewegung abgelaufen.

    Der Korrekturweg ab jetzt ist die Inventur (`apply_inventory`), keine Gegenbewegung mehr.
    """


class StaleInventoryError(Exception):
    """Der erwartete Bestand stimmt nicht mehr mit dem aktuellen überein (L10)."""

    def __init__(self, *, expected_stock: int, current_stock: int) -> None:
        self.expected_stock = expected_stock
        self.current_stock = current_stock
        super().__init__(
            f"Bestand hat sich zwischenzeitlich geändert: erwartet {expected_stock}, "
            f"tatsächlich {current_stock}"
        )


def format_utc_iso(moment: datetime) -> str:
    """Formatiert einen `datetime` als UTC-ISO-8601 mit `Z`, Millisekunden (L9) — derselbe
    Ausgabeformatierer wie `utc_now_iso()`, für Aufrufer, die einen berechneten statt den
    aktuellen Zeitpunkt formatieren müssen (z. B. `now - 90 Tage` für die Verbrauchsrate, M8)."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def utc_now_iso() -> str:
    """Ein einziger Zeitstempel-Helfer: UTC, ISO-8601 mit `Z`, Millisekunden (L9)."""
    return format_utc_iso(datetime.now(UTC))


def _require_item(connection: sqlite3.Connection, item_id: int) -> items_repo.ItemRow:
    item = items_repo.get_by_id(connection, item_id)
    if item is None:
        raise ItemNotFoundError(f"Artikel {item_id} existiert nicht")
    return item


def book_create_item(
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
    lead_days: int = 7,
) -> int:
    """Legt einen Artikel an und bucht die anfängliche `opening`-Bewegung **innerhalb einer
    bereits offenen Transaktion**.

    Aufrufer, die selbst nichts weiter zu schreiben haben, nehmen `create_item()`. Diesen Kern
    braucht `app/services/stammdaten.py` (M9): Ein Stammdaten-Import legt mehrere Artikel plus
    Kategorien/Läden atomar an — alles oder nichts, siehe `book_restock()` für dasselbe Muster.

    `qr_token` wird hier vergeben (`secrets.token_urlsafe(16)`); benutzt wird er erst in M3.
    `lead_days` ist die Vorlaufzeit für den Schwellenvorschlag aus M8 (docs/PLAN.md §9, Frage 4)
    — seit M8 pro Artikel, der Standardwert 7 spiegelt `HOMEKANBAN_LEAD_DAYS` (app/config.py).
    """
    if stock < 0:
        raise ValueError("Anfangsbestand darf nicht negativ sein")

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
        lead_days=lead_days,
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
    lead_days: int = 7,
) -> int:
    """Legt einen Artikel an und bucht die anfängliche `opening`-Bewegung, siehe
    `book_create_item()`."""
    with transaction(connection):
        return book_create_item(
            connection,
            name=name,
            unit=unit,
            stock=stock,
            reorder_level=reorder_level,
            target_stock=target_stock,
            pack_size=pack_size,
            category_id=category_id,
            store_id=store_id,
            note=note,
            position=position,
            source=source,
            lead_days=lead_days,
        )


def withdraw(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    source: str,
    idempotency_key: str | None = None,
    note: str | None = None,
    now: str | None = None,
) -> int:
    """Bucht eine Entnahme. `quantity` ist die entnommene Menge (positive Zahl).

    `now` überschreibt den Zeitstempel (UTC-ISO-8601) und ist ausschließlich für
    `ops/seed.py` gedacht, um synthetische Verbrauchshistorie über vergangene Wochen zu buchen,
    ohne an `app/services/stock.py` vorbei zu schreiben (M8, docs/PLAN.md, Aufgabe 6) — die
    Invariante `SUM(delta) == stock` bleibt dabei gewahrt. Im normalen Betrieb bleibt es `None`.

    Idempotenz (§5): Ein zweites Absenden mit demselben `idempotency_key` — Reload,
    Zurück-Button, hektisches Doppeltippen, zwei Personen gleichzeitig (R7) — bucht nicht noch
    einmal, sondern liefert die ID der bereits vorhandenen Bewegung zurück.

    Zwei Wege dorthin sind nötig, kein einzelner genügt:
    1. Der Vorab-`SELECT` erspart im Normalfall (Reload, Zurück-Button) den zweiten Schreib-
       versuch überhaupt.
    2. Er allein schließt die Race Condition aber nicht aus: Zwei gleichzeitige Aufrufe mit
       demselben Schlüssel können beide den Vorab-`SELECT` mit demselben "noch nicht vorhanden"
       durchlaufen, bevor der erste committet hat (klassisches TOCTOU). Der Unique-Index auf
       `movements.idempotency_key` ist deshalb die eigentliche Garantie: Der zweite `INSERT`
       schlägt mit `IntegrityError` fehl, und erst dann liefert ein erneuter `SELECT` zuverlässig
       die vom ersten Aufruf geschriebene Bewegung.
    """
    if quantity <= 0:
        raise ValueError("Entnahmemenge muss größer als 0 sein")

    if idempotency_key is not None:
        existing = movements_repo.get_by_idempotency_key(connection, idempotency_key)
        if existing is not None:
            return existing.id

    try:
        with transaction(connection):
            item = _require_item(connection, item_id)
            new_stock = item.stock - quantity
            timestamp = now or utc_now_iso()
            movement_id = movements_repo.insert(
                connection,
                item_id=item_id,
                kind="withdrawal",
                delta=-quantity,
                stock_after=new_stock,
                source=source,
                idempotency_key=idempotency_key,
                note=note,
                created_at=timestamp,
            )
            items_repo.update_stock(connection, item_id, new_stock, timestamp)
    except sqlite3.IntegrityError:
        if idempotency_key is not None:
            existing = movements_repo.get_by_idempotency_key(connection, idempotency_key)
            if existing is not None:
                return existing.id
        raise
    return movement_id


def book_restock(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    source: str,
    line_id: int | None = None,
    idempotency_key: str | None = None,
    note: str | None = None,
    now: str | None = None,
) -> int:
    """Bucht einen Zugang **innerhalb einer bereits offenen Transaktion**.

    Aufrufer, die selbst nichts weiter zu schreiben haben, nehmen `restock()`. Diesen Kern
    braucht `app/services/shopping.py`: Dort gehört das Abhaken einer Position in dieselbe
    Transaktion wie der Zugang (§6), und `transaction()` ist wegen des prozessweiten Locks
    (ADR 0005) nicht wiedereintrittsfähig — ein `restock()` innerhalb einer offenen Transaktion
    würde sich selbst blockieren.
    """
    if quantity <= 0:
        raise ValueError("Zugangsmenge muss größer als 0 sein")

    item = _require_item(connection, item_id)
    new_stock = item.stock + quantity
    timestamp = now or utc_now_iso()
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
        created_at=timestamp,
    )
    items_repo.update_stock(connection, item_id, new_stock, timestamp)
    return movement_id


def book_reversal(
    connection: sqlite3.Connection,
    *,
    movement: movements_repo.MovementRow,
    source: str,
    now: str | None = None,
) -> int:
    """Bucht die Gegenbewegung zu `movement` **innerhalb einer bereits offenen Transaktion**.

    Bewusst **ohne** Prüfung des Undo-Fensters: Das Fenster gehört zum QR-Flow (§5), wo es einen
    Fehlgriff auffangen soll. Die Rücknahme einer Listenposition („doch nicht gekauft“) ist etwas
    anderes — sie darf Stunden nach dem Einkauf noch möglich sein. Die Fensterprüfung sitzt
    deshalb in `undo()`, nicht hier.
    """
    item = _require_item(connection, movement.item_id)
    new_stock = item.stock - movement.delta
    timestamp = now or utc_now_iso()
    reversal_id = movements_repo.insert(
        connection,
        item_id=movement.item_id,
        kind=movement.kind,
        delta=-movement.delta,
        stock_after=new_stock,
        source=source,
        line_id=movement.line_id,
        reverts_movement_id=movement.id,
        created_at=timestamp,
    )
    items_repo.update_stock(connection, movement.item_id, new_stock, timestamp)
    return reversal_id


def restock(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    source: str,
    line_id: int | None = None,
    idempotency_key: str | None = None,
    note: str | None = None,
    now: str | None = None,
) -> int:
    """Bucht einen Zugang. `quantity` ist die zugegangene Menge (positive Zahl).

    `now` überschreibt den Zeitstempel — wie bei `withdraw()`, ausschließlich für
    `ops/seed.py` gedacht, um synthetische Historie zu buchen (M8).
    """
    with transaction(connection):
        movement_id = book_restock(
            connection,
            item_id=item_id,
            quantity=quantity,
            source=source,
            line_id=line_id,
            idempotency_key=idempotency_key,
            note=note,
            now=now,
        )
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


def undo(
    connection: sqlite3.Connection, *, movement_id: int, source: str, window_minutes: int
) -> int:
    """Bucht eine ausgleichende Gegenbewegung zu `movement_id` (L3) — kein DELETE.

    Nur innerhalb von `window_minutes` seit der Bewegung erlaubt (§5); danach ist die Inventur
    der Korrekturweg, siehe `UndoWindowExpiredError`.
    """
    with transaction(connection):
        movement = movements_repo.get_by_id(connection, movement_id)
        if movement is None:
            raise MovementNotFoundError(f"Bewegung {movement_id} existiert nicht")
        if movements_repo.find_reversal(connection, movement_id) is not None:
            raise AlreadyRevertedError(f"Bewegung {movement_id} wurde bereits rückgängig gemacht")

        created_at = datetime.fromisoformat(movement.created_at.replace("Z", "+00:00"))
        if not is_within_undo_window(
            created_at=created_at, now=datetime.now(UTC), window_minutes=window_minutes
        ):
            raise UndoWindowExpiredError(
                f"Bewegung {movement_id} liegt außerhalb des {window_minutes}-Minuten-Fensters"
            )

        reversal_id = book_reversal(connection, movement=movement, source=source)
    return reversal_id
