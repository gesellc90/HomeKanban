"""Board-Router: `GET /`, siehe docs/PLAN.md §7 (M2).

Rendert die drei abgeleiteten Spalten (§4). Kommt mit zwei Abfragen aus: eine für die aktiven
Artikel, eine Sammelabfrage für offene, nicht abgehakte Listenpositionen — statt einer Abfrage
je Artikel (docs/PLAN.md, Aufgabe 1).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.deps import DbConnection
from app.domain.quantities import reorder_quantity
from app.domain.status import ItemStatus, derive_status
from app.repo import items as items_repo
from app.repo import shopping_lists as shopping_lists_repo
from app.repo.items import ItemRow
from app.web.templating import templates

router = APIRouter()


@dataclass(frozen=True)
class BoardEntry:
    item: ItemRow
    reorder_quantity: int | None


@router.get("/", response_class=HTMLResponse)
def board(request: Request, connection: DbConnection) -> HTMLResponse:
    active_items = items_repo.list_active(connection)
    open_list_item_ids = shopping_lists_repo.open_unchecked_item_ids(
        connection, (item.id for item in active_items)
    )

    columns: dict[ItemStatus, list[BoardEntry]] = {status: [] for status in ItemStatus}
    for item in active_items:
        status = derive_status(
            stock=item.stock,
            reorder_level=item.reorder_level,
            has_open_list_line=item.id in open_list_item_ids,
        )
        quantity = (
            reorder_quantity(
                stock=item.stock, target_stock=item.target_stock, pack_size=item.pack_size
            )
            if status is ItemStatus.REORDER
            else None
        )
        columns[status].append(BoardEntry(item=item, reorder_quantity=quantity))

    return templates.TemplateResponse(
        request,
        "board.html",
        {
            "ok_items": columns[ItemStatus.OK],
            "reorder_items": columns[ItemStatus.REORDER],
            "on_list_items": columns[ItemStatus.ON_LIST],
        },
    )
