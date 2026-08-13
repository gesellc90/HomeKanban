"""Beispieldaten für die lokale Entwicklung.

Kein Teil des Betriebs auf dem Pi — ein Hilfsskript, um schnell einen Haushalt mit Artikeln
in mehreren Status (AUSREICHEND, NACHKAUFEN) vor sich zu haben, ohne jeden Artikel von Hand
über die spätere Oberfläche anzulegen. Wendet zuerst die Migrationen an und legt dann Artikel
über `app.services.stock.create_item` an (nicht per Rohzugriff), damit jeder Artikel korrekt
seine `opening`-Bewegung bekommt.

Aufruf: `python ops/seed.py [--db-path PFAD] [--history]`. Ohne `--db-path` wird
`HOMEKANBAN_DB_PATH` aus der Konfiguration verwendet. Bricht ab, ohne etwas zu ändern, wenn die
Datenbank bereits Artikel enthält.

`--history` bucht zusätzlich synthetische, rückdatierte Bewegungen über `stock.withdraw()`/
`stock.restock()` (M8, docs/PLAN.md §9) — ausschließlich über die Services, nie per Rohzugriff,
damit `stock_after` und die Journal-Invariante stimmen. Ohne diese Historie zeigt eine frische
Datenbank für jeden Artikel „zu wenig Daten“; M8 lässt sich sonst nicht vorführen. Rein für die
lokale Entwicklung — kein Teil des Betriebs auf dem Pi.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime, timedelta
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


def seed(connection: sqlite3.Connection) -> dict[str, int]:
    """Legt die Beispielartikel an, liefert `{name: item_id}` für `seed_history()`."""
    item_ids: dict[str, int] = {}
    for position, item in enumerate(_ITEMS):
        name, unit, initial_stock, reorder_level, target_stock, pack_size = item
        item_ids[name] = stock.create_item(
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
    return item_ids


def _days_ago(days: int) -> str:
    return stock.format_utc_iso(datetime.now(UTC) - timedelta(days=days))


def seed_history(connection: sqlite3.Connection, item_ids: dict[str, int]) -> None:
    """Bucht synthetische Verbrauchshistorie für zwei Artikel — je eine Vorführung der beiden
    Fälle aus der Definition of Done (docs/PLAN.md §9, M8):

    - **Kaffee** bekommt genug Historie (vier Entnahmen über 45 Tage) für eine plausible
      Verbrauchsrate und Reichweite.
    - **Zahnpasta** bekommt bewusst nur zwei Entnahmen — zu wenig für eine Zahl, zeigt also
      „zu wenig Daten“.
    """
    kaffee_id = item_ids["Kaffee"]
    stock.restock(connection, item_id=kaffee_id, quantity=5, source="import", now=_days_ago(70))
    for days in (60, 45, 30, 15):
        stock.withdraw(
            connection, item_id=kaffee_id, quantity=1, source="import", now=_days_ago(days)
        )

    zahnpasta_id = item_ids["Zahnpasta"]
    for days in (20, 5):
        stock.withdraw(
            connection, item_id=zahnpasta_id, quantity=1, source="import", now=_days_ago(days)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=None, help="Pfad zur SQLite-Datei")
    parser.add_argument(
        "--history",
        action="store_true",
        help=(
            "zusätzlich synthetische, rückdatierte Verbrauchshistorie buchen "
            "(M8, nur für die Vorführung)"
        ),
    )
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

        item_ids = seed(connection)
        print(f"{len(_ITEMS)} Beispielartikel angelegt in {db_path}.")

        if args.history:
            seed_history(connection, item_ids)
            print("Synthetische Verbrauchshistorie für Kaffee und Zahnpasta angelegt.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
