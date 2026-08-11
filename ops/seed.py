"""Beispieldaten für die lokale Entwicklung.

Kein Teil des Betriebs auf dem Pi — ein Hilfsskript, um schnell einen Haushalt mit Artikeln
in mehreren Status (AUSREICHEND, NACHKAUFEN) vor sich zu haben, ohne jeden Artikel von Hand
über die spätere Oberfläche anzulegen. Wendet zuerst die Migrationen an und legt dann Artikel
über `app.services.stock.create_item` an (nicht per Rohzugriff), damit jeder Artikel korrekt
seine `opening`-Bewegung bekommt.

Aufruf: `python ops/seed.py [--db-path PFAD]`. Ohne `--db-path` wird `HOMEKANBAN_DB_PATH` aus
der Konfiguration verwendet. Bricht ab, ohne etwas zu ändern, wenn die Datenbank bereits
Artikel enthält.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.config import get_settings
from app.db import connect
from app.migrate import migrate
from app.services import stock

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# (Name, Einheit, Anfangsbestand, Mindestbestand, Sollbestand, Kaufeinheit)
_ITEMS: list[tuple[str, str, int, int, int, int]] = [
    ("Spülmaschinentabs", "Packung", 3, 1, 3, 1),
    ("Klopapier", "Rolle", 0, 1, 10, 10),
    ("Kaffee", "Packung", 1, 1, 2, 1),
    ("Zahnpasta", "Tube", 2, 1, 3, 1),
    ("Müllbeutel", "Rolle", 4, 2, 6, 2),
]


def seed(connection: sqlite3.Connection) -> None:
    for position, item in enumerate(_ITEMS):
        name, unit, initial_stock, reorder_level, target_stock, pack_size = item
        stock.create_item(
            connection,
            name=name,
            unit=unit,
            stock=initial_stock,
            reorder_level=reorder_level,
            target_stock=target_stock,
            pack_size=pack_size,
            position=position,
            source="import",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=None, help="Pfad zur SQLite-Datei")
    args = parser.parse_args()

    settings = get_settings()
    db_path: Path = args.db_path or settings.db_path

    connection = connect(db_path)
    try:
        migrate(connection, MIGRATIONS_DIR)

        existing = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        if existing:
            print(f"Übersprungen: {db_path} enthält bereits {existing} Artikel.")
            return

        seed(connection)
        print(f"{len(_ITEMS)} Beispielartikel angelegt in {db_path}.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
