"""Verlauf und Verbrauchsprognose, siehe docs/PLAN.md §7, §9 (M8).

`GET /verlauf` ist die Haushaltsübersicht „was geht zuerst aus“ — alle aktiven Artikel nach
Reichweite sortiert (Fragerunde M8, Frage 2). `GET /artikel/{id}/verlauf` ist die vollständige,
ungekürzte Journalansicht eines einzelnen Artikels mitsamt Schwellenvorschlag; die kurze Vorschau
auf `/artikel/{id}` verlinkt hierher. `POST /artikel/{id}/verlauf/uebernehmen` schreibt einen
übernommenen Vorschlag als `reorder_level` (Frage 3: nachvollziehbar über `updated_at`, wie jede
andere Stammdatenänderung — kein Eintrag im Bewegungsjournal, das wäre eine Lüge im
Bestandsjournal, siehe `app/repo/items.py::update_reorder_level`).

Fehlbedienung endet immer auf einer verständlichen deutschen Seite mit einem Nicht-500-
Statuscode: unbekannte Artikel-ID (404), Übernehmen ohne ausreichende Datenlage (409, die Lage
kann sich zwischen Seitenaufruf und Klick geändert haben) und ein Vorschlag, der
`target_stock > reorder_level` verletzen würde (422 — ein rechnerisch korrekter Vorschlag, der an
einer Stammdatenregel scheitert, braucht eine Antwort, die sagt, was zu tun ist).

**Archivierte Artikel bleiben über `/artikel/{id}/verlauf` erreichbar** (§4 Regel 4 spricht von
Board und Listen, nicht vom Journal): Das Journal ist die historische Aufzeichnung und soll nicht
verschwinden, nur weil ein Artikel nicht mehr geführt wird. Prognose und Übernehmen-Weg werden für
archivierte Artikel aber ausgeblendet — weiterer Verbrauch wird nicht mehr gescannt, eine Rate
wäre ohne neue Daten nur eingefroren, und eine Schwellenänderung an einem archivierten Artikel hat
keinen Betriebszweck.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domain import forecast
from app.repo import items as items_repo
from app.repo import movements as movements_repo
from app.repo.items import ItemRow
from app.repo.movements import MovementRow
from app.services import stock as stock_service
from app.web.templating import templates

router = APIRouter()


def _require_item(connection: sqlite3.Connection, item_id: int) -> ItemRow:
    item = items_repo.get_by_id(connection, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Artikel nicht gefunden")
    return item


def _since_iso(*, now: datetime, window_days: int) -> str:
    return stock_service.format_utc_iso(now - timedelta(days=window_days))


def _to_events(movements: list[MovementRow]) -> list[forecast.WithdrawalObservation]:
    return [
        forecast.WithdrawalObservation(
            occurred_at=datetime.fromisoformat(movement.created_at.replace("Z", "+00:00")),
            quantity=-movement.delta,
        )
        for movement in movements
    ]


@dataclass(frozen=True)
class _ReachEntry:
    item: ItemRow
    reach: forecast.ReachEstimate


def _reach_sort_key(entry: _ReachEntry) -> tuple[int, float]:
    if entry.reach.is_unlimited:
        return (1, 0.0)
    assert entry.reach.days is not None
    return (0, entry.reach.days)


@router.get("/verlauf", response_class=HTMLResponse)
def household_overview(request: Request) -> HTMLResponse:
    connection = request.app.state.db

    active_items = items_repo.list_active(connection)
    since = _since_iso(now=datetime.now(UTC), window_days=forecast.RATE_WINDOW_DAYS)
    withdrawals_by_item: dict[int, list[MovementRow]] = {}
    for movement in movements_repo.list_unreverted_withdrawals_since(connection, since=since):
        withdrawals_by_item.setdefault(movement.item_id, []).append(movement)

    entries = []
    for item in active_items:
        events = _to_events(withdrawals_by_item.get(item.id, []))
        rate = forecast.consumption_rate(events)
        reach = forecast.estimate_reach(stock=item.stock, rate=rate)
        entries.append(_ReachEntry(item=item, reach=reach))

    with_forecast = sorted(
        (entry for entry in entries if entry.reach.has_enough_data), key=_reach_sort_key
    )
    without_forecast = sorted(
        (entry for entry in entries if not entry.reach.has_enough_data),
        key=lambda entry: entry.item.position,
    )

    return templates.TemplateResponse(
        request,
        "history_overview.html",
        {"with_forecast": with_forecast, "without_forecast": without_forecast},
    )


@dataclass(frozen=True)
class _ItemForecast:
    rate: forecast.ConsumptionRate
    reach: forecast.ReachEstimate
    suggested_reorder_level: int | None


def _compute_item_forecast(connection: sqlite3.Connection, item: ItemRow) -> _ItemForecast:
    since = _since_iso(now=datetime.now(UTC), window_days=forecast.RATE_WINDOW_DAYS)
    withdrawals = movements_repo.list_unreverted_withdrawals_for_item_since(
        connection, item.id, since=since
    )
    rate = forecast.consumption_rate(_to_events(withdrawals))
    reach = forecast.estimate_reach(stock=item.stock, rate=rate)
    suggestion = forecast.suggested_reorder_level(
        rate=rate, lead_days=item.lead_days, pack_size=item.pack_size
    )
    return _ItemForecast(rate=rate, reach=reach, suggested_reorder_level=suggestion)


def _render_item_history(
    request: Request,
    connection: sqlite3.Connection,
    item: ItemRow,
    *,
    status_code: int = 200,
    takeover_error: str | None = None,
) -> HTMLResponse:
    item_forecast = (
        None if item.archived_at is not None else _compute_item_forecast(connection, item)
    )
    return templates.TemplateResponse(
        request,
        "item_history.html",
        {
            "item": item,
            "movements": movements_repo.list_for_item(connection, item.id, limit=None),
            "forecast": item_forecast,
            "takeover_error": takeover_error,
        },
        status_code=status_code,
    )


@router.get("/artikel/{item_id}/verlauf", response_class=HTMLResponse)
def item_history(request: Request, item_id: int) -> HTMLResponse:
    connection = request.app.state.db
    item = _require_item(connection, item_id)
    return _render_item_history(request, connection, item)


@router.post("/artikel/{item_id}/verlauf/uebernehmen", response_model=None)
def take_over_suggestion(request: Request, item_id: int) -> HTMLResponse | RedirectResponse:
    """Übernimmt den aktuell gültigen Schwellenvorschlag als `reorder_level`.

    Nimmt bewusst **keine** Formularwerte vom Client entgegen und rechnet den Vorschlag frisch aus
    der Datenbank nach — sonst könnte ein zwischenzeitlich veralteter oder manipulierter Wert
    geschrieben werden. Das deckt nebenbei den Fall ab, dass die Datenlage zwischen Seitenaufruf
    und Klick unter die Sperre gerutscht ist (z. B. durch ein Undo).
    """
    connection = request.app.state.db
    item = _require_item(connection, item_id)

    if item.archived_at is not None:
        return _render_item_history(
            request,
            connection,
            item,
            status_code=409,
            takeover_error=(
                f"„{item.name}“ ist archiviert. Ein Schwellenvorschlag lässt sich hier nicht "
                "mehr übernehmen."
            ),
        )

    item_forecast = _compute_item_forecast(connection, item)
    if not item_forecast.rate.has_enough_data or item_forecast.suggested_reorder_level is None:
        return _render_item_history(
            request,
            connection,
            item,
            status_code=409,
            takeover_error=(
                "Für diesen Artikel gibt es aktuell keinen Vorschlag — zu wenig Daten. "
                "Vielleicht hat sich das seit dem letzten Laden dieser Seite geändert."
            ),
        )

    suggested = item_forecast.suggested_reorder_level
    if suggested >= item.target_stock:
        return _render_item_history(
            request,
            connection,
            item,
            status_code=422,
            takeover_error=(
                f"Der Vorschlag ({suggested} {item.unit}) ist nicht kleiner als der aktuelle "
                f"Sollbestand ({item.target_stock} {item.unit}). Bitte zuerst den Sollbestand "
                "auf der Artikelseite erhöhen, dann erneut übernehmen."
            ),
        )

    items_repo.update_reorder_level(
        connection, item.id, reorder_level=suggested, updated_at=stock_service.utc_now_iso()
    )
    return RedirectResponse(f"/artikel/{item.id}/verlauf", status_code=303)
