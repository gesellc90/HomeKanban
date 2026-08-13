"""Domänenvalidierung für Artikelstammdaten, siehe docs/PLAN.md §3.

Die Prüfregeln stehen als `CHECK`-Constraint in `migrations/0001_init.sql`. Diese Datei prüft
dieselben Regeln noch einmal auf Domänenebene, damit eine Verletzung als verständliche deutsche
Meldung endet — sonst würde `sqlite3.IntegrityError` bis zur Web-Schicht durchschlagen und dort
eine 500er-Seite erzeugen. Reine Logik: kein SQL, kein I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


class ItemValidationError(Exception):
    """Eine oder mehrere Prüfregeln für Artikelstammdaten sind verletzt."""

    def __init__(self, errors: list[str]) -> None:
        if not errors:
            raise ValueError("errors darf nicht leer sein")
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class ItemInput:
    name: str
    unit: str
    reorder_level: int
    target_stock: int
    pack_size: int
    lead_days: int
    stock: int | None = None
    note: str | None = None


def validate_item(item: ItemInput) -> list[str]:
    """Liefert eine Liste deutscher Fehlermeldungen; leer, wenn alle Regeln eingehalten sind."""
    errors: list[str] = []

    if not item.name.strip():
        errors.append("Name darf nicht leer sein.")
    if not item.unit.strip():
        errors.append("Einheit darf nicht leer sein.")
    if item.stock is not None and item.stock < 0:
        errors.append("Bestand darf nicht negativ sein.")
    if item.reorder_level < 0:
        errors.append("Mindestbestand darf nicht negativ sein.")
    if item.pack_size < 1:
        errors.append("Kaufeinheit muss mindestens 1 sein.")
    if item.lead_days < 1:
        errors.append("Vorlaufzeit muss mindestens 1 Tag sein.")
    if item.target_stock <= item.reorder_level:
        errors.append("Sollbestand muss größer als der Mindestbestand sein.")

    return errors


def require_valid_item(item: ItemInput) -> None:
    """Wie `validate_item`, wirft aber `ItemValidationError` statt eine Liste zurückzugeben."""
    errors = validate_item(item)
    if errors:
        raise ItemValidationError(errors)
