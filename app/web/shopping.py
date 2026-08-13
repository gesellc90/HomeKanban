"""Einkaufslisten-Router: ansehen, erzeugen, abhaken, zurücknehmen, abschließen.

Siehe docs/PLAN.md §6 und §7 (M4). Zwei Dinge prägen diese Datei:

**Abhaken und Zurücknehmen antworten mit einem HTMX-Partial der Zeile** (§7). Hier lohnt sich die
Teilaktualisierung, anders als im 303-Flow von M3: Wer zwölf Positionen bucht, soll nicht zwölf
Mal die ganze Seite neu geladen bekommen. Die Positionsanzahl oben ändert sich mit — dafür hängt
an der Antwort ein zweites Element mit `hx-swap-oob`.

**Ohne JavaScript bleibt alles bedienbar** (CLAUDE.md §4, keine harte JS-Abhängigkeit). Jede
Aktion ist ein echtes `<form method="post">`; die `hx-post`-Attribute liegen nur darüber. Fehlt
HTMX, sendet der Browser normal ab und bekommt `303 See Other` auf `/liste` — derselbe Weg wie in
M2/M3. Erkannt wird das am Header `HX-Request`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import DbConnection
from app.domain.grouping import Group, group_and_sort
from app.domain.pluralization import format_quantity
from app.repo import shopping_lists as lists_repo
from app.services import shopping as shopping_service
from app.web.templating import templates

router = APIRouter()

LIST_PATH = "/liste"


@dataclass(frozen=True)
class LineView:
    line: lists_repo.ShoppingListLineRow
    quantity_text: str
    purchased_text: str | None
    error: str | None = None
    note: str | None = None

    # Leitet an die Zeile weiter, damit ein `LineView` selbst das `Groupable`-Protokoll aus
    # `app/domain/grouping.py` erfüllt (M7) — die Gruppierung in `/liste` arbeitet direkt mit den
    # bereits für die Anzeige aufbereiteten Views, ohne einen zweiten Durchlauf über die Zeilen.

    @property
    def store_name(self) -> str | None:
        return self.line.store_name

    @property
    def store_position(self) -> int | None:
        return self.line.store_position

    @property
    def category_name(self) -> str | None:
        return self.line.category_name

    @property
    def category_position(self) -> int | None:
        return self.line.category_position

    @property
    def sort_position(self) -> int:
        return self.line.sort_position


@dataclass(frozen=True)
class ListSummary:
    total: int
    open: int
    checked: int


def _line_view(
    line: lists_repo.ShoppingListLineRow, *, error: str | None = None, note: str | None = None
) -> LineView:
    return LineView(
        line=line,
        quantity_text=format_quantity(quantity=line.suggested_qty, unit=line.unit_snapshot),
        purchased_text=(
            format_quantity(quantity=line.purchased_qty, unit=line.unit_snapshot)
            if line.purchased_qty is not None
            else None
        ),
        error=error,
        note=note,
    )


def _summary(lines: list[lists_repo.ShoppingListLineRow]) -> ListSummary:
    relevant = [line for line in lines if not line.is_dropped]
    checked = sum(1 for line in relevant if line.is_checked)
    return ListSummary(total=len(relevant), open=len(relevant) - checked, checked=checked)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _render_error_page(
    request: Request, *, status_code: int, title: str, message: str
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "shopping_error.html",
        {"title": title, "message": message},
        status_code=status_code,
    )


def _render_page(
    request: Request,
    connection: sqlite3.Connection,
    *,
    status_code: int = 200,
    error_line_id: int | None = None,
    error: str | None = None,
    note: str | None = None,
) -> HTMLResponse:
    list_row = lists_repo.get_open_list(connection)
    all_lines = lists_repo.list_lines(connection, list_row.id) if list_row is not None else []
    views = [
        _line_view(
            line,
            error=error if line.id == error_line_id else None,
            note=note if line.id == error_line_id else None,
        )
        for line in all_lines
        if not line.is_dropped
    ]
    # Gruppiert nach Laden, innerhalb nach Kategorie-Position (§7/§9 M7) — dieselbe Logik wie im
    # Export, hier auf den bereits für die Anzeige aufbereiteten `LineView`s.
    groups: tuple[Group[LineView], ...] = group_and_sort(views)

    context: dict[str, Any] = {
        "shopping_list": list_row,
        "views": views,
        "groups": groups,
        "summary": _summary(all_lines),
    }
    return templates.TemplateResponse(
        request, "shopping_list.html", context, status_code=status_code
    )


def _render_line(
    request: Request,
    connection: sqlite3.Connection,
    line_id: int,
    *,
    status_code: int = 200,
    error: str | None = None,
    note: str | None = None,
) -> HTMLResponse:
    """Die HTMX-Antwort: die eine Zeile, plus die Aktionsleiste als Out-of-Band-Tausch."""
    line = lists_repo.get_line(connection, line_id)
    assert line is not None  # Der Aufrufer hat die Position bereits geprüft.
    list_row = lists_repo.get_list(connection, line.list_id)
    assert list_row is not None

    context: dict[str, Any] = {
        "view": _line_view(line, error=error, note=note),
        "shopping_list": list_row,
        "summary": _summary(lists_repo.list_lines(connection, line.list_id)),
        "oob_actions": True,
        "oob": True,
    }
    return templates.TemplateResponse(
        request, "shopping_line.html", context, status_code=status_code
    )


def _respond(
    request: Request,
    connection: sqlite3.Connection,
    line_id: int,
    *,
    status_code: int = 200,
    error: str | None = None,
    note: str | None = None,
) -> HTMLResponse | RedirectResponse:
    """HTMX bekommt das Zeilen-Partial, ein normaler Browser die Weiterleitung auf `/liste`."""
    if lists_repo.get_line(connection, line_id) is None:
        # Kann nur die Mengenprüfung erreichen: Sie schlägt zu, bevor der Dienst die Position
        # überhaupt nachschlägt. Ohne diese Prüfung liefe eine unsinnige Menge auf einer
        # unbekannten Zeilen-ID in eine 500er-Seite.
        return _unknown_line(request)
    if _is_htmx(request):
        return _render_line(
            request, connection, line_id, status_code=status_code, error=error, note=note
        )
    if error is None and note is None:
        return RedirectResponse(LIST_PATH, status_code=303)
    return _render_page(
        request,
        connection,
        status_code=status_code,
        error_line_id=line_id,
        error=error,
        note=note,
    )


def _parse_purchased_qty(raw: str) -> int | None:
    """Leeres Feld heißt „auf den Sollbestand“ (§6); alles andere muss eine ganze Zahl sein."""
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        raise shopping_service.InvalidQuantityError(
            f"„{stripped}“ ist keine Menge. Bitte eine ganze Zahl eintragen oder das Feld leer "
            "lassen, dann wird auf den Sollbestand gebucht."
        ) from None


@router.get(LIST_PATH, response_class=HTMLResponse)
def shopping_list_page(request: Request, connection: DbConnection) -> HTMLResponse:
    """Die offene Liste zum Abhaken. Gibt es keine, ist das kein 404, sondern eine freundliche
    leere Seite mit „Liste erzeugen“ — der Normalfall zwischen zwei Einkäufen."""
    return _render_page(request, connection)


@router.post("/liste/erzeugen")
def create_list(connection: DbConnection) -> RedirectResponse:
    """Legt die offene Liste an, falls nötig, und gleicht sie ab (§6). Ein zweiter Aufruf erzeugt
    keine zweite Liste, sondern aktualisiert die bestehende."""
    shopping_service.create_or_reconcile_list(connection)
    return RedirectResponse(LIST_PATH, status_code=303)


@router.post("/liste/{list_id}/zeilen/{line_id}/abhaken", response_model=None)
def check_line(
    request: Request,
    list_id: int,
    line_id: int,
    connection: DbConnection,
    purchased_qty: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    try:
        quantity = _parse_purchased_qty(purchased_qty)
        result = shopping_service.check_line(
            connection, list_id=list_id, line_id=line_id, purchased_qty=quantity
        )
    except shopping_service.InvalidQuantityError as error:
        return _respond(request, connection, line_id, status_code=422, error=str(error))
    except shopping_service.LineAlreadyCheckedError:
        return _respond(
            request,
            connection,
            line_id,
            status_code=409,
            error="Diese Position war schon abgehakt — es wurde nichts noch einmal gebucht.",
        )
    except shopping_service.LineDroppedError:
        return _respond(
            request,
            connection,
            line_id,
            status_code=409,
            error="Diese Position steht nicht mehr auf der Liste und wurde nicht gebucht.",
        )
    except shopping_service.LineNotFoundError:
        return _unknown_line(request)
    except shopping_service.ShoppingListNotFoundError:
        return _unknown_list(request)
    except shopping_service.ListClosedError:
        return _closed_list(request)

    return _respond(request, connection, line_id, note=result.note)


@router.post("/liste/{list_id}/zeilen/{line_id}/zuruecknehmen", response_model=None)
def uncheck_line(
    request: Request,
    list_id: int,
    line_id: int,
    connection: DbConnection,
) -> HTMLResponse | RedirectResponse:
    try:
        shopping_service.uncheck_line(connection, list_id=list_id, line_id=line_id)
    except shopping_service.LineNotFoundError:
        return _unknown_line(request)
    except shopping_service.ShoppingListNotFoundError:
        return _unknown_list(request)
    except shopping_service.ListClosedError:
        return _closed_list(request)

    return _respond(request, connection, line_id)


@router.post("/liste/{list_id}/alles-gekauft", response_model=None)
def check_all_lines(
    request: Request, list_id: int, connection: DbConnection
) -> HTMLResponse | RedirectResponse:
    """„Alles gekauft“ (O1, R2): der Standardweg nach dem Einkauf, ein Tap für die ganze Liste."""
    try:
        shopping_service.check_all_open_lines(connection, list_id)
    except shopping_service.ShoppingListNotFoundError:
        return _unknown_list(request)
    except shopping_service.ListClosedError:
        return _closed_list(request)

    return RedirectResponse(LIST_PATH, status_code=303)


@router.post("/liste/{list_id}/abschliessen", response_model=None)
def complete_list(
    request: Request, list_id: int, connection: DbConnection
) -> HTMLResponse | RedirectResponse:
    try:
        shopping_service.complete_list(connection, list_id)
    except shopping_service.ShoppingListNotFoundError:
        return _unknown_list(request)
    except shopping_service.ListClosedError:
        return _closed_list(request)

    return RedirectResponse(LIST_PATH, status_code=303)


def _unknown_list(request: Request) -> HTMLResponse:
    return _render_error_page(
        request,
        status_code=404,
        title="Einkaufsliste nicht gefunden",
        message="Diese Einkaufsliste existiert nicht (mehr).",
    )


def _closed_list(request: Request) -> HTMLResponse:
    return _render_error_page(
        request,
        status_code=409,
        title="Einkauf bereits abgeschlossen",
        message=(
            "Diese Einkaufsliste ist abgeschlossen und lässt sich nicht mehr ändern. Artikel, "
            "die noch fehlen, stehen wieder im Nachkaufen und kommen mit der nächsten Liste."
        ),
    )


def _unknown_line(request: Request) -> HTMLResponse:
    return _render_error_page(
        request,
        status_code=404,
        title="Position nicht gefunden",
        message="Diese Position gehört nicht zu dieser Einkaufsliste oder existiert nicht (mehr).",
    )
