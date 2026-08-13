"""Stammdaten-Export/-Import: `/stammdaten` (M9, Fragerunde Frage 3).

Als UI-Seite statt als CLI-Skript — gegen die ursprüngliche Empfehlung, aber mit dem Nutzer so
entschieden: eine Betriebsaufgabe, die trotzdem im Browser stattfindet, weil sie nicht an eine
Kommandozeile auf dem Pi gebunden sein soll. Kein API-Key (L12 gilt nur für den
Kurzbefehl-Export in `app/api/export.py`) — diese Seite gehört zur normalen Oberfläche.

Export liefert JSON **und** CSV zum Herunterladen; Import nimmt eine der beiden Dateien entgegen
und erkennt das Format an der Dateiendung. Das eigentliche Lesen/Schreiben liegt in
`app/services/stammdaten.py`, das Parsen/Formatieren in `app/domain/stammdaten.py` — diese Datei
ist nur Formular- und Fehlerdarstellung, wie `app/web/taxonomy.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.domain.stammdaten import StammdatenExport, StammdatenFormatError, from_csv, from_json
from app.domain.stammdaten import to_csv as stammdaten_to_csv
from app.domain.stammdaten import to_json as stammdaten_to_json
from app.services import stammdaten as stammdaten_service
from app.web.templating import templates

router = APIRouter()

_JSON_MEDIA_TYPE = "application/json; charset=utf-8"
_CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
_PARSERS = {"json": from_json, "csv": from_csv}

# Modul-Singleton statt `File(...)` direkt im Funktionsdefault (ruff B008) — dasselbe Muster wie
# `_ITEM_IDS_QUERY` in app/web/labels.py.
_FILE_UPLOAD = File(...)


def _download_filename(suffix: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"stammdaten-{timestamp}.{suffix}"


def _render_page(
    request: Request,
    *,
    status_code: int = 200,
    errors: list[str] | None = None,
) -> HTMLResponse:
    connection = request.app.state.db
    export = stammdaten_service.export_stammdaten(connection)
    context: dict[str, Any] = {
        "item_count": len(export.items),
        "category_count": len(export.categories),
        "store_count": len(export.stores),
        "errors": errors or [],
    }
    return templates.TemplateResponse(request, "stammdaten.html", context, status_code=status_code)


@router.get("/stammdaten", response_class=HTMLResponse)
def stammdaten_page(request: Request) -> HTMLResponse:
    return _render_page(request)


@router.get("/stammdaten/export.json", response_model=None)
def export_json(request: Request) -> Response:
    data = stammdaten_service.export_stammdaten(request.app.state.db)
    return Response(
        content=stammdaten_to_json(data),
        media_type=_JSON_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{_download_filename("json")}"'},
    )


@router.get("/stammdaten/export.csv", response_model=None)
def export_csv(request: Request) -> Response:
    data = stammdaten_service.export_stammdaten(request.app.state.db)
    return Response(
        content=stammdaten_to_csv(data),
        media_type=_CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{_download_filename("csv")}"'},
    )


def _detect_format(filename: str) -> str | None:
    if "." not in filename:
        return None
    suffix = filename.rsplit(".", 1)[-1].lower()
    return suffix if suffix in _PARSERS else None


def _parse_upload(filename: str, raw_bytes: bytes) -> StammdatenExport | list[str]:
    """Liefert die geparsten Stammdaten, oder eine Fehlerliste bei Fehlbedienung."""
    file_format = _detect_format(filename)
    if file_format is None:
        return [
            f"Unbekanntes Dateiformat „{filename or '(ohne Namen)'}“ — erwartet wird eine "
            ".json- oder .csv-Datei."
        ]

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ["Datei ist nicht als UTF-8-Text lesbar."]

    try:
        return _PARSERS[file_format](text)
    except StammdatenFormatError as error:
        return [str(error)]


@router.post("/stammdaten/import", response_model=None)
async def import_stammdaten_upload(
    request: Request, file: UploadFile = _FILE_UPLOAD
) -> HTMLResponse | RedirectResponse:
    raw_bytes = await file.read()
    parsed = _parse_upload(file.filename or "", raw_bytes)
    if isinstance(parsed, list):
        return _render_page(request, status_code=422, errors=parsed)

    try:
        stammdaten_service.import_stammdaten(request.app.state.db, parsed)
    except stammdaten_service.StammdatenImportRejectedError as error:
        return _render_page(request, status_code=409, errors=error.errors)

    return RedirectResponse("/stammdaten", status_code=303)
