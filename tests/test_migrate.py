"""Tests für den Migrationsrunner.

Es gibt in M0 noch keine echte Schemadatei (die kommt mit `0001_init.sql` erst in M1) — getestet
wird daher gegen Fixture-Migrationen in tests/fixtures/migrations/, nicht gegen Produktionsdateien.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.migrate import migrate

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "migrations"


@pytest.fixture
def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def test_applies_all_pending_migrations_in_order(connection: sqlite3.Connection) -> None:
    applied = migrate(connection, FIXTURES_DIR)

    assert applied == ["0001_create_widgets.sql", "0002_seed_widgets.sql"]
    rows = connection.execute("SELECT name FROM widgets").fetchall()
    assert [row["name"] for row in rows] == ["erste"]


def test_running_twice_is_idempotent_and_does_not_reapply(
    connection: sqlite3.Connection,
) -> None:
    first_run = migrate(connection, FIXTURES_DIR)
    second_run = migrate(connection, FIXTURES_DIR)

    assert first_run == ["0001_create_widgets.sql", "0002_seed_widgets.sql"]
    assert second_run == []
    rows = connection.execute("SELECT name FROM widgets").fetchall()
    assert [row["name"] for row in rows] == ["erste"]


def test_records_applied_versions_in_schema_migrations(
    connection: sqlite3.Connection,
) -> None:
    migrate(connection, FIXTURES_DIR)

    versions = {
        row["version"] for row in connection.execute("SELECT version FROM schema_migrations")
    }
    assert versions == {"0001_create_widgets.sql", "0002_seed_widgets.sql"}


def test_failed_migration_is_rolled_back_completely(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    broken_dir = tmp_path / "migrations"
    broken_dir.mkdir()
    (broken_dir / "0001_broken.sql").write_text(
        "CREATE TABLE ok (id INTEGER);\nINSERT INTO does_not_exist VALUES (1);\n",
        encoding="utf-8",
    )

    with pytest.raises(sqlite3.OperationalError):
        migrate(connection, broken_dir)

    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "ok" not in tables

    versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    assert versions == set()
