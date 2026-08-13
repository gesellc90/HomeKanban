"""Rückspielen eines Backups (M9, docs/PLAN.md §9).

**Vor dem Aufruf: den Container stoppen** (`docker compose down` bzw. `docker compose stop`, siehe
`ops/BACKUP.md`). Dieses Skript kann nicht prüfen, ob noch ein Prozess auf `--db-path` schreibt —
läuft die App währenddessen weiter, entstehen wieder frische `-wal`/`-shm`-Dateien gegen die alte
Datenbank, während hier eine neue untergeschoben wird.

Was das Skript selbst übernimmt (`app.services.restore.restore_backup`): das Backup wird geprüft
(`PRAGMA integrity_check` + Kerntabellen), **bevor** eine vorhandene Datenbank angefasst wird; eine
vorhandene Datenbank wird nie gelöscht, sondern nach `<name>.vor-restore-<Zeitstempel>` verschoben
(CLAUDE.md §4); liegengebliebene `-wal`/`-shm`-Dateien werden mit beiseitegelegt, damit sie den
zurückgespielten Stand nicht verfälschen.

**Nach dem Aufruf:** Container wieder starten und `GET /healthz` prüfen — das ist der Nachweis,
dass die Journal-Invariante (`SUM(delta) == stock`) auch nach dem Restore hält.

Aufruf: `python ops/restore.py --backup-file PFAD [--db-path PFAD]`. Ohne `--db-path` wird
`HOMEKANBAN_DB_PATH` aus der Konfiguration verwendet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.services.restore import RestoreError, restore_backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup-file", type=Path, required=True, help="Pfad zur .db.gz-Sicherungsdatei"
    )
    parser.add_argument("--db-path", type=Path, default=None, help="Zielpfad der Datenbankdatei")
    args = parser.parse_args()

    settings = get_settings()
    db_path: Path = args.db_path or settings.db_path

    try:
        result = restore_backup(backup_path=args.backup_file, db_path=db_path)
    except RestoreError as error:
        print(f"Restore fehlgeschlagen: {error}", file=sys.stderr)
        sys.exit(1)

    print(f"Restauriert nach: {result.restored_path}")
    if result.moved_aside:
        names = ", ".join(path.name for path in result.moved_aside)
        print(f"Vorherigen Stand beiseitegelegt ({len(result.moved_aside)}): {names}")
    print("Jetzt den Container wieder starten und GET /healthz prüfen.")


if __name__ == "__main__":
    main()
