"""Artikel-Router: Anlegen, Detail/Stammdaten, Inventur, Archivieren/Reaktivieren.

Siehe docs/PLAN.md §7 (M2). Jeder schreibende POST antwortet nach Erfolg mit `303 See Other` —
ein Reload der Ergebnisseite darf nie noch einmal buchen oder anlegen. Validierungsfehler
(Domänenregeln aus `app/domain/validation.py`, doppelte Namen aus dem partiellen Unique-Index)
werden dagegen direkt mit einem Nicht-500-Statuscode zurückgerendert, ohne Redirect — es wurde
nichts geschrieben, ein erneutes Absenden ist ungefährlich.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domain.quantities import reorder_quantity
from app.domain.status import ItemStatus, derive_status
from app.domain.validation import ItemInput, validate_item
from app.repo import items as items_repo
from app.repo import movements as movements_repo
from app.repo import shopping_lists as shopping_lists_repo
from app.services import stock as stock_service
from app.web.templating import templates

router = APIRouter()

_DUPLICATE_NAME_MARKER = "items.name"


def _duplicate_name_message(name: str) -> str:
    return f"Der Name „{name}“ ist bereits durch einen anderen aktiven Artikel vergeben."


@dataclass(frozen=True)
class _ItemFormValues:
    name: str
    unit: str
    note: str
    reorder_level: int
    target_stock: int
    pack_size: int
    stock: int = 0


def _new_form_defaults() -> _ItemFormValues:
    return _ItemFormValues(
        name="", unit="", note="", reorder_level=1, target_stock=2, pack_size=1, stock=0
    )


def _form_values_from_item(item: items_repo.ItemRow) -> _ItemFormValues:
    return _ItemFormValues(
        name=item.name,
        unit=item.unit,
        note=item.note or "",
        reorder_level=item.reorder_level,
        target_stock=item.target_stock,
        pack_size=item.pack_size,
        stock=item.stock,
    )


@router.get("/artikel/neu", response_class=HTMLResponse)
def new_item_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "item_new.html", {"values": _new_form_defaults(), "errors": []}
    )


@router.post("/artikel", response_model=None)
def create_item(
    request: Request,
    name: str = Form(""),
    unit: str = Form(""),
    note: str = Form(""),
    stock: int = Form(0),
    reorder_level: int = Form(...),
    target_stock: int = Form(...),
    pack_size: int = Form(1),
) -> HTMLResponse | RedirectResponse:
    connection = request.app.state.db

    clean_name = name.strip()
    clean_unit = unit.strip()
    clean_note = note.strip() or None
    values = _ItemFormValues(
        name=clean_name,
        unit=clean_unit,
        note=note.strip(),
        reorder_level=reorder_level,
        target_stock=target_stock,
        pack_size=pack_size,
        stock=stock,
    )

    errors = validate_item(
        ItemInput(
            name=clean_name,
            unit=clean_unit,
            reorder_level=reorder_level,
            target_stock=target_stock,
            pack_size=pack_size,
            stock=stock,
            note=clean_note,
        )
    )
    if errors:
        return templates.TemplateResponse(
            request, "item_new.html", {"values": values, "errors": errors}, status_code=422
        )

    try:
        item_id = stock_service.create_item(
            connection,
            name=clean_name,
            unit=clean_unit,
            stock=stock,
            reorder_level=reorder_level,
            target_stock=target_stock,
            pack_size=pack_size,
            note=clean_note,
            position=items_repo.next_position(connection),
            source="board",
        )
    except sqlite3.IntegrityError as error:
        if _DUPLICATE_NAME_MARKER not in str(error):
            raise
        return templates.TemplateResponse(
            request,
            "item_new.html",
            {"values": values, "errors": [_duplicate_name_message(clean_name)]},
            status_code=422,
        )

    return RedirectResponse(f"/artikel/{item_id}", status_code=303)


def _require_item(connection: sqlite3.Connection, item_id: int) -> items_repo.ItemRow:
    item = items_repo.get_by_id(connection, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Artikel nicht gefunden")
    return item


@dataclass(frozen=True)
class _DetailErrors:
    form_errors: list[str] = field(default_factory=list)
    inventory_errors: list[str] = field(default_factory=list)
    reactivate_errors: list[str] = field(default_factory=list)


def _render_detail(
    request: Request,
    connection: sqlite3.Connection,
    item_id: int,
    *,
    status_code: int = 200,
    form_values: _ItemFormValues | None = None,
    inventory_expected_stock: int | None = None,
    errors: _DetailErrors | None = None,
) -> HTMLResponse:
    item = _require_item(connection, item_id)
    errors = errors or _DetailErrors()

    has_open_list_line = shopping_lists_repo.has_open_unchecked_line(connection, item_id)
    item_status = derive_status(
        stock=item.stock, reorder_level=item.reorder_level, has_open_list_line=has_open_list_line
    )
    reorder_qty = (
        reorder_quantity(stock=item.stock, target_stock=item.target_stock, pack_size=item.pack_size)
        if item_status is ItemStatus.REORDER
        else None
    )

    base_url = request.app.state.settings.base_url.rstrip("/")

    context: dict[str, Any] = {
        "item": item,
        "status": item_status,
        "reorder_qty": reorder_qty,
        "movements": movements_repo.list_for_item(connection, item_id),
        "form_values": form_values or _form_values_from_item(item),
        "inventory_expected_stock": (
            inventory_expected_stock if inventory_expected_stock is not None else item.stock
        ),
        "form_errors": errors.form_errors,
        "inventory_errors": errors.inventory_errors,
        "reactivate_errors": errors.reactivate_errors,
        # Entnahme-Link zum Testen ohne Etikett — der Einzel-QR selbst kommt erst in M5
        # (docs/PLAN.md §9, M3, Punkt 6).
        "scan_url": f"{base_url}/e/{item.qr_token}",
    }
    return templates.TemplateResponse(request, "item_detail.html", context, status_code=status_code)


@router.get("/artikel/{item_id}", response_class=HTMLResponse)
def item_detail(request: Request, item_id: int) -> HTMLResponse:
    connection = request.app.state.db
    return _render_detail(request, connection, item_id)


@router.post("/artikel/{item_id}", response_model=None)
def update_item(
    request: Request,
    item_id: int,
    name: str = Form(""),
    unit: str = Form(""),
    note: str = Form(""),
    reorder_level: int = Form(...),
    target_stock: int = Form(...),
    pack_size: int = Form(1),
) -> HTMLResponse | RedirectResponse:
    connection = request.app.state.db
    _require_item(connection, item_id)

    clean_name = name.strip()
    clean_unit = unit.strip()
    clean_note = note.strip() or None
    submitted_values = _ItemFormValues(
        name=clean_name,
        unit=clean_unit,
        note=note.strip(),
        reorder_level=reorder_level,
        target_stock=target_stock,
        pack_size=pack_size,
    )

    errors = validate_item(
        ItemInput(
            name=clean_name,
            unit=clean_unit,
            reorder_level=reorder_level,
            target_stock=target_stock,
            pack_size=pack_size,
            note=clean_note,
        )
    )
    if errors:
        return _render_detail(
            request,
            connection,
            item_id,
            status_code=422,
            form_values=submitted_values,
            errors=_DetailErrors(form_errors=errors),
        )

    try:
        items_repo.update(
            connection,
            item_id,
            name=clean_name,
            unit=clean_unit,
            note=clean_note,
            reorder_level=reorder_level,
            target_stock=target_stock,
            pack_size=pack_size,
            updated_at=stock_service.utc_now_iso(),
        )
    except sqlite3.IntegrityError as error:
        if _DUPLICATE_NAME_MARKER not in str(error):
            raise
        return _render_detail(
            request,
            connection,
            item_id,
            status_code=422,
            form_values=submitted_values,
            errors=_DetailErrors(form_errors=[_duplicate_name_message(clean_name)]),
        )

    return RedirectResponse(f"/artikel/{item_id}", status_code=303)


@router.post("/artikel/{item_id}/inventur", response_model=None)
def apply_inventory(
    request: Request,
    item_id: int,
    expected_stock: int = Form(...),
    actual_stock: int = Form(...),
) -> HTMLResponse | RedirectResponse:
    connection = request.app.state.db
    _require_item(connection, item_id)

    try:
        stock_service.apply_inventory(
            connection, item_id=item_id, expected_stock=expected_stock, actual_stock=actual_stock
        )
    except stock_service.StaleInventoryError as error:
        return _render_detail(
            request,
            connection,
            item_id,
            status_code=409,
            inventory_expected_stock=error.current_stock,
            errors=_DetailErrors(
                inventory_errors=[
                    "Der Bestand hat sich zwischenzeitlich geändert: erwartet wurde "
                    f"{error.expected_stock}, tatsächlich sind es {error.current_stock}. "
                    "Bitte prüfen und erneut buchen."
                ]
            ),
        )
    except ValueError as error:
        return _render_detail(
            request,
            connection,
            item_id,
            status_code=422,
            errors=_DetailErrors(inventory_errors=[str(error)]),
        )

    return RedirectResponse(f"/artikel/{item_id}", status_code=303)


@router.post("/artikel/{item_id}/archivieren")
def archive_item(request: Request, item_id: int) -> RedirectResponse:
    connection = request.app.state.db
    _require_item(connection, item_id)

    items_repo.archive(connection, item_id, stock_service.utc_now_iso())

    return RedirectResponse("/", status_code=303)


@router.post("/artikel/{item_id}/reaktivieren", response_model=None)
def reactivate_item(request: Request, item_id: int) -> HTMLResponse | RedirectResponse:
    connection = request.app.state.db
    item = _require_item(connection, item_id)

    try:
        items_repo.reactivate(connection, item_id, stock_service.utc_now_iso())
    except sqlite3.IntegrityError as error:
        if _DUPLICATE_NAME_MARKER not in str(error):
            raise
        return _render_detail(
            request,
            connection,
            item_id,
            status_code=422,
            errors=_DetailErrors(
                reactivate_errors=[
                    f"Der Name „{item.name}“ ist inzwischen durch einen anderen aktiven Artikel "
                    "vergeben. Bitte zuerst umbenennen, dann erneut reaktivieren."
                ]
            ),
        )

    return RedirectResponse(f"/artikel/{item_id}", status_code=303)
