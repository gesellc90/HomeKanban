"""QR-Entnahme-Flow: Scannen, Buchen, Rückgängig. Siehe docs/PLAN.md §5, §7 (M3).

`GET /e/{token}` verändert nichts (Kamera-Apps und Messenger laden URLs vorab) und trägt deshalb
`Cache-Control: no-store`. Jede Buchung ist ein `POST` mit einem beim Rendern erzeugten
`idempotency_key`; ein zweites Absenden desselben Formulars liefert das bestehende Ergebnis statt
einer zweiten Buchung (siehe `app/services/stock.py`). Fehlbedienung — unbekanntes Token,
archivierter Artikel, Entnahme über den Bestand hinaus, abgelaufenes Undo-Fenster, doppeltes
Undo — endet immer auf einer verständlichen deutschen Seite mit einem Nicht-500-Statuscode, nie
in einem Stacktrace.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import DbConnection
from app.domain.quantities import reorder_quantity
from app.domain.status import ItemStatus, derive_status
from app.domain.undo import is_within_undo_window
from app.repo import items as items_repo
from app.repo import movements as movements_repo
from app.repo import shopping_lists as shopping_lists_repo
from app.services import stock as stock_service
from app.web.templating import templates

router = APIRouter()

# CHECK (stock >= 0) aus migrations/0001_init.sql — Marker, um genau diese Verletzung zu erkennen
# (vgl. app/web/items.py, _DUPLICATE_NAME_MARKER für dasselbe Muster bei items.name).
_STOCK_CHECK_MARKER = "stock >= 0"


def _new_idempotency_key() -> str:
    return secrets.token_urlsafe(16)


def _render_scan_error(
    request: Request, *, status_code: int, title: str, message: str
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "scan_error.html",
        {"title": title, "message": message},
        status_code=status_code,
    )


def _unknown_token_error(request: Request) -> HTMLResponse:
    return _render_scan_error(
        request,
        status_code=404,
        title="Unbekannter Code",
        message=(
            "Dieser QR-Code ist bei HomeKanban nicht bekannt. Vielleicht wurde der Artikel "
            "gelöscht, oder das Etikett gehört zu einer anderen App."
        ),
    )


def _archived_item_error(request: Request, item: items_repo.ItemRow) -> HTMLResponse:
    return _render_scan_error(
        request,
        status_code=410,
        title="Artikel archiviert",
        message=(
            f"„{item.name}“ ist archiviert. Das Etikett klebt noch, aber der Artikel wird hier "
            "nicht mehr geführt — gebucht wird nicht."
        ),
    )


@dataclass(frozen=True)
class _ScanContext:
    item: items_repo.ItemRow
    status: ItemStatus
    reorder_qty: int | None


def _scan_context(connection: sqlite3.Connection, item: items_repo.ItemRow) -> _ScanContext:
    has_open_list_line = shopping_lists_repo.has_open_unchecked_line(connection, item.id)
    status = derive_status(
        stock=item.stock, reorder_level=item.reorder_level, has_open_list_line=has_open_list_line
    )
    reorder_qty = (
        reorder_quantity(stock=item.stock, target_stock=item.target_stock, pack_size=item.pack_size)
        if status is ItemStatus.REORDER
        else None
    )
    return _ScanContext(item=item, status=status, reorder_qty=reorder_qty)


def _render_entnahme(
    request: Request,
    connection: sqlite3.Connection,
    item: items_repo.ItemRow,
    *,
    status_code: int = 200,
    error: str | None = None,
) -> HTMLResponse:
    context = _scan_context(connection, item)
    response = templates.TemplateResponse(
        request,
        "scan_entnahme.html",
        {
            "item": context.item,
            "status": context.status,
            "reorder_qty": context.reorder_qty,
            "quick_idempotency_key": _new_idempotency_key(),
            "step_idempotency_key": _new_idempotency_key(),
            "error": error,
        },
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _render_result(
    request: Request,
    connection: sqlite3.Connection,
    item: items_repo.ItemRow,
    movement: movements_repo.MovementRow,
    *,
    undo_error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    settings = request.app.state.settings
    context = _scan_context(connection, item)
    already_reverted = movements_repo.find_reversal(connection, movement.id) is not None
    created_at = datetime.fromisoformat(movement.created_at.replace("Z", "+00:00"))
    can_undo = not already_reverted and is_within_undo_window(
        created_at=created_at, now=datetime.now(UTC), window_minutes=settings.undo_window_minutes
    )
    return templates.TemplateResponse(
        request,
        "scan_ergebnis.html",
        {
            "item": context.item,
            "status": context.status,
            "reorder_qty": context.reorder_qty,
            "movement": movement,
            "already_reverted": already_reverted,
            "can_undo": can_undo,
            "undo_error": undo_error,
            "scan_href": f"/e/{item.qr_token}",
        },
        status_code=status_code,
    )


@router.get("/e/{token}", response_class=HTMLResponse)
def scan_item(request: Request, token: str, connection: DbConnection) -> HTMLResponse:
    item = items_repo.get_by_qr_token(connection, token)
    if item is None:
        return _unknown_token_error(request)
    if item.archived_at is not None:
        return _archived_item_error(request, item)

    return _render_entnahme(request, connection, item)


@router.post("/e/{token}/entnahme", response_model=None)
def book_withdrawal(
    request: Request,
    token: str,
    connection: DbConnection,
    quantity: int = Form(...),
    idempotency_key: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    item = items_repo.get_by_qr_token(connection, token)
    if item is None:
        return _unknown_token_error(request)
    if item.archived_at is not None:
        return _archived_item_error(request, item)

    try:
        movement_id = stock_service.withdraw(
            connection,
            item_id=item.id,
            quantity=quantity,
            source="qr",
            idempotency_key=idempotency_key,
        )
    except ValueError as error:
        return _render_entnahme(request, connection, item, status_code=422, error=str(error))
    except sqlite3.IntegrityError as error:
        if _STOCK_CHECK_MARKER not in str(error):
            raise
        return _render_entnahme(
            request,
            connection,
            item,
            status_code=422,
            error=(
                f"Entnahme von {quantity} {item.unit} übersteigt den Bestand "
                f"({item.stock} {item.unit})."
            ),
        )

    return RedirectResponse(f"/e/{token}/ok/{movement_id}", status_code=303)


@router.get("/e/{token}/ok/{movement_id}", response_class=HTMLResponse)
def scan_result(
    request: Request,
    token: str,
    movement_id: int,
    connection: DbConnection,
) -> HTMLResponse:
    item = items_repo.get_by_qr_token(connection, token)
    if item is None:
        return _unknown_token_error(request)

    movement = movements_repo.get_by_id(connection, movement_id)
    if movement is None or movement.item_id != item.id:
        return _render_scan_error(
            request,
            status_code=404,
            title="Buchung nicht gefunden",
            message="Diese Buchung gehört nicht zu diesem Artikel oder existiert nicht (mehr).",
        )

    return _render_result(request, connection, item, movement)


@router.post("/bewegungen/{movement_id}/rueckgaengig", response_model=None)
def undo_movement(
    request: Request,
    movement_id: int,
    connection: DbConnection,
) -> HTMLResponse | RedirectResponse:
    settings = request.app.state.settings

    movement = movements_repo.get_by_id(connection, movement_id)
    if movement is None:
        return _render_scan_error(
            request,
            status_code=404,
            title="Buchung nicht gefunden",
            message="Diese Buchung existiert nicht (mehr).",
        )
    item = items_repo.get_by_id(connection, movement.item_id)
    assert item is not None  # Artikel werden nie gelöscht, nur archiviert.

    try:
        stock_service.undo(
            connection,
            movement_id=movement_id,
            source="qr",
            window_minutes=settings.undo_window_minutes,
        )
    except stock_service.AlreadyRevertedError:
        return _render_result(
            request,
            connection,
            item,
            movement,
            status_code=409,
            undo_error="Diese Buchung wurde bereits rückgängig gemacht.",
        )
    except stock_service.UndoWindowExpiredError:
        return _render_result(
            request,
            connection,
            item,
            movement,
            status_code=409,
            undo_error=(
                f"Das Zeitfenster zum Rückgängigmachen ({settings.undo_window_minutes} Minuten) "
                "ist abgelaufen. Für Korrekturen bitte „Bestand korrigieren“ auf der "
                "Entnahmeseite verwenden."
            ),
        )

    return RedirectResponse(f"/e/{item.qr_token}", status_code=303)
