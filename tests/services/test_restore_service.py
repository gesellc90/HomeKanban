from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import pytest

from app.db import connect
from app.migrate import migrate
from app.repo import shopping_lists as lists_repo
from app.repo.movements import find_ledger_invariant_violations
from app.services import backup as backup_service
from app.services import restore as restore_service
from app.services import shopping as shopping_service
from app.services import stock

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def _make_database(db_path: Path, *, item_name: str = "Testartikel") -> int:
    connection = connect(db_path)
    try:
        migrate(connection, MIGRATIONS_DIR)
        item_id = stock.create_item(
            connection,
            name=item_name,
            unit="Packung",
            stock=5,
            reorder_level=1,
            target_stock=10,
            position=0,
        )
    finally:
        connection.close()
    return item_id


class TestRestoreValidation:
    def test_missing_backup_file_raises_understandable_error(self, tmp_path: Path) -> None:
        with pytest.raises(restore_service.BackupFileMissingError):
            restore_service.restore_backup(
                backup_path=tmp_path / "fehlt.db.gz", db_path=tmp_path / "homekanban.db"
            )

    def test_missing_target_dir_raises_understandable_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "source.db"
        _make_database(db_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_path = backup_service.create_backup(db_path=db_path, backup_dir=backup_dir)

        with pytest.raises(restore_service.RestoreDirectoryError):
            restore_service.restore_backup(
                backup_path=backup_path, db_path=tmp_path / "fehlt" / "homekanban.db"
            )

    def test_not_gzip_raises_corrupt_error_and_does_not_touch_existing_database(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        broken_backup = tmp_path / "broken.db.gz"
        broken_backup.write_bytes(b"das ist kein gzip")

        with pytest.raises(restore_service.BackupFileCorruptError):
            restore_service.restore_backup(backup_path=broken_backup, db_path=db_path)

        # Nichts wurde beiseitegelegt oder überschrieben.
        connection = connect(db_path)
        try:
            assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        finally:
            connection.close()
        assert list(tmp_path.glob("*.vor-restore-*")) == []

    def test_gzip_of_non_sqlite_content_raises_corrupt_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path)
        broken_backup = tmp_path / "broken.db.gz"
        with gzip.open(broken_backup, "wb") as compressed:
            compressed.write(b"kein sqlite, nur text")

        with pytest.raises(restore_service.BackupFileCorruptError):
            restore_service.restore_backup(backup_path=broken_backup, db_path=db_path)

    def test_gzip_of_unrelated_sqlite_db_raises_corrupt_error_missing_core_tables(
        self, tmp_path: Path
    ) -> None:
        unrelated_db = tmp_path / "unrelated.db"
        connection = sqlite3.connect(unrelated_db)
        connection.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY)")
        connection.commit()
        connection.close()

        backup_path = tmp_path / "unrelated.db.gz"
        with open(unrelated_db, "rb") as raw, gzip.open(backup_path, "wb") as compressed:
            compressed.write(raw.read())

        with pytest.raises(restore_service.BackupFileCorruptError):
            restore_service.restore_backup(
                backup_path=backup_path, db_path=tmp_path / "homekanban.db"
            )


