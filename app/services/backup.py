"""Sicherung der SQLite-Datenbank (M9, docs/PLAN.md §9).

Über `sqlite3.Connection.backup()`, **nicht** über `cp` auf die offene Datei — im WAL-Modus
(app/db.py) erzeugt ein Dateikopie stille Inkonsistenz, weil unfertige oder noch nicht ins
Hauptdokument übertragene Seiten aus der `-wal`-Datei fehlen könnten. Die Backup-API kopiert
dagegen einen konsistenten Snapshot, während parallel geschrieben werden darf (`busy_timeout`
wartet dabei wie jeder andere Zugriff, siehe app/db.py).

Der unkomprimierte Zwischenstand entsteht nur in einem temporären Verzeichnis **innerhalb** von
`backup_dir` und existiert nie unter dem endgültigen Namen: `os.replace()` benennt die fertige
`.gz`-Datei erst um, wenn sie vollständig geschrieben ist (dasselbe Dateisystem vorausgesetzt,
weil `backup_dir` als Zielverzeichnis für die temporäre Datei dient). Bricht das Schreiben ab
— volle Platte mitten im gzip —, bleibt unter dem Zielnamen nichts liegen, das die
Aufbewahrungsregel (`app/domain/retention.py`) später fälschlich für ein gültiges Backup hält.
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

from app.db import connect
from app.domain.retention import RetentionPolicy, parse_backup_keep, select_backups_to_keep

#: Lexikalisch korrekt sortierbar (L9) und wieder einlesbar — die Aufbewahrungsregel arbeitet
#: auf den daraus geparsten Zeitpunkten (app/domain/retention.py).
_FILENAME_FORMAT = "%Y%m%dT%H%M%SZ"
_FILENAME_SUFFIX = ".db.gz"


class BackupError(Exception):
    """Basisklasse für alle Fehler, die `ops/backup.py` als deutsche Meldung mit einem von Null
    verschiedenen Exit-Code ausgeben soll — nie als Stacktrace (docs/PLAN.md §9, Aufgabe 5)."""


class DatabaseFileMissingError(BackupError):
    """Die zu sichernde Datenbankdatei existiert nicht."""


class BackupDirectoryError(BackupError):
    """`backup_dir` existiert nicht oder ist nicht beschreibbar."""


class BackupWriteError(BackupError):
    """Das Schreiben der Sicherung ist mittendrin gescheitert, z. B. volle Platte."""


def format_backup_filename(moment: datetime) -> str:
    """Dateiname für ein Backup, das zu `moment` (UTC) erzeugt wurde."""
    return moment.strftime(_FILENAME_FORMAT) + _FILENAME_SUFFIX


def parse_backup_filename(name: str) -> datetime | None:
    """Der Zeitpunkt aus einem Backup-Dateinamen, oder `None` bei einem fremden Dateinamen.

    Fremde Dateien im Sicherungsverzeichnis (docs/PLAN.md §9: "bringen das Skript nicht
    durcheinander") liefern hier `None` statt einer Ausnahme — der Aufrufer überspringt sie.
    """
    if not name.endswith(_FILENAME_SUFFIX):
        return None
    stamp = name[: -len(_FILENAME_SUFFIX)]
    try:
        return datetime.strptime(stamp, _FILENAME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _require_database_file(db_path: Path) -> None:
    if not db_path.is_file():
        raise DatabaseFileMissingError(f"Datenbankdatei nicht gefunden: {db_path}")


def _require_writable_backup_dir(backup_dir: Path) -> None:
    if not backup_dir.is_dir():
        raise BackupDirectoryError(f"Sicherungsverzeichnis nicht gefunden: {backup_dir}")
    if not os.access(backup_dir, os.W_OK):
        raise BackupDirectoryError(f"Sicherungsverzeichnis nicht beschreibbar: {backup_dir}")


def create_backup(*, db_path: Path, backup_dir: Path, now: datetime | None = None) -> Path:
    """Erstellt ein gzip-komprimiertes Backup von `db_path` in `backup_dir` und liefert den Pfad.

    Sicher gegen gleichzeitige Schreibzugriffe auf `db_path` (die Backup-API kopiert einen
    konsistenten Snapshot) und gegen eine volle Platte mitten im Schreiben (siehe Moduldoc).
    """
    _require_database_file(db_path)
    _require_writable_backup_dir(backup_dir)

    moment = now or datetime.now(UTC)
    final_path = backup_dir / format_backup_filename(moment)

    try:
        with tempfile.TemporaryDirectory(dir=backup_dir, prefix=".backup-tmp-") as tmp_dir:
            tmp_db_path = Path(tmp_dir) / "snapshot.db"
            tmp_gz_path = Path(tmp_dir) / "snapshot.db.gz"

            source = connect(db_path)
            try:
                target = sqlite3.connect(tmp_db_path)
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()

            with open(tmp_db_path, "rb") as raw, gzip.open(tmp_gz_path, "wb") as compressed:
                shutil.copyfileobj(raw, compressed)

            os.replace(tmp_gz_path, final_path)
    except OSError as error:
        raise BackupWriteError(f"Sicherung konnte nicht geschrieben werden: {error}") from error

    return final_path


def list_backups(backup_dir: Path) -> list[Path]:
    """Alle erkannten Backup-Dateien in `backup_dir`, älteste zuerst. Fremde Dateien werden
    ignoriert, nicht als Fehler behandelt (docs/PLAN.md §9)."""
    candidates = [
        path
        for path in backup_dir.iterdir()
        if path.is_file() and parse_backup_filename(path.name) is not None
    ]
    return sorted(candidates, key=lambda path: parse_backup_filename(path.name) or datetime.min)


def apply_retention(
    *, backup_dir: Path, policy: RetentionPolicy, now: datetime | None = None, keep_path: Path
) -> list[Path]:
    """Löscht, was `app.domain.retention.select_backups_to_keep` verwirft, und liefert die
    gelöschten Pfade (älteste zuerst).

    `keep_path` — das soeben geschriebene Backup — wird **niemals** gelöscht, selbst wenn eine
    unsinnig enge Aufbewahrungsregel (`daily=0` o. Ä.) es sonst verwerfen würde; die Domänenlogik
    kennt nur Zeitpunkte, keine Dateiidentität, und genau dafür ist dieser Parameter da.
    """
    moment = now or datetime.now(UTC)
    backups = list_backups(backup_dir)
    timestamp_by_path = {path: parse_backup_filename(path.name) for path in backups}
    timestamps = [ts for ts in timestamp_by_path.values() if ts is not None]

    keep_timestamps = select_backups_to_keep(timestamps, policy=policy, now=moment)

    deleted: list[Path] = []
    for path in backups:
        if path == keep_path:
            continue
        if timestamp_by_path[path] in keep_timestamps:
            continue
        path.unlink()
        deleted.append(path)
    return deleted


@dataclass(frozen=True)
class BackupRunResult:
    created: Path
    deleted: list[Path]


def run_backup(
    *, db_path: Path, backup_dir: Path, keep_spec: str, now: datetime | None = None
) -> BackupRunResult:
    """Ein vollständiger Sicherungslauf: neues Backup schreiben, dann die Aufbewahrungsregel
    anwenden — die Reihenfolge stellt sicher, dass eine kaputte `HOMEKANBAN_BACKUP_KEEP`
    (`RetentionPolicyError`) erkannt wird, **bevor** überhaupt geschrieben wird.
    """
    policy = parse_backup_keep(keep_spec)

    moment = now or datetime.now(UTC)
    created_path = create_backup(db_path=db_path, backup_dir=backup_dir, now=moment)
    deleted_paths = apply_retention(
        backup_dir=backup_dir, policy=policy, now=moment, keep_path=created_path
    )
    return BackupRunResult(created=created_path, deleted=deleted_paths)
