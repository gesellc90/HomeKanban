"""Anwendungsfälle rund um die Einkaufsliste: erzeugen, abgleichen, abhaken, abschließen.

Siehe docs/PLAN.md §6. Die Entscheidung, was der Abgleich tut, liegt in `app/domain/shopping.py`;
hier steht nur die Ausführung — jeweils in **einer** Transaktion, ohne Rendern darin (R7).

Zwei Stellen brauchen besondere Sorgfalt, beide aus demselben Grund wie in M3 (ADR 0005: die
Datenbank ist die Instanz, die Gleichzeitigkeit wirklich entscheidet, nicht eine vorherige
Prüfung im Anwendungscode):

* **Höchstens eine offene Liste.** `ux_shopping_lists_one_open` erzwingt das. Zwei gleichzeitige
  „Liste erzeugen“ würden sonst in einem `IntegrityError` und damit in einer 500er-Seite enden.
  Deshalb dasselbe Muster wie beim Idempotenzschlüssel: vorher nachsehen, den `IntegrityError`
  abfangen, danach erneut nachschlagen.
* **Abhaken bucht genau einmal.** Der Schutz ist das bedingte `UPDATE` in
  `repo.shopping_lists.mark_checked` (`WHERE checked_at IS NULL`), nicht eine Vorabprüfung.
  Ein `movements.idempotency_key` wäre hier der falsche Weg: Ein aus der `line_id` abgeleiteter
  Schlüssel würde nach „abhaken → zurücknehmen → erneut abhaken“ kollidieren und die zweite,
  völlig legitime Buchung verschlucken.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.db import transaction
from app.domain.shopping import (
    ReconciliationItem,
    ReconciliationLine,
    ReconciliationPlan,
    plan_reconciliation,
)
from app.repo import items as items_repo
from app.repo import movements as movements_repo
from app.repo import shopping_lists as lists_repo
from app.services.stock import book_restock, book_reversal, utc_now_iso

SOURCE = "shopping_list"

# Obergrenze für eine von Hand eingetippte Kaufmenge. Kein fachliches Limit, sondern ein Fangnetz
# für Vertipper ("100" statt "10" ist plausibel, "1000000" ist ein Zahlendreher).
MAX_PURCHASED_QTY = 9999


class ShoppingListNotFoundError(Exception):
    """Eine Liste mit dieser ID existiert nicht."""


class ListClosedError(Exception):
    """Diese Liste ist bereits abgeschlossen."""


class LineNotFoundError(Exception):
    """Eine Position mit dieser ID existiert nicht — oder nicht in dieser Liste."""


class LineDroppedError(Exception):
    """Diese Position wurde verworfen und kann nicht abgehakt werden."""


class LineAlreadyCheckedError(Exception):
    """Diese Position ist bereits abgehakt; ein zweites Abhaken bucht nicht noch einmal."""


class InvalidQuantityError(Exception):
    """Die eingegebene Kaufmenge ist unbrauchbar. Die Meldung ist für Endnutzer gedacht."""


@dataclass(frozen=True)
class CheckResult:
    """Ergebnis eines Abhakens — `movement_id is None` heißt: abgehakt, aber nichts gebucht."""

    line_id: int
    purchased_qty: int
    movement_id: int | None
    note: str | None = None


# --- Liste erzeugen und abgleichen -------------------------------------------------------------


def ensure_open_list(connection: sqlite3.Connection) -> lists_repo.ShoppingListRow:
    """Liefert die offene Liste und legt sie an, falls es noch keine gibt."""
    existing = lists_repo.get_open_list(connection)
    if existing is not None:
        return existing

    try:
        with transaction(connection):
            list_id = lists_repo.insert_list(connection, created_at=utc_now_iso())
    except sqlite3.IntegrityError:
        # Jemand anders war zwischen Nachsehen und Einfügen schneller (ADR 0005). Der partielle
        # Unique-Index hat das verhindert — jetzt gilt dessen Liste.
        concurrent = lists_repo.get_open_list(connection)
        if concurrent is None:
            raise
        return concurrent

    created = lists_repo.get_list(connection, list_id)
    assert created is not None
    return created


def reconcile(connection: sqlite3.Connection, list_id: int) -> ReconciliationPlan:
    """Führt den Abgleich aus §6 gegen eine offene Liste aus und liefert, was getan wurde."""
    with transaction(connection):
        list_row = _require_open_list(connection, list_id)
        lines = lists_repo.list_lines(connection, list_row.id)
        active_items = items_repo.list_active(connection)

        plan = plan_reconciliation(
            items=[
                ReconciliationItem(
                    item_id=item.id,
                    name=item.name,
                    unit=item.unit,
                    stock=item.stock,
                    reorder_level=item.reorder_level,
                    target_stock=item.target_stock,
                    pack_size=item.pack_size,
                )
                for item in active_items
            ],
            lines=[
                ReconciliationLine(
                    line_id=line.id,
                    item_id=line.item_id,
                    suggested_qty=line.suggested_qty,
                    is_checked=line.is_checked,
                    is_dropped=line.is_dropped,
                )
                for line in lines
            ],
            next_position=lists_repo.next_line_position(connection, list_row.id),
        )

        now = utc_now_iso()
        for line_id_to_drop in plan.to_drop:
            lists_repo.drop_line(connection, line_id_to_drop, dropped_at=now)
        for update in plan.to_requantify:
            lists_repo.update_suggested_qty(
                connection, update.line_id, suggested_qty=update.suggested_qty
            )
        for line_to_append in plan.to_append:
            lists_repo.insert_line(
                connection,
                list_id=list_row.id,
                item_id=line_to_append.item_id,
                suggested_qty=line_to_append.suggested_qty,
                name_snapshot=line_to_append.name_snapshot,
                unit_snapshot=line_to_append.unit_snapshot,
                position=line_to_append.position,
            )

    return plan


def create_or_reconcile_list(
    connection: sqlite3.Connection,
) -> tuple[lists_repo.ShoppingListRow, ReconciliationPlan]:
    """Der Weg hinter „Liste erzeugen“ und hinter dem Export-`POST` (§6).

    Beides ist derselbe Vorgang: Es gibt nie zwei konkurrierende Listen, sondern eine Liste, die
    den aktuellen Bedarf zeigt. Eine zweite Exportanfrage erzeugt daher keine zweite Liste.
    """
    list_row = ensure_open_list(connection)
    plan = reconcile(connection, list_row.id)
    refreshed = lists_repo.get_list(connection, list_row.id)
    assert refreshed is not None
    return refreshed, plan


def mark_exported(connection: sqlite3.Connection, list_id: int) -> lists_repo.ShoppingListRow:
    """Setzt `exported_at` und erhöht `export_count` — nur beim `POST`, nie beim `GET` (§6)."""
    with transaction(connection):
        _require_open_list(connection, list_id)
        lists_repo.mark_exported(connection, list_id, exported_at=utc_now_iso())
    refreshed = lists_repo.get_list(connection, list_id)
    assert refreshed is not None
    return refreshed


# --- Abhaken und Zurücknehmen ------------------------------------------------------------------


def check_line(
    connection: sqlite3.Connection,
    *,
    list_id: int,
    line_id: int,
    purchased_qty: int | None = None,
) -> CheckResult:
    """Hakt eine Position ab und bucht den Zugang in derselben Transaktion (§6).

    * ohne `purchased_qty` → Bestand wird **auf `target_stock` gesetzt**
    * mit `purchased_qty` → `stock += purchased_qty`

    Das ist nicht dasselbe: Wer nichts angibt, sagt „so viel gekauft, dass der Sollbestand
    erreicht ist“; wer eine Menge angibt, sagt „genau so viel ist dazugekommen“.

    Randfall ohne Angabe: Liegt der Bestand bereits bei oder über `target_stock` — jemand hat
    zwischenzeitlich eine Inventur gemacht oder spontan nachgekauft — gibt es nichts zu buchen.
    Dann wird die Position abgehakt, aber **keine** Bewegung geschrieben; ein Zugang mit `delta
    <= 0` wäre eine Lüge im Journal, und ein Fehler wäre hier unangemessen.
    """
    if purchased_qty is not None:
        _require_valid_quantity(purchased_qty)

    with transaction(connection):
        _require_open_list(connection, list_id)
        line = _require_line_of_list(connection, list_id, line_id)
        if line.is_dropped:
            raise LineDroppedError(f"Position {line_id} wurde verworfen")
        if line.is_checked:
            raise LineAlreadyCheckedError(f"Position {line_id} ist bereits abgehakt")

        item = items_repo.get_by_id(connection, line.item_id)
        if item is None:
            raise LineNotFoundError(f"Artikel zu Position {line_id} existiert nicht")

        note: str | None = None
        if purchased_qty is None:
            quantity = max(item.target_stock - item.stock, 0)
            recorded_qty = line.suggested_qty if quantity > 0 else 0
            if quantity == 0:
                note = (
                    f"Der Bestand liegt mit {item.stock} {item.unit} bereits beim Sollbestand "
                    f"({item.target_stock}) — es wurde nichts gebucht. Falls doch etwas "
                    "dazugekommen ist, bitte die Menge eintragen."
                )
        else:
            quantity = purchased_qty
            recorded_qty = purchased_qty

        now = utc_now_iso()
        if (
            lists_repo.mark_checked(connection, line_id, checked_at=now, purchased_qty=recorded_qty)
            == 0
        ):
            # Jemand anders war schneller: das bedingte UPDATE hat nicht gegriffen.
            raise LineAlreadyCheckedError(f"Position {line_id} ist bereits abgehakt")

        movement_id: int | None = None
        if quantity > 0:
            movement_id = book_restock(
                connection,
                item_id=line.item_id,
                quantity=quantity,
                source=SOURCE,
                line_id=line_id,
                now=now,
            )

    return CheckResult(
        line_id=line_id, purchased_qty=recorded_qty, movement_id=movement_id, note=note
    )


def check_all_open_lines(connection: sqlite3.Connection, list_id: int) -> list[CheckResult]:
    """„Alles gekauft“ (O1, R2): hakt jede offene Position ab und bucht sie.

    Jede Position bekommt ihre eigene kurze Transaktion (R7) statt einer langen über die ganze
    Liste. Positionen, die zwischenzeitlich von jemand anderem abgehakt oder verworfen wurden,
    werden übersprungen statt zum Fehler zu führen — der Sammelbutton soll das Naheliegende tun.
    """
    _require_open_list(connection, list_id)

    results: list[CheckResult] = []
    for line in lists_repo.list_lines(connection, list_id):
        if not line.is_open:
            continue
        try:
            results.append(check_line(connection, list_id=list_id, line_id=line.id))
        except (LineAlreadyCheckedError, LineDroppedError):
            continue
    return results


def uncheck_line(connection: sqlite3.Connection, *, list_id: int, line_id: int) -> int | None:
    """Nimmt ein Abhaken zurück („doch nicht gekauft“, §6) und liefert die Gegenbewegung.

    Erzeugt die Gegenbewegung (L3), kein Löschen im Journal, und leert `checked_at`. Bewusst
    **ohne** Undo-Fenster: Das Fenster aus §5 gehört zum QR-Flow. Wer abends beim Einräumen
    merkt, dass eine Packung doch nicht im Wagen lag, darf das Stunden nach dem Einkauf noch
    korrigieren — siehe `stock.book_reversal`.

    Eine erneute Rücknahme ist harmlos: Sie findet keine offene Buchung mehr und liefert `None`.
    """
    with transaction(connection):
        _require_open_list(connection, list_id)
        line = _require_line_of_list(connection, list_id, line_id)
        if not line.is_checked:
            return None

        movement = movements_repo.find_unreverted_for_line(connection, line_id)
        reversal_id = (
            book_reversal(connection, movement=movement, source=SOURCE)
            if movement is not None
            else None
        )
        lists_repo.clear_checked(connection, line_id)
    return reversal_id


# --- Abschließen -------------------------------------------------------------------------------


def complete_list(connection: sqlite3.Connection, list_id: int) -> int:
    """„Einkauf abschließen“ (§6): offene Positionen verwerfen, Liste auf `done`.

    Die verworfenen Artikel liegen weiter unter ihrer Schwelle und stehen damit sofort wieder in
    NACHKAUFEN; beim nächsten Abgleich sind sie automatisch wieder dabei. Nichts geht verloren,
    und keine Liste schleppt sich über Wochen. Liefert die Zahl der verworfenen Positionen.
    """
    with transaction(connection):
        _require_open_list(connection, list_id)
        now = utc_now_iso()
        dropped = lists_repo.drop_open_lines(connection, list_id, dropped_at=now)
        if (
            lists_repo.close_list(connection, list_id, status=lists_repo.STATUS_DONE, closed_at=now)
            == 0
        ):
            raise ListClosedError(f"Liste {list_id} ist bereits abgeschlossen")
    return dropped


# --- Hilfen ------------------------------------------------------------------------------------


def _require_open_list(connection: sqlite3.Connection, list_id: int) -> lists_repo.ShoppingListRow:
    list_row = lists_repo.get_list(connection, list_id)
    if list_row is None:
        raise ShoppingListNotFoundError(f"Einkaufsliste {list_id} existiert nicht")
    if list_row.status != lists_repo.STATUS_OPEN:
        raise ListClosedError(f"Einkaufsliste {list_id} ist bereits abgeschlossen")
    return list_row


def _require_line_of_list(
    connection: sqlite3.Connection, list_id: int, line_id: int
) -> lists_repo.ShoppingListLineRow:
    line = lists_repo.get_line(connection, line_id)
    if line is None or line.list_id != list_id:
        raise LineNotFoundError(f"Position {line_id} gehört nicht zu Einkaufsliste {list_id}")
    return line


def _require_valid_quantity(purchased_qty: int) -> None:
    if purchased_qty <= 0:
        raise InvalidQuantityError(
            "Die Menge muss größer als 0 sein. Wenn du nichts bekommen hast, lass die Position "
            "einfach offen — beim Abschließen bleibt der Artikel im Nachkaufen."
        )
    if purchased_qty > MAX_PURCHASED_QTY:
        raise InvalidQuantityError(
            f"Die Menge {purchased_qty} wirkt unplausibel (höchstens {MAX_PURCHASED_QTY}). "
            "Bitte prüfen."
        )
