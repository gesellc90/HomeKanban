from __future__ import annotations

import gzip
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.db import connect
from app.domain.retention import RetentionPolicy, RetentionPolicyError
from app.migrate import migrate
from app.repo.movements import find_ledger_invariant_violations
from app.services import backup as backup_service
from app.services import stock

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


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


class TestFilenameRoundtrip:
    def test_parses_what_it_formatted(self) -> None:
        moment = datetime(2026, 8, 13, 14, 25, 30, tzinfo=UTC)
        name = backup_service.format_backup_filename(moment)

        assert name == "20260813T142530Z.db.gz"
        assert backup_service.parse_backup_filename(name) == moment

    def test_foreign_filename_returns_none(self) -> None:
        assert backup_service.parse_backup_filename("readme.txt") is None
        assert backup_service.parse_backup_filename("nonsense.db.gz") is None


class TestCreateBackup:
    def test_missing_database_file_raises_understandable_error(self, tmp_path: Path) -> None:
        with pytest.raises(backup_service.DatabaseFileMissingError):
            backup_service.create_backup(
                db_path=tmp_path / "does-not-exist.db", backup_dir=tmp_path
            )

    def test_missing_backup_dir_raises_understandable_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)

        with pytest.raises(backup_service.BackupDirectoryError):
            backup_service.create_backup(db_path=db_path, backup_dir=tmp_path / "missing")

    @pytest.mark.skipif(os.geteuid() == 0, reason="Rechteprüfung ist als root wirkungslos")
    def test_unwritable_backup_dir_raises_understandable_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_dir.chmod(0o500)

        try:
            with pytest.raises(backup_service.BackupDirectoryError):
                backup_service.create_backup(db_path=db_path, backup_dir=backup_dir)
        finally:
            backup_dir.chmod(0o700)  # sonst kann tmp_path später nicht aufgeräumt werden

    def test_result_is_valid_gzip_of_a_valid_sqlite_database(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result_path = backup_service.create_backup(db_path=db_path, backup_dir=backup_dir)

        assert result_path.parent == backup_dir
        assert result_path.name.endswith(".db.gz")

        restored_path = tmp_path / "restored.db"
        with gzip.open(result_path, "rb") as compressed:
            restored_path.write_bytes(compressed.read())

        restored = sqlite3.connect(restored_path)
        try:
            restored.row_factory = sqlite3.Row
            row = restored.execute("SELECT name, stock FROM items").fetchone()
            assert row["name"] == "Testartikel"
            assert row["stock"] == 5
        finally:
            restored.close()

    def test_leaves_no_uncompressed_intermediate_file_behind(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        backup_service.create_backup(db_path=db_path, backup_dir=backup_dir)

        remaining = list(backup_dir.iterdir())
        assert remaining == [backup_dir / remaining[0].name]
        assert remaining[0].name.endswith(".db.gz")

    def test_does_not_disturb_foreign_files_in_backup_dir(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        foreign = backup_dir / "notes.txt"
        foreign.write_text("nicht anfassen")

        backup_service.create_backup(db_path=db_path, backup_dir=backup_dir)

        assert foreign.read_text() == "nicht anfassen"

    def test_failed_write_leaves_no_partial_file_under_the_final_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        def _broken_copy(*_args: object, **_kwargs: object) -> None:
            raise OSError("No space left on device")

        monkeypatch.setattr(backup_service.shutil, "copyfileobj", _broken_copy)

        with pytest.raises(backup_service.BackupWriteError):
            backup_service.create_backup(db_path=db_path, backup_dir=backup_dir)

        assert list(backup_dir.iterdir()) == []  # kein halbes Backup unter dem Zielnamen


class TestBackupDuringConcurrentWrites:
    def test_backup_taken_while_another_connection_keeps_writing_is_fully_readable(
        self, tmp_path: Path
    ) -> None:
        """Der wichtigste Test des Meilensteins (docs/PLAN.md §9, Testfokus): Eine echte,
        unabhängige Verbindung bucht fortlaufend, während parallel gesichert wird. Das Ergebnis
        muss sich öffnen lassen, vollständige Tabellen haben und die Journal-Invariante
        (`SUM(delta) == stock`) einhalten — genau der Fall, für den die Backup-API statt `cp`
        gebraucht wird (WAL-Modus, siehe app/services/backup.py)."""
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        writer_connection = connect(db_path)
        item = writer_connection.execute("SELECT id FROM items").fetchone()
        item_id = item["id"]

        stop_writing = threading.Event()
        write_errors: list[BaseException] = []

        def keep_writing() -> None:
            while not stop_writing.is_set():
                try:
                    stock.withdraw(writer_connection, item_id=item_id, quantity=1, source="qr")
                    stock.restock(writer_connection, item_id=item_id, quantity=1, source="board")
                except BaseException as error:  # noqa: BLE001 - für die Testauswertung gesammelt
                    write_errors.append(error)
                    break

        writer_thread = threading.Thread(target=keep_writing)
        writer_thread.start()
        try:
            time.sleep(0.05)  # sicherstellen, dass der Schreiber schon läuft
            result_path = backup_service.create_backup(db_path=db_path, backup_dir=backup_dir)
        finally:
            stop_writing.set()
            writer_thread.join(timeout=5)
            writer_connection.close()

        assert write_errors == []

        restored_path = tmp_path / "restored.db"
        with gzip.open(result_path, "rb") as compressed:
            restored_path.write_bytes(compressed.read())

        restored = connect(restored_path)
        try:
            tables = {
                row["name"]
                for row in restored.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            assert {"items", "movements", "shopping_lists", "shopping_list_lines"} <= tables

            item_count = restored.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
            assert item_count == 1

            assert find_ledger_invariant_violations(restored) == []
        finally:
            restored.close()


class TestListBackups:
    def test_orders_oldest_first_and_ignores_foreign_files(self, tmp_path: Path) -> None:
        backup_dir = tmp_path
        (backup_dir / "readme.txt").write_text("kein Backup")
        newer = backup_service.format_backup_filename(datetime(2026, 1, 2, tzinfo=UTC))
        older = backup_service.format_backup_filename(datetime(2026, 1, 1, tzinfo=UTC))
        (backup_dir / newer).write_bytes(b"")
        (backup_dir / older).write_bytes(b"")

        result = backup_service.list_backups(backup_dir)

        assert [path.name for path in result] == [older, newer]


def _touch_backup(backup_dir: Path, moment: datetime) -> Path:
    path = backup_dir / backup_service.format_backup_filename(moment)
    path.write_bytes(b"")
    return path


class TestApplyRetention:
    def test_deletes_what_the_domain_rule_discards(self, tmp_path: Path) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        kept = _touch_backup(tmp_path, now)
        discarded = _touch_backup(tmp_path, now - timedelta(days=100))

        deleted = backup_service.apply_retention(
            backup_dir=tmp_path, policy=RetentionPolicy(daily=1, weekly=0), now=now, keep_path=kept
        )

        assert deleted == [discarded]
        assert not discarded.exists()
        assert kept.exists()

    def test_never_deletes_the_just_written_backup_even_if_policy_would_discard_it(
        self, tmp_path: Path
    ) -> None:
        """Eine unsinnig enge Regel (`daily=0,weekly=0`) darf das eben geschriebene Backup nicht
        mitreißen — die Domänenlogik kennt nur Zeitpunkte, `apply_retention` schützt die konkrete
        Datei zusätzlich über `keep_path` (docs/PLAN.md §9, "niemals das gerade geschriebene
        Backup")."""
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        just_written = _touch_backup(tmp_path, now)

        deleted = backup_service.apply_retention(
            backup_dir=tmp_path,
            policy=RetentionPolicy(daily=0, weekly=0),
            now=now,
            keep_path=just_written,
        )

        assert deleted == []
        assert just_written.exists()

    def test_ignores_foreign_files(self, tmp_path: Path) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        kept = _touch_backup(tmp_path, now)
        foreign = tmp_path / "notes.txt"
        foreign.write_text("nicht anfassen")

        deleted = backup_service.apply_retention(
            backup_dir=tmp_path, policy=RetentionPolicy(daily=0, weekly=0), now=now, keep_path=kept
        )

        assert deleted == []
        assert foreign.exists()


class TestRunBackup:
    def test_writes_a_backup_and_applies_retention_in_one_call(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        # daily=1, weekly=0: nur das eben geschriebene Backup bleibt übrig, unabhängig vom Alter
        # des zweiten — reicht, um die Verdrahtung zu belegen (die genaue Regel testet bereits
        # tests/domain/test_retention.py erschöpfend).
        stale = _touch_backup(backup_dir, now - timedelta(days=100))

        result = backup_service.run_backup(
            db_path=db_path, backup_dir=backup_dir, keep_spec="1d,0w", now=now
        )

        assert result.created.exists()
        assert result.created.name == backup_service.format_backup_filename(now)
        assert result.deleted == [stale]
        assert not stale.exists()

    def test_invalid_keep_spec_is_rejected_before_writing_anything(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        with pytest.raises(RetentionPolicyError):
            backup_service.run_backup(db_path=db_path, backup_dir=backup_dir, keep_spec="unsinn")

        assert list(backup_dir.iterdir()) == []  # nichts geschrieben, bevor die Regel geprüft war
