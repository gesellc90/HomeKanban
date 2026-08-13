"""Etiketten-Router: Einzel-QR, Auswahl, Bogenansicht, Kalibrierung (docs/PLAN.md §7, M5).

Alles hier ist **lesend**. Etiketten verändern keinen Bestand, deshalb gibt es keinen einzigen
POST — die Auswahl reist als Query-Parameter zur Druckansicht, damit ein Ausdruck wiederholbar,
verlinkbar und per Reload harmlos ist.

Fehlbedienung endet nie in einem Stacktrace (CLAUDE.md §8): unbekannte oder archivierte Artikel,
leere Auswahl und unsinnige Rasterwerte werden alle als verständliche deutsche Seite mit einem
Nicht-500-Status beantwortet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from app.deps import DbConnection
from app.domain import labels as labels_domain
from app.repo import items as items_repo
from app.services import labels as labels_service
from app.web.templating import templates

router = APIRouter()

# Die Codes sind je Artikel stabil: `qr_token` überlebt jede Umbenennung (R9), und der einzige
# weitere Bestandteil ist `BASE_URL`. Eine Stunde Caching macht die Detailseite und die
# Bogenansicht flott, ohne eine Änderung von `BASE_URL` während der Einrichtung (M6) einen ganzen
# Tag lang zu verstecken. Bewusst kein `immutable`: Genau dann wäre die Änderung nicht mehr
# einzufangen, und der Aufwand — ein paar hundert Byte neu erzeugen — ist ohnehin winzig.
_QR_CACHE_CONTROL = "public, max-age=3600"

# Mehrfach vorkommender Query-Parameter `?item_id=1&item_id=2`. Als Modul-Singleton, weil FastAPI
# den Aufruf im Default braucht, ruff ihn dort aber (zu Recht) nicht sehen will — `default_factory`
# statt eines geteilten `[]` sorgt zusätzlich dafür, dass keine Liste zwischen Anfragen wandert.
_ITEM_IDS_QUERY = Query(default_factory=list)


def _qr_error(request: Request, *, status_code: int, title: str, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "scan_error.html", {"title": title, "message": message}, status_code=status_code
    )


def _active_item_or_error(
    request: Request, connection: sqlite3.Connection, item_id: int
) -> items_repo.ItemRow | HTMLResponse:
    """Ein Etikett gibt es nur für einen aktiven Artikel.

    Für **archivierte** Artikel wird bewusst kein Code ausgeliefert, sondern `410 Gone`: Der Scan
    eines solchen Etiketts endet in `app/web/scan.py` ohnehin bei „Artikel archiviert“, ein
    frisch gedrucktes Etikett dafür wäre also von vornherein ein totes Etikett. §4 Regel 4
    („archivierte Artikel erscheinen nirgends“) verlangt dasselbe.
    """
    item = items_repo.get_by_id(connection, item_id)
    if item is None:
        return _qr_error(
            request,
            status_code=404,
            title="Artikel nicht gefunden",
            message="Zu dieser Artikelnummer gibt es keinen Artikel.",
        )
    if item.archived_at is not None:
        return _qr_error(
            request,
            status_code=410,
            title="Artikel archiviert",
            message=(
                f"„{item.name}“ ist archiviert — dafür gibt es kein Etikett. Ein Scan des Codes "
                "würde nichts buchen. Zuerst reaktivieren, dann drucken."
            ),
        )
    return item


@router.get("/artikel/{item_id}/qr.svg", response_model=None)
def item_qr_svg(request: Request, item_id: int, connection: DbConnection) -> Response:
    item = _active_item_or_error(request, connection, item_id)
    if isinstance(item, HTMLResponse):
        return item

    url = labels_service.scan_url(request.app.state.settings.base_url, item.qr_token)
    return Response(
        content=labels_service.qr_svg_document(url),
        media_type="image/svg+xml",
        headers={"Cache-Control": _QR_CACHE_CONTROL},
    )


@router.get("/artikel/{item_id}/qr.png", response_model=None)
def item_qr_png(request: Request, item_id: int, connection: DbConnection) -> Response:
    item = _active_item_or_error(request, connection, item_id)
    if isinstance(item, HTMLResponse):
        return item

    url = labels_service.scan_url(request.app.state.settings.base_url, item.qr_token)
    return Response(
        content=labels_service.qr_png_bytes(url),
        media_type="image/png",
        headers={
            "Cache-Control": _QR_CACHE_CONTROL,
            # Der Dateiname landet im Download-Ordner — dort hilft der Artikelname mehr als
            # „qr.png“. `item_id` bleibt als eindeutiger Teil davor.
            "Content-Disposition": f'inline; filename="qr-{item_id}.png"',
        },
    )


@dataclass(frozen=True)
class PlacedLabel:
    """Ein Etikett mit seiner Position auf dem Bogen, in Millimetern.

    Hier — und nur hier — werden aus Zeile und Spalte der Domäne Millimeter. Die Domäne kennt
    Zellen, das Papier kennt Maße; die Umrechnung ist Darstellung und gehört deshalb in die
    Web-Schicht (docs/PLAN.md §2). Absolute Positionierung statt CSS-Grid ist Absicht: Sie ist
    das, was das Papier vorgibt, und sie macht einen Seitenumbruch mitten in einer Etikettenzeile
    strukturell unmöglich.
    """

    left_mm: float
    top_mm: float
    label: labels_service.Label | None  # None = Zelle bleibt leer


def _place(
    sheet: labels_domain.LabelSheet,
    *,
    grid: labels_domain.LabelGrid,
    labels: list[labels_service.Label],
) -> list[PlacedLabel]:
    placed: list[PlacedLabel] = []
    for slot in sheet.slots:
        placed.append(
            PlacedLabel(
                left_mm=round(
                    grid.margin_left_mm + slot.column * (grid.label_width_mm + grid.column_gap_mm),
                    3,
                ),
                top_mm=round(
                    grid.margin_top_mm + slot.row * (grid.label_height_mm + grid.row_gap_mm), 3
                ),
                label=None if slot.label_index is None else labels[slot.label_index],
            )
        )
    return placed


@dataclass(frozen=True)
class _GridForm:
    """Die Rasterwahl, wie sie als Query-Parameter durch beide Seiten reist.

    Voreinstellung ist `DEFAULT_GRID_KEY`; die freien Millimeterfelder sind mit den Werten der
    Voreinstellung vorbelegt, damit das Formular auch beim Umschalten auf „frei einstellbar“
    sinnvolle Zahlen zeigt statt Nullen.
    """

    grid_key: str
    grid: labels_domain.LabelGrid


def _grid_from_query(
    *,
    grid_key: str,
    columns: int | None,
    rows: int | None,
    label_width: float | None,
    label_height: float | None,
    margin_left: float | None,
    margin_top: float | None,
    column_gap: float | None,
    row_gap: float | None,
) -> _GridForm:
    """Leitet das Raster aus den Query-Parametern ab.

    Ein bekannter Preset-Schlüssel gewinnt gegen die Einzelfelder — beim frei einstellbaren Raster
    (oder einem unbekannten Schlüssel) zählen die Felder, jeweils gegen die Voreinstellung
    aufgefüllt. Geprüft wird das Ergebnis erst von `validate_grid`; hier wird nur eingesammelt,
    damit auch ein unsinniges Raster noch als Formular mit Fehlermeldung zurückkommen kann.
    """
    preset = labels_domain.preset_by_key(grid_key)
    if preset is not None:
        return _GridForm(grid_key=preset.key, grid=preset.grid)

    fallback = labels_domain.default_grid()
    return _GridForm(
        grid_key=labels_domain.CUSTOM_GRID_KEY,
        grid=labels_domain.LabelGrid(
            columns=fallback.columns if columns is None else columns,
            rows=fallback.rows if rows is None else rows,
            label_width_mm=fallback.label_width_mm if label_width is None else label_width,
            label_height_mm=fallback.label_height_mm if label_height is None else label_height,
            margin_left_mm=fallback.margin_left_mm if margin_left is None else margin_left,
            margin_top_mm=fallback.margin_top_mm if margin_top is None else margin_top,
            column_gap_mm=fallback.column_gap_mm if column_gap is None else column_gap,
            row_gap_mm=fallback.row_gap_mm if row_gap is None else row_gap,
        ),
    )


@router.get("/etiketten", response_class=HTMLResponse)
def label_selection(
    request: Request,
    connection: DbConnection,
    item_id: list[int] = _ITEM_IDS_QUERY,
    grid_key: str = Query(default=labels_domain.DEFAULT_GRID_KEY),
    columns: int | None = Query(default=None),
    rows: int | None = Query(default=None),
    label_width: float | None = Query(default=None),
    label_height: float | None = Query(default=None),
    margin_left: float | None = Query(default=None),
    margin_top: float | None = Query(default=None),
    column_gap: float | None = Query(default=None),
    row_gap: float | None = Query(default=None),
) -> HTMLResponse:
    """Auswahl der Artikel und des Rasters. Nur nicht archivierte Artikel stehen zur Wahl (§9)."""
    items = labels_service.selectable_items(connection)

    form = _grid_from_query(
        grid_key=grid_key,
        columns=columns,
        rows=rows,
        label_width=label_width,
        label_height=label_height,
        margin_left=margin_left,
        margin_top=margin_top,
        column_gap=column_gap,
        row_gap=row_gap,
    )

    return templates.TemplateResponse(
        request,
        "labels_select.html",
        {
            "items": items,
            "presets": labels_domain.GRID_PRESETS,
            "custom_key": labels_domain.CUSTOM_GRID_KEY,
            "grid_key": form.grid_key,
            "grid": form.grid,
            "preselected": set(item_id),
            "errors": labels_domain.validate_grid(form.grid),
        },
    )


def _labels_error(request: Request, *, status_code: int, title: str, message: str) -> HTMLResponse:
    """Fehlerseite der Druckansicht — mit dem Rückweg zur Auswahl statt einer Sackgasse."""
    return templates.TemplateResponse(
        request,
        "labels_error.html",
        {"title": title, "message": message},
        status_code=status_code,
    )


@router.get("/etiketten/druck", response_class=HTMLResponse)
def label_sheet(
    request: Request,
    connection: DbConnection,
    item_id: list[int] = _ITEM_IDS_QUERY,
    grid_key: str = Query(default=labels_domain.DEFAULT_GRID_KEY),
    columns: int | None = Query(default=None),
    rows: int | None = Query(default=None),
    label_width: float | None = Query(default=None),
    label_height: float | None = Query(default=None),
    margin_left: float | None = Query(default=None),
    margin_top: float | None = Query(default=None),
    column_gap: float | None = Query(default=None),
    row_gap: float | None = Query(default=None),
) -> HTMLResponse:
    """Druckoptimierte Bogenansicht: kein Kopf, keine Navigation, nur Papier."""
    form = _grid_from_query(
        grid_key=grid_key,
        columns=columns,
        rows=rows,
        label_width=label_width,
        label_height=label_height,
        margin_left=margin_left,
        margin_top=margin_top,
        column_gap=column_gap,
        row_gap=row_gap,
    )

    grid_errors = labels_domain.validate_grid(form.grid)
    if grid_errors:
        return _labels_error(
            request,
            status_code=422,
            title="Raster nicht druckbar",
            message=" ".join(grid_errors),
        )

    if not item_id:
        return _labels_error(
            request,
            status_code=422,
            title="Nichts ausgewählt",
            message=(
                "Für den Druck wurde kein Artikel ausgewählt. Bitte auf der Auswahlseite "
                "mindestens einen Artikel anhaken."
            ),
        )

    labels, unknown = labels_service.collect_labels(
        connection, item_ids=item_id, base_url=request.app.state.settings.base_url
    )
    if unknown:
        numbers = ", ".join(str(number) for number in unknown)
        return _labels_error(
            request,
            status_code=404,
            title="Artikel nicht druckbar",
            message=(
                f"Diese Artikelnummern gibt es nicht oder sie sind archiviert: {numbers}. "
                "Archivierte Artikel bekommen kein Etikett — ein Scan würde nichts buchen."
            ),
        )

    sheets = labels_domain.paginate_labels(label_count=len(labels), grid=form.grid)

    return templates.TemplateResponse(
        request,
        "labels_sheet.html",
        {
            "label_count": len(labels),
            "grid": form.grid,
            "placed_sheets": [
                (sheet.number, _place(sheet, grid=form.grid, labels=labels)) for sheet in sheets
            ],
        },
    )


@router.get("/etiketten/kalibrierung", response_class=HTMLResponse)
def label_calibration(request: Request) -> HTMLResponse:
    """Maßstabskontrolle vor dem Druck — die Absicherung, auf der ADR 0004 aufbaut."""
    return templates.TemplateResponse(request, "labels_calibration.html", {})
