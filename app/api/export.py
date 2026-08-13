"""Export-Schnittstelle für den Apple-Kurzbefehl, siehe docs/PLAN.md §6 und §7 (M4).

| Methode | Pfad                            | Zweck                                        |
| ------- | ------------------------------- | -------------------------------------------- |
| `GET`   | `/api/shopping-list`            | lesen **ohne Nebenwirkung** (Vorschau, Debug) |
| `POST`  | `/api/shopping-list/export`     | Abgleich, `exported_at`, Liste liefern        |

Der Kurzbefehl nutzt `POST`, weil der Aufruf einen Abgleich auslöst und protokolliert wird; ein
`GET` mit Nebenwirkung wäre genau der Fehler, den §5 vermeidet.

Als einziger Teil der App ist dieser Endpunkt authentifiziert (L12): Er ist der einzige, den ein
Gerät außerhalb des Browsers automatisiert aufruft. Der Schlüssel kommt aus dem Header
`X-API-Key` oder — weil sich das in Kurzbefehlen leichter zusammenbauen lässt — aus `?key=`.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.deps import DbConnection
from app.domain.grouping import MISC_LABEL, group_and_sort
from app.domain.pluralization import plural_unit
from app.domain.shopping import format_export_group_header, format_export_line, format_export_text
from app.repo import shopping_lists as lists_repo
from app.services import shopping as shopping_service

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

FORMAT_TEXT = "text"
FORMAT_JSON = "json"
_FORMATS = (FORMAT_TEXT, FORMAT_JSON)


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "status": "unauthorized",
            "detail": "Fehlender oder falscher API-Schlüssel. Erwartet wird der Header "
            "X-API-Key oder der Parameter ?key=.",
        },
    )


def _not_configured() -> JSONResponse:
    # Kein 401: Der Aufrufer hat nichts falsch gemacht, dem Dienst fehlt seine Konfiguration
    # (§8, HOMEKANBAN_API_KEY ist Pflicht). 503 sagt "vorübergehend nicht verfügbar" — und die
    # Ursache steht im Log des Pi, nicht in der Antwort ans Netz.
    logger.error(
        "HOMEKANBAN_API_KEY ist nicht gesetzt — der Export-Endpunkt verweigert den Dienst. "
        "Bitte einen Schlüssel in .env eintragen und den Container neu starten."
    )
    return JSONResponse(
        status_code=503,
        content={
            "status": "not_configured",
            "detail": "Der Export ist auf diesem Server nicht eingerichtet: "
            "HOMEKANBAN_API_KEY fehlt.",
        },
    )


def _invalid_format(value: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "status": "invalid_format",
            "detail": f"Unbekanntes Format „{value}“. Erlaubt sind text und json.",
        },
    )


def _authorize(request: Request, key: str | None) -> JSONResponse | None:
    """Liefert die Fehlerantwort, oder `None`, wenn der Aufruf durchgelassen wird."""
    configured: str | None = request.app.state.settings.api_key
    if not configured:
        return _not_configured()

    presented = request.headers.get("X-API-Key") or key
    if presented is None:
        return _unauthorized()

    # Zeitkonstanter Vergleich: Ein Vergleich mit `==` bricht beim ersten falschen Zeichen ab
    # und verrät über die Antwortzeit, wie viele Zeichen stimmten.
    if not secrets.compare_digest(presented, configured):
        return _unauthorized()
    return None


def _export_line_text(line: lists_repo.ShoppingListLineRow) -> str:
    return format_export_line(
        name=line.name_snapshot, quantity=line.suggested_qty, unit=line.unit_snapshot
    )


def _line_payload(line: lists_repo.ShoppingListLineRow) -> dict[str, Any]:
    return {
        "line_id": line.id,
        "item_id": line.item_id,
        "name": line.name_snapshot,
        "unit": line.unit_snapshot,
        "unit_display": (
            line.unit_snapshot if line.suggested_qty == 1 else plural_unit(line.unit_snapshot)
        ),
        "quantity": line.suggested_qty,
        "text": _export_line_text(line),
    }


def _render(
    list_row: lists_repo.ShoppingListRow | None,
    lines: list[lists_repo.ShoppingListLineRow],
    response_format: str,
) -> Response:
    # Gruppiert nach Laden, innerhalb nach Kategorie-Position (§9 M7 Definition of Done). Die
    # eingefrorenen store_snapshot/category_snapshot-Werte machen `ShoppingListLineRow` bereits
    # zu einem `Groupable` (M7, Frage 1 der Fragerunde).
    groups = group_and_sort(lines)
    # Eine einzelne "Sonstiges"-Gruppe heißt: keine Laden-/Kategoriezuordnung im ganzen Haushalt
    # vorhanden. Dann eine Überschriftszeile zu erzwingen wäre reine Zusatzarbeit im Kurzbefehl
    # ohne jeden Informationsgewinn (M7, Frage 2) — Überschriften erscheinen erst, sobald sie
    # tatsächlich etwas zu unterscheiden gibt.
    show_headers = len(groups) > 1 or (bool(groups) and groups[0].label != MISC_LABEL)

    if response_format == FORMAT_TEXT:
        text_lines: list[str] = []
        for group in groups:
            if show_headers:
                text_lines.append(format_export_group_header(group.label))
            text_lines.extend(_export_line_text(line) for line in group.entries)
        return PlainTextResponse(
            format_export_text(text_lines), media_type="text/plain; charset=utf-8"
        )

    payload: dict[str, Any] = {
        "list_id": list_row.id if list_row is not None else None,
        "created_at": list_row.created_at if list_row is not None else None,
        "exported_at": list_row.exported_at if list_row is not None else None,
        "export_count": list_row.export_count if list_row is not None else 0,
        "lines": [_line_payload(line) for line in lines],
        "groups": [
            {"label": group.label, "lines": [_line_payload(line) for line in group.entries]}
            for group in groups
        ],
    }
    return JSONResponse(status_code=200, content=payload)


def _open_lines(
    connection: sqlite3.Connection, list_row: lists_repo.ShoppingListRow | None
) -> list[lists_repo.ShoppingListLineRow]:
    """Nur offene Positionen gehören in den Export — Abgehaktes ist gekauft, Verworfenes weg."""
    if list_row is None:
        return []
    return [line for line in lists_repo.list_lines(connection, list_row.id) if line.is_open]


@router.get("/shopping-list", response_model=None)
def read_shopping_list(
    request: Request,
    connection: DbConnection,
    response_format: str = Query(FORMAT_TEXT, alias="format"),
    key: str | None = Query(None),
) -> Response:
    """Liest die offene Liste, **ohne** irgendetwas zu verändern: kein Abgleich, kein
    `exported_at`, kein `export_count`."""
    error = _authorize(request, key)
    if error is not None:
        return error
    if response_format not in _FORMATS:
        return _invalid_format(response_format)

    list_row = lists_repo.get_open_list(connection)
    return _render(list_row, _open_lines(connection, list_row), response_format)


@router.post("/shopping-list/export", response_model=None)
def export_shopping_list(
    request: Request,
    connection: DbConnection,
    response_format: str = Query(FORMAT_TEXT, alias="format"),
    key: str | None = Query(None),
) -> Response:
    """Gleicht ab, protokolliert den Export und liefert die Liste — der Aufruf des Kurzbefehls.

    Gibt es nichts zu kaufen, entsteht trotzdem eine (leere) offene Liste und die Antwort ist
    leer. Das ist ein gültiges Ergebnis, kein Fehler (§6).
    """
    error = _authorize(request, key)
    if error is not None:
        return error
    if response_format not in _FORMATS:
        return _invalid_format(response_format)

    list_row, _ = shopping_service.create_or_reconcile_list(connection)
    list_row = shopping_service.mark_exported(connection, list_row.id)
    return _render(list_row, _open_lines(connection, list_row), response_format)