class TestRestoreRoundtrip:
    def test_restores_into_an_empty_target_and_holds_the_ledger_invariant(
        self, tmp_path: Path
    ) -> None:
        source_db = tmp_path / "source.db"
        item_id = _make_database(source_db)
        source_connection = connect(source_db)
        try:
            # Artikel und Bewegungen: Entnahme, die den Artikel unter die Schwelle drückt, plus
            # ein Teil-Zugang.
            stock.withdraw(source_connection, item_id=item_id, quantity=5, source="qr")
            stock.restock(source_connection, item_id=item_id, quantity=1, source="board")
            # Einkaufsliste: der Abgleich legt wegen der Entnahme automatisch eine offene Position
            # für den Artikel an (Bestand jetzt 1, Schwelle 1 → NACHKAUFEN).
            list_row, _plan = shopping_service.create_or_reconcile_list(source_connection)
            lines_before = lists_repo.list_lines(source_connection, list_row.id)
        finally:
            source_connection.close()

        assert len(lines_before) == 1
        assert lines_before[0].name_snapshot == "Testartikel"

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_path = backup_service.create_backup(db_path=source_db, backup_dir=backup_dir)

        target_db = tmp_path / "restored" / "homekanban.db"
        target_db.parent.mkdir()

        result = restore_service.restore_backup(backup_path=backup_path, db_path=target_db)

        assert result.restored_path == target_db
        assert result.moved_aside == []

        restored_connection = connect(target_db)
        try:
            item = restored_connection.execute("SELECT * FROM items").fetchone()
            assert item["name"] == "Testartikel"
            assert item["stock"] == 1  # 5 - 5 + 1
            assert find_ledger_invariant_violations(restored_connection) == []

            restored_list = lists_repo.get_open_list(restored_connection)
            assert restored_list is not None
            restored_lines = lists_repo.list_lines(restored_connection, restored_list.id)
            assert len(restored_lines) == 1
            assert restored_lines[0].name_snapshot == "Testartikel"
            assert restored_lines[0].suggested_qty == lines_before[0].suggested_qty
        finally:
            restored_connection.close()

    def test_moves_existing_database_aside_instead_of_deleting_it(self, tmp_path: Path) -> None:
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path, item_name="Alter Artikel")

        other_db = tmp_path / "other.db"
        _make_database(other_db, item_name="Neuer Artikel")
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_path = backup_service.create_backup(db_path=other_db, backup_dir=backup_dir)

        result = restore_service.restore_backup(backup_path=backup_path, db_path=db_path)

        assert len(result.moved_aside) == 1
        moved_original = result.moved_aside[0]
        assert moved_original.exists()
        assert moved_original.name.startswith("homekanban.db.vor-restore-")

        # Nichts verloren: der alte Stand ist noch da, unter dem neuen Namen.
        moved_connection = sqlite3.connect(moved_original)
        moved_connection.row_factory = sqlite3.Row
        try:
            assert (
                moved_connection.execute("SELECT name FROM items").fetchone()["name"]
                == "Alter Artikel"
            )
        finally:
            moved_connection.close()

        # Der Zielpfad zeigt jetzt den restaurierten Stand.
        restored_connection = connect(db_path)
        try:
            assert (
                restored_connection.execute("SELECT name FROM items").fetchone()["name"]
                == "Neuer Artikel"
            )
        finally:
            restored_connection.close()

    def test_stray_wal_and_shm_files_do_not_leak_into_the_restored_database(
        self, tmp_path: Path
    ) -> None:
        """Der im Auftrag genannte, leicht übersehene Fall: liegengebliebene `-wal`/`-shm`-Dateien
        neben der alten Datenbank dürfen den zurückgespielten Stand nicht überschreiben."""
        db_path = tmp_path / "homekanban.db"
        _make_database(db_path, item_name="Alter Artikel")
        # Simuliert einen nicht sauber beendeten Container: Reste einer WAL-Sitzung liegen noch
        # neben der alten Datenbank.
        wal_path = db_path.with_name(db_path.name + "-wal")
        shm_path = db_path.with_name(db_path.name + "-shm")
        wal_path.write_bytes(b"stray-wal-bytes")
        shm_path.write_bytes(b"stray-shm-bytes")

        other_db = tmp_path / "other.db"
        _make_database(other_db, item_name="Neuer Artikel")
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_path = backup_service.create_backup(db_path=other_db, backup_dir=backup_dir)

        result = restore_service.restore_backup(backup_path=backup_path, db_path=db_path)

        # Die alten Begleitdateien liegen jetzt unter dem neuen Namen, nicht mehr unter dem alten.
        assert not wal_path.exists()
        assert not shm_path.exists()
        assert len(result.moved_aside) == 3  # db, -wal, -shm

        restored_connection = connect(db_path)
        try:
            assert (
                restored_connection.execute("SELECT name FROM items").fetchone()["name"]
                == "Neuer Artikel"
            )
            assert find_ledger_invariant_violations(restored_connection) == []
        finally:
            restored_connection.close()

    def test_restoring_when_nothing_exists_yet_leaves_moved_aside_empty(
        self, tmp_path: Path
    ) -> None:
        source_db = tmp_path / "source.db"
        _make_database(source_db)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_path = backup_service.create_backup(db_path=source_db, backup_dir=backup_dir)

        target_db = tmp_path / "fresh" / "homekanban.db"
        target_db.parent.mkdir()

        result = restore_service.restore_backup(backup_path=backup_path, db_path=target_db)

        assert result.moved_aside == []
        assert target_db.exists()
