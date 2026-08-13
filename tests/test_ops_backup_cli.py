"""Testet `ops/backup.py` als tatsächlichen Prozessaufruf (kein Paket, siehe docs/PLAN.md §2/§9,
"Fünf Dinge, die dich betreffen") — genau der Weg, den der Host-Cron später benutzt. Prüft vor
allem die Fehlbedienungsfälle: verständliche deutsche Meldung auf stderr, von Null verschiedener
Exit-Code, nie ein Stacktrace (docs/PLAN.md §9, Aufgabe 5)."""

from __future__ import annotations

import gzip
import os
import subprocess
import sys
from pathlib import Path

from app.db import connect
from app.migrate import migrate
from app.services import stock

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"
BACKUP_SCRIPT = REPO_ROOT / "ops" / "backup.py"


def _make_database(db_path: Path) -> None:
    connection = connect(db_path)
    try:
        migrate(connection, MIGRATIONS_DIR)
        stock.create_item(
            connection,
            name="Testartikel",
            unit="Packung",
            stock=5,
            reorder_level=1,
            target_stock=10,
            position=0,
        )
    finally:
        connection.close()


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BACKUP_SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestOpsBackupCli:
    def test_successful_run_writes_a_readable_gzip_backup(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = _run("--db-path", str(db_path), "--backup-dir", str(backup_dir))

        assert result.returncode == 0, result.stderr
        assert "Backup geschrieben" in result.stdout
        written = list(backup_dir.iterdir())
        assert len(written) == 1
        with gzip.open(written[0], "rb") as compressed:
            assert compressed.read(16).startswith(b"SQLite format 3")

    def test_missing_database_file_exits_nonzero_with_german_message_and_no_traceback(
        self, tmp_path: Path
    ) -> None:
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = _run("--db-path", str(tmp_path / "fehlt.db"), "--backup-dir", str(backup_dir))

        assert result.returncode != 0
        assert "Traceback" not in result.stderr
        assert "nicht gefunden" in result.stderr

    def test_missing_backup_dir_exits_nonzero_with_german_message_and_no_traceback(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)

        result = _run("--db-path", str(db_path), "--backup-dir", str(tmp_path / "fehlt"))

        assert result.returncode != 0
        assert "Traceback" not in result.stderr
        assert "Sicherungsverzeichnis" in result.stderr

    def test_broken_keep_config_via_env_exits_nonzero_without_writing_a_backup(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = subprocess.run(
            [sys.executable, str(BACKUP_SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "HOMEKANBAN_BACKUP_KEEP": "unsinn",
                "HOMEKANBAN_DB_PATH": str(db_path),
                "HOMEKANBAN_BACKUP_DIR": str(backup_dir),
            },
        )

        assert result.returncode != 0
        assert "Traceback" not in result.stderr
        assert list(backup_dir.iterdir()) == []
