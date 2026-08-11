"""Migrationsrunner: wendet `.sql`-Dateien aus einem Verzeichnis in Namensreihenfolge an.

Jede Migration läuft für sich atomar (Skript + Versionseintrag zusammen), der Dateiname ist die
Version. Bereits angewendete Migrationen werden übersprungen — der Runner ist idempotent und darf
beliebig oft aufgerufen werden (Testpflicht laut docs/PLAN.md §11).

`sqlite3.Connection.executescript()` gibt vor jedem Aufruf implizit eine pendente Transaktion frei
und lässt sich daher nicht mit `app.db.transaction()` kombinieren. Stattdessen wird `BEGIN`
innerhalb des ausgeführten Skripts selbst gesetzt und die Transaktion danach über die
Python-API committet bzw. bei einem Fehler zurückgerollt.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""


def migrate(connection: sqlite3.Connection, migrations_dir: Path) -> list[str]:
    connection.execute(_SCHEMA_MIGRATIONS_DDL)
    connection.commit()

    applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}

    newly_applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in applied:
            continue

        sql = path.read_text(encoding="utf-8")
        try:
            connection.executescript(f"BEGIN;\n{sql}")
            connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (path.name,))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        newly_applied.append(path.name)

    return newly_applied
