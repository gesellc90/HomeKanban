"""Stammdaten-Export/-Import: liest/schreibt die Datenbank (M9, Fragerunde Frage 3).

Das Format-Übersetzen (JSON/CSV ↔ `StammdatenExport`) übernimmt `app/domain/stammdaten.py` — hier
steht nur, was diese Datenklassen mit der Datenbank zu tun haben.

**Import ist atomar und alles-oder-nichts** (docs/PLAN.md §9, Fragerunde Frage 3: "Import legt nur
an, was noch nicht existiert, verweigert bei Namenskonflikt … und rührt Bestehendes nicht an"):
Erst werden **alle** Probleme gesammelt — Namenskonflikte mit vorhandenen Kategorien/Läden/
Artikeln, Duplikate innerhalb der Datei selbst, Verweise auf nirgends deklarierte Kategorien/
Läden, verletzte Domänenregeln (`app/domain/validation.py`) —, dann wird entweder alles
geschrieben oder nichts. Artikel entstehen über `app.services.stock.book_create_item()` (nie per
Rohzugriff), damit jeder importierte Artikel seine `opening`-Bewegung bekommt und die
Journal-Invariante (`SUM(delta) == stock`, L2) hält.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.db import transaction
from app.domain.stammdaten import StammdatenExport, StammdatenItem
from app.domain.validation import ItemInput, validate_item
from app.repo import items as items_repo
from app.repo import taxonomy as taxonomy_repo
from app.services import stock as stock_service


class StammdatenImportRejectedError(Exception):
    """Der Import wurde vollständig verweigert — nichts wurde geschrieben.

    Sammelt alle gefundenen Probleme (Namenskonflikte, Duplikate, unbekannte Verweise,
    Domänenregeln) statt beim ersten Fehler abzubrechen, damit eine korrigierte Datei nicht
    mehrmals hintereinander an neuen Einzelfehlern scheitert.
    """

    def __init__(self, errors: list[str]) -> None:
        if not errors:
            raise ValueError("errors darf nicht leer sein")
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class StammdatenImportResult:
    category_count: int
    store_count: int
    item_count: int


def export_stammdaten(connection: sqlite3.Connection) -> StammdatenExport:
    """Nur **aktive** Artikel (app/domain/stammdaten.py Moduldoc) — archivierte gehören nicht zum
    "aktuellen Haushalt", den dieses Format zum Ansehen und Wiederanlegen abbildet."""
    categories = taxonomy_repo.list_all(connection, "categories")
    stores = taxonomy_repo.list_all(connection, "stores")
    category_names = {row.id: row.name for row in categories}
    store_names = {row.id: row.name for row in stores}

    items = [
        StammdatenItem(
            name=item.name,
            unit=item.unit,
            note=item.note,
            stock=item.stock,
            reorder_level=item.reorder_level,
            target_stock=item.target_stock,
            pack_size=item.pack_size,
            lead_days=item.lead_days,
            category=(
                category_names.get(item.category_id) if item.category_id is not None else None
            ),
            store=store_names.get(item.store_id) if item.store_id is not None else None,
        )
        for item in items_repo.list_active(connection)
    ]
    return StammdatenExport(
        categories=[row.name for row in categories],
        stores=[row.name for row in stores],
        items=items,
    )


def _find_taxonomy_errors(
    connection: sqlite3.Connection, names: list[str], *, table: taxonomy_repo.TableName, label: str
) -> list[str]:
    existing = {row.name for row in taxonomy_repo.list_all(connection, table)}
    errors: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not name.strip():
            errors.append(f"{label}-Name darf nicht leer sein.")
        elif name in existing:
            errors.append(f"{label} „{name}“ existiert bereits.")
        elif name in seen:
            errors.append(f"{label} „{name}“ kommt in der Datei mehrfach vor.")
        seen.add(name)
    return errors


def _find_item_errors(
    connection: sqlite3.Connection, data: StammdatenExport
) -> tuple[list[str], list[StammdatenItem]]:
    """Liefert `(Fehler, Artikel ohne Namenskonflikt)`. Die zweite Liste wird nur befüllt, damit
    ein Aufrufer bei Erfolg nicht noch einmal filtern muss — bei vorhandenen Fehlern wird ohnehin
    nichts geschrieben."""
    existing_names = {row.name.casefold() for row in items_repo.list_active(connection)}
    known_categories = set(data.categories) | {
        row.name for row in taxonomy_repo.list_all(connection, "categories")
    }
    known_stores = set(data.stores) | {
        row.name for row in taxonomy_repo.list_all(connection, "stores")
    }

    errors: list[str] = []
    seen: set[str] = set()
    for item in data.items:
        key = item.name.casefold()
        if key in existing_names:
            errors.append(f"Artikel „{item.name}“ existiert bereits.")
        elif key in seen:
            errors.append(f"Artikel „{item.name}“ kommt in der Datei mehrfach vor.")
        seen.add(key)

        if item.category is not None and item.category not in known_categories:
            errors.append(
                f"Artikel „{item.name}“ verweist auf unbekannte Kategorie „{item.category}“."
            )
        if item.store is not None and item.store not in known_stores:
            errors.append(f"Artikel „{item.name}“ verweist auf unbekannten Laden „{item.store}“.")

        domain_errors = validate_item(
            ItemInput(
                name=item.name,
                unit=item.unit,
                reorder_level=item.reorder_level,
                target_stock=item.target_stock,
                pack_size=item.pack_size,
                lead_days=item.lead_days,
                stock=item.stock,
                note=item.note,
            )
        )
        errors.extend(f"Artikel „{item.name}“: {message}" for message in domain_errors)

    return errors, data.items


def import_stammdaten(
    connection: sqlite3.Connection, data: StammdatenExport, *, source: str = "import"
) -> StammdatenImportResult:
    """Importiert Kategorien, Läden und Artikel in einer Transaktion — alles oder nichts.

    Wirft `StammdatenImportRejectedError` mit allen gefundenen Problemen, **bevor** irgendetwas
    geschrieben wird, wenn auch nur eines nicht passt.
    """
    errors = [
        *_find_taxonomy_errors(connection, data.categories, table="categories", label="Kategorie"),
        *_find_taxonomy_errors(connection, data.stores, table="stores", label="Laden"),
    ]
    item_errors, items = _find_item_errors(connection, data)
    errors.extend(item_errors)
    if errors:
        raise StammdatenImportRejectedError(errors)

    with transaction(connection):
        category_ids: dict[str, int] = {
            row.name: row.id for row in taxonomy_repo.list_all(connection, "categories")
        }
        for name in data.categories:
            category_ids[name] = taxonomy_repo.insert(
                connection,
                "categories",
                name=name,
                position=taxonomy_repo.next_position(connection, "categories"),
            )

        store_ids: dict[str, int] = {
            row.name: row.id for row in taxonomy_repo.list_all(connection, "stores")
        }
        for name in data.stores:
            store_ids[name] = taxonomy_repo.insert(
                connection,
                "stores",
                name=name,
                position=taxonomy_repo.next_position(connection, "stores"),
            )

        for item in items:
            stock_service.book_create_item(
                connection,
                name=item.name,
                unit=item.unit,
                stock=item.stock,
                reorder_level=item.reorder_level,
                target_stock=item.target_stock,
                pack_size=item.pack_size,
                lead_days=item.lead_days,
                category_id=category_ids.get(item.category) if item.category else None,
                store_id=store_ids.get(item.store) if item.store else None,
                note=item.note,
                position=items_repo.next_position(connection),
                source=source,
            )

    return StammdatenImportResult(
        category_count=len(data.categories), store_count=len(data.stores), item_count=len(items)
    )
