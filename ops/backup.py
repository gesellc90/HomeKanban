"""Sicherungslauf für den Host-Cron (M9, docs/PLAN.md §9).

Ein Aufruf macht genau zwei Dinge: ein neues Backup über `app.services.backup.create_backup`
schreiben (SQLite-`.backup()`-API + gzip, **kein** `cp` auf die offene Datei, siehe dort) und
anschließend die Aufbewahrungsregel (`app.domain.retention`, `HOMEKANBAN_BACKUP_KEEP`) anwenden.
Keine Logdatei daneben (R5, docs/PLAN.md §10) — alles geht nach stdout/stderr, wie der Rest der
App.

Aufruf: `python ops/backup.py [--db-path PFAD] [--backup-dir PFAD]`. Ohne Angabe werden
`HOMEKANBAN_DB_PATH`/`HOMEKANBAN_BACKUP_DIR` aus der Konfiguration verwendet.

**Zwei Aufrufwege, die dieses Skript beide vertragen muss** (Aufgabenstellung, "Fünf Dinge, die
dich betreffen"): Die Datenbank liegt im Compose-Setup in einem *benannten* Docker-Volume
(`homekanban-data`), nicht in einem Bind-Mount — ein Host-Cron sieht `/data/homekanban.db` also
nicht ohne Weiteres. Solange M6 das nicht löst, läuft dieser Aufruf entweder **im Container**
(`docker compose exec homekanban python ops/backup.py`, `--db-path`/`--backup-dir` zeigen dann auf
die Container-Pfade `/data/...`) oder auf dem **Host** gegen einen zusätzlichen Bind-Mount für das
Sicherungsverzeichnis — deshalb sind beide Pfade frei wählbar und es gibt keine `/data`-Annahme
im Code selbst. Details und die vorgesehenen Cron-Zeilen stehen in `ops/BACKUP.md`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.domain.retention import RetentionPolicyError
from app.services.backup import BackupError, run_backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=None, help="Pfad zur SQLite-Datei")
    parser.add_argument(
        "--backup-dir", type=Path, default=None, help="Zielverzeichnis für die Sicherungen"
    )
    args = parser.parse_args()

    settings = get_settings()
    db_path: Path = args.db_path or settings.db_path
    backup_dir: Path = args.backup_dir or settings.backup_dir

    try:
        result = run_backup(db_path=db_path, backup_dir=backup_dir, keep_spec=settings.backup_keep)
    except (BackupError, RetentionPolicyError) as error:
        # Deutsche Meldung, von Null verschiedener Exit-Code, nie ein Stacktrace (§9, Aufgabe 5)
        # — das hier ist der nächtliche Cron-Lauf, niemand sieht das interaktiv.
        print(f"Sicherung fehlgeschlagen: {error}", file=sys.stderr)
        sys.exit(1)

    print(f"Backup geschrieben: {result.created}")
    if result.deleted:
        names = ", ".join(path.name for path in result.deleted)
        print(f"Nach Aufbewahrungsregel gelöscht ({len(result.deleted)}): {names}")


if __name__ == "__main__":
    main()
