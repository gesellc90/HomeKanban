"""Stammdaten-Export/-Import: Artikel, Kategorien, Läden als JSON oder CSV (M9, Fragerunde,
Frage 3).

Reine Logik: kein Dateisystem, kein SQL. Übersetzt zwischen der portablen Textdarstellung
(JSON/CSV) und den hier definierten, von der Datenbank losgelösten Datenklassen.
`app/services/stammdaten.py` liest/schreibt die Datenbank und ruft diese Funktionen nur zur
Übersetzung — dieselbe Schichtung wie `app/domain/labels.py` und `app/services/labels.py`.

**Entschieden (Fragerunde M9, Frage 3):** Umfang ist `items` (samt `lead_days`), `categories`,
`stores` — **ohne** `movements` und ohne Einkaufslisten; dafür ist das Datenbank-Backup da
(`app/services/backup.py`). Nur **aktive** (nicht archivierte) Artikel werden exportiert, im
Einklang mit "zum Ansehen und Wiederanlegen" statt einer zweiten Sicherung. `qr_token` ist bewusst
**nicht** Teil des Formats: Ein Import erzeugt neue, stabile Tokens über
`app.services.stock.create_item` — bestehende, geklebte Etiketten müssten nach einem
Stammdaten-Import neu gedruckt werden.

**CSV-Format (sichtbare Annahme, nicht Teil der Fragerunde):** Nur Artikel, eine Zeile je Artikel;
Kategorien und Läden ergeben sich aus den Spalten `category`/`store` der Artikelzeilen (erste
Nennung bestimmt die Reihenfolge). Eine Kategorie oder ein Laden **ohne** zugeordneten Artikel
geht damit im CSV-Format verloren — das JSON-Format ist die vollständige, verlustfreie
Darstellung und die Grundlage für den Restore-Test (docs/PLAN.md §9, Aufgabe 6).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass


class StammdatenFormatError(ValueError):
    """Die Import-Datei ist kaputt, abgeschnitten oder enthält unbekannte/fehlende Felder —
    verständliche deutsche Meldung statt eines Absturzes (docs/PLAN.md §9, Aufgabe 5)."""


@dataclass(frozen=True)
class StammdatenItem:
    name: str
    unit: str
    note: str | None
    stock: int
    reorder_level: int
    target_stock: int
    pack_size: int
    lead_days: int
    category: str | None
    store: str | None


@dataclass(frozen=True)
class StammdatenExport:
    categories: list[str]
    stores: list[str]
    items: list[StammdatenItem]


_TOP_LEVEL_FIELDS = ("categories", "stores", "items")
_ITEM_FIELDS = (
    "name",
    "unit",
    "note",
    "stock",
    "reorder_level",
    "target_stock",
    "pack_size",
    "lead_days",
    "category",
    "store",
)
_CSV_FIELDNAMES = _ITEM_FIELDS


def to_json(data: StammdatenExport) -> str:
    payload = {
        "categories": list(data.categories),
        "stores": list(data.stores),
        "items": [
            {
                "name": item.name,
                "unit": item.unit,
                "note": item.note,
                "stock": item.stock,
                "reorder_level": item.reorder_level,
                "target_stock": item.target_stock,
                "pack_size": item.pack_size,
                "lead_days": item.lead_days,
                "category": item.category,
                "store": item.store,
            }
            for item in data.items
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def from_json(text: str) -> StammdatenExport:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise StammdatenFormatError(f"Datei ist kein gültiges JSON: {error}") from error

    if not isinstance(payload, dict):
        raise StammdatenFormatError("Die JSON-Datei muss ein Objekt auf oberster Ebene sein.")

    unknown_top_level = set(payload) - set(_TOP_LEVEL_FIELDS)
    if unknown_top_level:
        raise StammdatenFormatError(
            f"Unbekannte Felder in der JSON-Datei: {', '.join(sorted(unknown_top_level))}."
        )
    missing_top_level = set(_TOP_LEVEL_FIELDS) - set(payload)
    if missing_top_level:
        raise StammdatenFormatError(
            f"Es fehlen Felder in der JSON-Datei: {', '.join(sorted(missing_top_level))}."
        )

    categories = _require_string_list(payload["categories"], field="categories")
    stores = _require_string_list(payload["stores"], field="stores")

    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        raise StammdatenFormatError("„items“ muss eine Liste sein.")

    items = [_item_from_dict(raw_item, index=index) for index, raw_item in enumerate(raw_items)]
    return StammdatenExport(categories=categories, stores=stores, items=items)


def _require_string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise StammdatenFormatError(f"„{field}“ muss eine Liste von Namen (Text) sein.")
    return list(value)


def _item_from_dict(raw: object, *, index: int) -> StammdatenItem:
    if not isinstance(raw, dict):
        raise StammdatenFormatError(f"Artikel Nr. {index + 1} ist kein Objekt.")

    unknown = set(raw) - set(_ITEM_FIELDS)
    if unknown:
        raise StammdatenFormatError(
            f"Artikel Nr. {index + 1} enthält unbekannte Felder: {', '.join(sorted(unknown))}."
        )
    missing = set(_ITEM_FIELDS) - set(raw)
    if missing:
        raise StammdatenFormatError(
            f"Artikel Nr. {index + 1} fehlen Felder: {', '.join(sorted(missing))}."
        )

    return StammdatenItem(
        name=_require_str(raw["name"], field="name", index=index),
        unit=_require_str(raw["unit"], field="unit", index=index),
        note=_require_optional_str(raw["note"], field="note", index=index),
        stock=_require_int(raw["stock"], field="stock", index=index),
        reorder_level=_require_int(raw["reorder_level"], field="reorder_level", index=index),
        target_stock=_require_int(raw["target_stock"], field="target_stock", index=index),
        pack_size=_require_int(raw["pack_size"], field="pack_size", index=index),
        lead_days=_require_int(raw["lead_days"], field="lead_days", index=index),
        category=_require_optional_str(raw["category"], field="category", index=index),
        store=_require_optional_str(raw["store"], field="store", index=index),
    )


def _require_str(value: object, *, field: str, index: int) -> str:
    if not isinstance(value, str):
        raise StammdatenFormatError(f"Artikel Nr. {index + 1}: „{field}“ muss Text sein.")
    return value


def _require_optional_str(value: object, *, field: str, index: int) -> str | None:
    if value is None:
        return None
    return _require_str(value, field=field, index=index)


def _require_int(value: object, *, field: str, index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StammdatenFormatError(f"Artikel Nr. {index + 1}: „{field}“ muss eine Ganzzahl sein.")
    return value


def to_csv(data: StammdatenExport) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for item in data.items:
        writer.writerow(
            {
                "name": item.name,
                "unit": item.unit,
                "note": item.note or "",
                "stock": item.stock,
                "reorder_level": item.reorder_level,
                "target_stock": item.target_stock,
                "pack_size": item.pack_size,
                "lead_days": item.lead_days,
                "category": item.category or "",
                "store": item.store or "",
            }
        )
    return buffer.getvalue()


def from_csv(text: str) -> StammdatenExport:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise StammdatenFormatError("CSV-Datei ist leer oder hat keine Kopfzeile.")

    fieldnames = tuple(reader.fieldnames)
    if fieldnames != _CSV_FIELDNAMES:
        unknown = set(fieldnames) - set(_CSV_FIELDNAMES)
        missing = set(_CSV_FIELDNAMES) - set(fieldnames)
        details = []
        if unknown:
            details.append(f"unbekannte Spalten: {', '.join(sorted(unknown))}")
        if missing:
            details.append(f"fehlende Spalten: {', '.join(sorted(missing))}")
        if not details:
            details.append("falsche Reihenfolge der Spalten")
        raise StammdatenFormatError(
            f"CSV-Kopfzeile passt nicht zum erwarteten Format ({'; '.join(details)}). "
            f"Erwartet: {', '.join(_CSV_FIELDNAMES)}."
        )

    items: list[StammdatenItem] = []
    categories: list[str] = []
    stores: list[str] = []
    for row_index, row in enumerate(reader):
        item = _item_from_csv_row(row, row_index=row_index)
        items.append(item)
        if item.category is not None and item.category not in categories:
            categories.append(item.category)
        if item.store is not None and item.store not in stores:
            stores.append(item.store)

    return StammdatenExport(categories=categories, stores=stores, items=items)


def _item_from_csv_row(row: dict[str, str | None], *, row_index: int) -> StammdatenItem:
    # `csv.DictReader` liefert `None`, wenn eine Zeile weniger Spalten hat als die Kopfzeile, und
    # sammelt zu viele Spalten unter dem Schlüssel `None` — beides der abgeschnittene bzw. kaputte
    # Fall aus der Fehlbedienungsliste (docs/PLAN.md §9, Aufgabe 5).
    if None in row:
        raise StammdatenFormatError(
            f"CSV-Zeile {row_index + 2} hat mehr Spalten als die Kopfzeile."
        )

    def _field(name: str) -> str:
        value = row.get(name)
        if value is None:
            raise StammdatenFormatError(
                f"CSV-Zeile {row_index + 2}: Spalte „{name}“ fehlt (Zeile abgeschnitten?)."
            )
        return value

    def _int_field(name: str) -> int:
        raw = _field(name)
        try:
            return int(raw)
        except ValueError as error:
            raise StammdatenFormatError(
                f"CSV-Zeile {row_index + 2}: „{name}“ ist keine Ganzzahl ({raw!r})."
            ) from error

    def _optional(name: str) -> str | None:
        value = _field(name)
        return value or None

    name = _field("name")
    if not name.strip():
        raise StammdatenFormatError(f"CSV-Zeile {row_index + 2}: „name“ darf nicht leer sein.")

    return StammdatenItem(
        name=name,
        unit=_field("unit"),
        note=_optional("note"),
        stock=_int_field("stock"),
        reorder_level=_int_field("reorder_level"),
        target_stock=_int_field("target_stock"),
        pack_size=_int_field("pack_size"),
        lead_days=_int_field("lead_days"),
        category=_optional("category"),
        store=_optional("store"),
    )
