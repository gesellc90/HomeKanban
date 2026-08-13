"""Testet `ops/restore.py` als tatsächlichen Prozessaufruf, analog zu
tests/test_ops_backup_cli.py. Prüft vor allem, dass Fehlbedienung nie zu einem Stacktrace führt
(docs/PLAN.md §9, Aufgabe 5) und dass ein echter Restore-Rundlauf über die Kommandozeile
funktioniert (Definition of Done: "ein Restore ist durchgeführt worden")."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.db import connect
from app.migrate import migrate
from app.repo.movements import find_ledger_invariant_violations
from app.services import backup as backup_service
from app.services import stock

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"
BACKUP_SCRIPT = REPO_ROOT / "ops" / "backup.py"
RESTORE_SCRIPT = REPO_ROOT / "ops" / "restore.py"


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


def _run_restore(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RESTORE_SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestOpsRestoreCli:
    def test_missing_backup_file_exits_nonzero_with_german_message_and_no_traceback(
        self, tmp_path: Path
    ) -> None:
        result = _run_restore(
            "--backup-file", str(tmp_path / "fehlt.db.gz"), "--db-path", str(tmp_path / "hk.db")
        )

        assert result.returncode != 0
        assert "Traceback" not in result.stderr
        assert "nicht gefunden" in result.stderr

    def test_end_to_end_backup_then_restore_via_the_command_line(self, tmp_path: Path) -> None:
        """Der komplette Rundlauf über die tatsächlichen CLI-Skripte: sichern, Zieldatenbank
        löschen ("Karte tot"), zurückspielen, Invariante prüfen."""
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        backup_result = subprocess.run(
            [
                sys.executable,
                str(BACKUP_SCRIPT),
                "--db-path",
                str(db_path),
                "--backup-dir",
                str(backup_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert backup_result.returncode == 0, backup_result.stderr

        [backup_file] = backup_service.list_backups(backup_dir)

        # "SD-Karten-Tod": die Originaldatenbank verschwindet vollständig.
        db_path.unlink()

        restore_result = _run_restore("--backup-file", str(backup_file), "--db-path", str(db_path))

        assert restore_result.returncode == 0, restore_result.stderr
        assert "Restauriert nach" in restore_result.stdout

        restored_connection = connect(db_path)
        try:
            item = restored_connection.execute("SELECT * FROM items").fetchone()
            assert item["name"] == "Testartikel"
            assert item["stock"] == 5
            assert find_ledger_invariant_violations(restored_connection) == []
        finally:
            restored_connection.close()
