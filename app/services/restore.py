"""Rückspielen eines Backups (M9, docs/PLAN.md §9).

**Voraussetzung, die dieses Modul nicht erzwingen kann:** Der Container (bzw. jeder Prozess, der
`db_path` offen hält) muss gestoppt sein, bevor restauriert wird — eine laufende App würde sonst
weiterhin gegen die alte Datei samt ihrer `-wal`/`-shm`-Dateien schreiben, während hier eine neue
Datei untergeschoben wird. Das gehört in die Betriebsanleitung (`ops/BACKUP.md`), nicht in Code.

**Was dieses Modul erzwingt:**

1. Das Backup wird geprüft (`PRAGMA integrity_check` + Kerntabellen vorhanden), **bevor** eine
   vorhandene Datenbank überhaupt angefasst wird — ein kaputtes Backup darf niemals eine intakte
   Datenbank ersetzen.
2. Eine vorhandene Datenbank wird nie gelöscht, sondern beiseitegelegt (CLAUDE.md §4: "keine
   destruktiven Datenoperationen ohne Sicherung", "vor dem Überschreiben oder Löschen einer Datei
   erst hineinsehen").
3. Liegengebliebene `-wal`/`-shm`-Dateien neben der alten Datenbank werden mit beiseitegelegt —
   sonst würde SQLite sie beim nächsten Öffnen gegen die **neue**, gerade restaurierte Datei
   abspielen wollen und den zurückgespielten Stand verfälschen (der Punkt, den man laut
   Aufgabenstellung leicht übersieht).
"""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Eine Datenbankdatei im WAL-Modus kann diese beiden Begleitdateien haben (app/db.py).
_SIDECAR_SUFFIXES = ("-wal", "-shm")

#: Tabellen, deren Fehlen ein Backup als "keine HomeKanban-Datenbank" statt als beschädigt
#: einstuft — beide Meldungen enden als `BackupFileCorruptError`, aber mit unterschiedlichem Text.
_CORE_TABLES = {"items", "movements", "shopping_lists", "shopping_list_lines"}


class RestoreError(Exception):
    """Basisklasse für alle Fehler, die `ops/restore.py` als deutsche Meldung mit einem von Null
    verschiedenen Exit-Code ausgeben soll — nie als Stacktrace (docs/PLAN.md §9, Aufgabe 5)."""


class BackupFileMissingError(RestoreError):
    """Die angegebene Backup-Datei existiert nicht."""


class BackupFileCorruptError(RestoreError):
    """Die Backup-Datei ist kein gültiges gzip, keine gültige SQLite-Datenbank, oder es fehlen
    Kerntabellen — kaputt oder abgeschnitten."""


class RestoreDirectoryError(RestoreError):
    """Das Zielverzeichnis für die Datenbank existiert nicht oder ist nicht beschreibbar."""


@dataclass(frozen=True)
class RestoreResult:
    restored_path: Path
    moved_aside: list[Path]


def _require_backup_file(backup_path: Path) -> None:
    if not backup_path.is_file():
        raise BackupFileMissingError(f"Backup-Datei nicht gefunden: {backup_path}")


def _require_writable_target_dir(db_path: Path) -> None:
    target_dir = db_path.parent
    if not target_dir.is_dir():
        raise RestoreDirectoryError(f"Zielverzeichnis nicht gefunden: {target_dir}")
    if not os.access(target_dir, os.W_OK):
        raise RestoreDirectoryError(f"Zielverzeichnis nicht beschreibbar: {target_dir}")


def _decompress(backup_path: Path, destination: Path) -> None:
    try:
        with gzip.open(backup_path, "rb") as compressed, open(destination, "wb") as raw:
            shutil.copyfileobj(compressed, raw)
    except (OSError, gzip.BadGzipFile) as error:
        raise BackupFileCorruptError(
            f"Backup-Datei ist kein gültiges gzip oder abgeschnitten: {backup_path} ({error})"
        ) from error


def _verify_sqlite_database(candidate_path: Path, *, backup_path: Path) -> None:
    try:
        connection = sqlite3.connect(f"file:{candidate_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as error:
        raise BackupFileCorruptError(
            f"Backup-Datei lässt sich nicht als SQLite-Datenbank öffnen: {backup_path} ({error})"
        ) from error

    try:
        try:
            (status,) = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as error:
            raise BackupFileCorruptError(
                f"Backup-Datei ist keine gültige SQLite-Datenbank: {backup_path} ({error})"
            ) from error
        if status != "ok":
            raise BackupFileCorruptError(
                f"Backup-Datei besteht die Konsistenzprüfung nicht: {backup_path} ({status})"
            )

        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = _CORE_TABLES - table_names
        if missing:
            raise BackupFileCorruptError(
                f"Backup-Datei enthält keine HomeKanban-Datenbank (es fehlen: "
                f"{', '.join(sorted(missing))}): {backup_path}"
            )
    finally:
        connection.close()


def _sidecar_paths(db_path: Path) -> list[Path]:
    return [db_path.with_name(db_path.name + suffix) for suffix in _SIDECAR_SUFFIXES]


def _move_existing_database_aside(db_path: Path, *, moment: datetime) -> list[Path]:
    """Legt eine vorhandene Datenbank samt `-wal`/`-shm` beiseite statt sie zu löschen.

    Das ist der Kern des im Auftrag genannten leicht übersehenen Falls: Bliebe eine `-wal`-Datei
    unter dem alten Namen liegen, würde SQLite sie beim nächsten Öffnen der frisch restaurierten
    Datei zuordnen und deren Frames auf den neuen Stand anwenden — mit unvorhersehbarem Ergebnis.
    """
    suffix = f".vor-restore-{moment.strftime('%Y%m%dT%H%M%SZ')}"
    moved: list[Path] = []
    for existing in [db_path, *_sidecar_paths(db_path)]:
        if existing.exists():
            destination = existing.with_name(existing.name + suffix)
            os.replace(existing, destination)
            moved.append(destination)
    return moved


def restore_backup(
    *, backup_path: Path, db_path: Path, now: datetime | None = None
) -> RestoreResult:
    """Spielt `backup_path` nach `db_path` zurück. Der Aufrufer muss sicherstellen, dass kein
    Prozess `db_path` gerade offen hält (siehe Moduldoc) — das kann dieses Modul nicht prüfen.
    """
    _require_backup_file(backup_path)
    _require_writable_target_dir(db_path)

    moment = now or datetime.now(UTC)

    with tempfile.TemporaryDirectory(dir=db_path.parent, prefix=".restore-tmp-") as tmp_dir:
        candidate_path = Path(tmp_dir) / "candidate.db"
        _decompress(backup_path, candidate_path)
        _verify_sqlite_database(candidate_path, backup_path=backup_path)

        moved_aside = _move_existing_database_aside(db_path, moment=moment)
        os.replace(candidate_path, db_path)

    return RestoreResult(restored_path=db_path, moved_aside=moved_aside)
