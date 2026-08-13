"""Pflegeseiten für Kategorien und Läden: `GET`/`POST /kategorien`, `GET`/`POST /laeden`.

Siehe docs/PLAN.md §7 (M7). Beide Seiten sind bis auf Text und Pfad identisch — angelegt,
umbenannt, umsortiert wird nach demselben Muster wie in `app/repo/taxonomy.py`. Die Reihenfolge
ist hier keine Kosmetik: Sie bestimmt später den Weg der Einkaufsliste durch den Laden (§6, §9).

**Kein Drag & Drop** (L4 lehnt es schon fürs Board ab; für diese Nebenseite wäre eine
JS-Bibliothek erst recht nicht zu rechtfertigen) — Hoch/Runter-Buttons genügen, Trefferflächen
≥ 44 px (CLAUDE.md §8).

**Löschen** (Frage 3 der M7-Fragerunde, entschieden): kein Archivieren, keine Migration — ein
Eintrag lässt sich löschen, solange ihm kein Artikel mehr zugeordnet ist (auch kein archivierter,
siehe `taxonomy_repo.count_assigned_items`); sonst eine deutsche Meldung mit der Zahl der
betroffenen Artikel statt eines `IntegrityError`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import DbConnection
from app.repo import taxonomy as taxonomy_repo
from app.web.templating import templates

router = APIRouter()

TEMPLATE = "taxonomy_list.html"


@dataclass(frozen=True)
class _TaxonomyKind:
    table: taxonomy_repo.TableName
    base_path: str
    title: str
    label: str  # "Kategorie" / "Laden", für Meldungen


_CATEGORY = _TaxonomyKind(
    table="categories", base_path="/kategorien", title="Kategorien", label="Kategorie"
)
_STORE = _TaxonomyKind(table="stores", base_path="/laeden", title="Läden", label="Laden")


def _duplicate_name_message(kind: _TaxonomyKind, name: str) -> str:
    return f"Der Name „{name}“ ist bereits als {kind.label} vergeben."


def _duplicate_marker(kind: _TaxonomyKind) -> str:
    return f"{kind.table}.name"


def _render_list(
    request: Request,
    connection: sqlite3.Connection,
    kind: _TaxonomyKind,
    *,
    status_code: int = 200,
    errors: list[str] | None = None,
    new_name: str = "",
) -> HTMLResponse:
    context: dict[str, Any] = {
        "title": kind.title,
        "label": kind.label,
        "base_path": kind.base_path,
        "entries": taxonomy_repo.list_all(connection, kind.table),
        "errors": errors or [],
        "new_name": new_name,
    }
    return templates.TemplateResponse(request, TEMPLATE, context, status_code=status_code)


def _unknown_entry(request: Request, kind: _TaxonomyKind) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "taxonomy_error.html",
        {
            "title": f"{kind.label} nicht gefunden",
            "message": f"Diese {kind.label} existiert nicht (mehr).",
            "back_link": kind.base_path,
        },
        status_code=404,
    )


def _create(
    request: Request, connection: sqlite3.Connection, kind: _TaxonomyKind, name: str
) -> HTMLResponse | RedirectResponse:
    clean_name = name.strip()
    if not clean_name:
        return _render_list(
            request, connection, kind, status_code=422, errors=["Name darf nicht leer sein."]
        )

    try:
        taxonomy_repo.insert(
            connection,
            kind.table,
            name=clean_name,
            position=taxonomy_repo.next_position(connection, kind.table),
        )
    except sqlite3.IntegrityError as error:
        if _duplicate_marker(kind) not in str(error):
            raise
        return _render_list(
            request,
            connection,
            kind,
            status_code=422,
            errors=[_duplicate_name_message(kind, clean_name)],
            new_name=clean_name,
        )

    return RedirectResponse(kind.base_path, status_code=303)


def _rename(
    request: Request, connection: sqlite3.Connection, kind: _TaxonomyKind, entry_id: int, name: str
) -> HTMLResponse | RedirectResponse:
    if taxonomy_repo.get_by_id(connection, kind.table, entry_id) is None:
        return _unknown_entry(request, kind)

    clean_name = name.strip()
    if not clean_name:
        return _render_list(
            request, connection, kind, status_code=422, errors=["Name darf nicht leer sein."]
        )

    try:
        taxonomy_repo.rename(connection, kind.table, entry_id, name=clean_name)
    except sqlite3.IntegrityError as error:
        if _duplicate_marker(kind) not in str(error):
            raise
        return _render_list(
            request,
            connection,
            kind,
            status_code=422,
            errors=[_duplicate_name_message(kind, clean_name)],
        )

    return RedirectResponse(kind.base_path, status_code=303)


def _move(
    request: Request,
    connection: sqlite3.Connection,
    kind: _TaxonomyKind,
    entry_id: int,
    *,
    up: bool,
) -> HTMLResponse | RedirectResponse:
    entries = taxonomy_repo.list_all(connection, kind.table)
    index = next((i for i, entry in enumerate(entries) if entry.id == entry_id), None)
    if index is None:
        return _unknown_entry(request, kind)

    neighbor_index = index - 1 if up else index + 1
    # Über die Listengrenze hinaus umsortieren ist kein Fehler, sondern ein No-Op: das erste
    # Element kann nicht weiter nach oben, das letzte nicht weiter nach unten (CLAUDE.md §8,
    # kein Stacktrace bei Fehlbedienung). Die Reihenfolge bleibt dabei unverändert und lückenlos.
    if 0 <= neighbor_index < len(entries):
        entry = entries[index]
        neighbor = entries[neighbor_index]
        taxonomy_repo.swap_positions(
            connection,
            kind.table,
            first_id=entry.id,
            first_position=entry.position,
            second_id=neighbor.id,
            second_position=neighbor.position,
        )

    return RedirectResponse(kind.base_path, status_code=303)


def _delete(
    request: Request, connection: sqlite3.Connection, kind: _TaxonomyKind, entry_id: int
) -> HTMLResponse | RedirectResponse:
    entry = taxonomy_repo.get_by_id(connection, kind.table, entry_id)
    if entry is None:
        return _unknown_entry(request, kind)

    assigned = taxonomy_repo.count_assigned_items(connection, kind.table, entry_id)
    if assigned > 0:
        article = "einem" if assigned == 1 else f"{assigned}"
        noun = "Artikel" if assigned == 1 else "Artikeln"
        return _render_list(
            request,
            connection,
            kind,
            status_code=422,
            errors=[
                f"„{entry.name}“ ist noch {article} {noun} zugeordnet und kann nicht gelöscht "
                "werden. Artikel zuerst einer anderen Zuordnung geben oder archivieren."
            ],
        )

    taxonomy_repo.delete(connection, kind.table, entry_id)
    return RedirectResponse(kind.base_path, status_code=303)


def _register(kind: _TaxonomyKind) -> None:
    # `kind` ist eine lokale Variable dieses Funktionsaufrufs — jeder der zwei Aufrufe
    # (Kategorien, Läden) bekommt seinen eigenen Aufrufrahmen, die verschachtelten Routen binden
    # also an ihr jeweils eigenes `kind`. Das ist kein Closure-in-Schleife-Fallstrick, weil hier
    # keine gemeinsame Schleifenvariable wiederverwendet wird.

    @router.get(kind.base_path, response_class=HTMLResponse, name=f"{kind.table}_list")
    def list_page(request: Request, connection: DbConnection) -> HTMLResponse:
        return _render_list(request, connection, kind)

    @router.post(kind.base_path, response_model=None, name=f"{kind.table}_create")
    def create(
        request: Request,
        connection: DbConnection,
        name: str = Form(""),
    ) -> HTMLResponse | RedirectResponse:
        return _create(request, connection, kind, name)

    @router.post(f"{kind.base_path}/{{entry_id}}", response_model=None, name=f"{kind.table}_rename")
    def rename(
        request: Request,
        entry_id: int,
        connection: DbConnection,
        name: str = Form(""),
    ) -> HTMLResponse | RedirectResponse:
        return _rename(request, connection, kind, entry_id, name)

    @router.post(
        f"{kind.base_path}/{{entry_id}}/hoch", response_model=None, name=f"{kind.table}_up"
    )
    def move_up(
        request: Request, entry_id: int, connection: DbConnection
    ) -> HTMLResponse | RedirectResponse:
        return _move(request, connection, kind, entry_id, up=True)

    @router.post(
        f"{kind.base_path}/{{entry_id}}/runter", response_model=None, name=f"{kind.table}_down"
    )
    def move_down(
        request: Request, entry_id: int, connection: DbConnection
    ) -> HTMLResponse | RedirectResponse:
        return _move(request, connection, kind, entry_id, up=False)

    @router.post(
        f"{kind.base_path}/{{entry_id}}/loeschen",
        response_model=None,
        name=f"{kind.table}_delete",
    )
    def delete(
        request: Request, entry_id: int, connection: DbConnection
    ) -> HTMLResponse | RedirectResponse:
        return _delete(request, connection, kind, entry_id)


_register(_CATEGORY)
_register(_STORE)
