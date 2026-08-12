"""Tests für `migrations/0001_init.sql`: Tabellen, CHECK-Regeln, partielle Unique-Indizes.

Prüft direkt gegen die Produktionsmigration (nicht gegen Fixtures wie tests/test_migrate.py),
mit rohem SQL statt der Repository-Schicht, um die Datenbankregeln selbst zu testen.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from app.migrate import migrate

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_NOW = "2026-01-01T00:00:00.000Z"


@pytest.fixture
def raw_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_minimal_item(
    connection: sqlite3.Connection,
    *,
    name: str = "Kaffee",
    stock: int = 1,
    reorder_level: int = 0,
    target_stock: int = 1,
    pack_size: int = 1,
    position: int = 0,
    qr_token: str | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO items (
            name, unit, stock, reorder_level, target_stock, pack_size,
            qr_token, position, created_at, updated_at
        ) VALUES (?, 'Packung', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            stock,
            reorder_level,
            target_stock,
            pack_size,
            qr_token or f"token-{uuid.uuid4().hex}",
            position,
            _NOW,
            _NOW,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _create_open_list(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        "INSERT INTO shopping_lists (status, created_at) VALUES ('open', ?)", (_NOW,)
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def test_0001_init_creates_all_seven_tables(raw_connection: sqlite3.Connection) -> None:
    applied = migrate(raw_connection, MIGRATIONS_DIR)

    assert "0001_init.sql" in applied
    tables = {
        row[0]
        for row in raw_connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {
        "items",
        "movements",
        "shopping_lists",
        "shopping_list_lines",
        "categories",
        "stores",
        "schema_migrations",
    } <= tables


def test_0001_init_is_idempotent_on_second_run(raw_connection: sqlite3.Connection) -> None:
    first_run = migrate(raw_connection, MIGRATIONS_DIR)
    second_run = migrate(raw_connection, MIGRATIONS_DIR)

    assert "0001_init.sql" in first_run
    assert second_run == []


class TestItemChecks:
    def test_negative_stock_is_rejected(self, raw_connection: sqlite3.Connection) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)

        with pytest.raises(sqlite3.IntegrityError):
            _create_minimal_item(raw_connection, stock=-1)

    def test_negative_reorder_level_is_rejected(self, raw_connection: sqlite3.Connection) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)

        with pytest.raises(sqlite3.IntegrityError):
            _create_minimal_item(raw_connection, reorder_level=-1, target_stock=1)

    def test_pack_size_below_one_is_rejected(self, raw_connection: sqlite3.Connection) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)

        with pytest.raises(sqlite3.IntegrityError):
            _create_minimal_item(raw_connection, pack_size=0)

    def test_target_stock_must_be_greater_than_reorder_level(
        self, raw_connection: sqlite3.Connection
    ) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)

        with pytest.raises(sqlite3.IntegrityError):
            _create_minimal_item(raw_connection, reorder_level=5, target_stock=5)

    def test_duplicate_active_name_case_insensitive_is_rejected(
        self, raw_connection: sqlite3.Connection
    ) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        _create_minimal_item(raw_connection, name="Kaffee")

        with pytest.raises(sqlite3.IntegrityError):
            _create_minimal_item(raw_connection, name="KAFFEE")

    def test_archived_item_does_not_block_reusing_the_name(
        self, raw_connection: sqlite3.Connection
    ) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        first_id = _create_minimal_item(raw_connection, name="Kaffee")
        raw_connection.execute("UPDATE items SET archived_at = ? WHERE id = ?", (_NOW, first_id))

        # Darf nicht scheitern: der ursprüngliche Artikel ist archiviert.
        second_id = _create_minimal_item(raw_connection, name="Kaffee")
        assert second_id != first_id


class TestShoppingListChecks:
    def test_at_most_one_open_list(self, raw_connection: sqlite3.Connection) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        _create_open_list(raw_connection)

        with pytest.raises(sqlite3.IntegrityError):
            _create_open_list(raw_connection)

    def test_multiple_closed_lists_are_allowed(self, raw_connection: sqlite3.Connection) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        raw_connection.execute(
            "INSERT INTO shopping_lists (status, created_at) VALUES ('done', ?)", (_NOW,)
        )
        raw_connection.execute(
            "INSERT INTO shopping_lists (status, created_at) VALUES ('cancelled', ?)", (_NOW,)
        )

        count = raw_connection.execute("SELECT COUNT(*) FROM shopping_lists").fetchone()[0]
        assert count == 2

    def test_item_has_at_most_one_active_line_per_list(
        self, raw_connection: sqlite3.Connection
    ) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        item_id = _create_minimal_item(raw_connection)
        list_id = _create_open_list(raw_connection)
        raw_connection.execute(
            """
            INSERT INTO shopping_list_lines (
                list_id, item_id, suggested_qty, name_snapshot, unit_snapshot, position
            ) VALUES (?, ?, 1, 'Kaffee', 'Packung', 0)
            """,
            (list_id, item_id),
        )

        with pytest.raises(sqlite3.IntegrityError):
            raw_connection.execute(
                """
                INSERT INTO shopping_list_lines (
                    list_id, item_id, suggested_qty, name_snapshot, unit_snapshot, position
                ) VALUES (?, ?, 1, 'Kaffee', 'Packung', 1)
                """,
                (list_id, item_id),
            )

    def test_dropped_line_does_not_block_a_new_active_line(
        self, raw_connection: sqlite3.Connection
    ) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        item_id = _create_minimal_item(raw_connection)
        list_id = _create_open_list(raw_connection)
        raw_connection.execute(
            """
            INSERT INTO shopping_list_lines (
                list_id, item_id, suggested_qty, name_snapshot, unit_snapshot, position, dropped_at
            ) VALUES (?, ?, 1, 'Kaffee', 'Packung', 0, ?)
            """,
            (list_id, item_id, _NOW),
        )

        # Darf nicht scheitern: die vorhandene Position ist verworfen.
        raw_connection.execute(
            """
            INSERT INTO shopping_list_lines (
                list_id, item_id, suggested_qty, name_snapshot, unit_snapshot, position
            ) VALUES (?, ?, 1, 'Kaffee', 'Packung', 1)
            """,
            (list_id, item_id),
        )


class TestMovementChecks:
    def test_unknown_kind_is_rejected(self, raw_connection: sqlite3.Connection) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        item_id = _create_minimal_item(raw_connection)

        with pytest.raises(sqlite3.IntegrityError):
            raw_connection.execute(
                """
                INSERT INTO movements (item_id, kind, delta, stock_after, source, created_at)
                VALUES (?, 'unbekannt', 1, 1, 'board', ?)
                """,
                (item_id, _NOW),
            )

    def test_unknown_source_is_rejected(self, raw_connection: sqlite3.Connection) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        item_id = _create_minimal_item(raw_connection)

        with pytest.raises(sqlite3.IntegrityError):
            raw_connection.execute(
                """
                INSERT INTO movements (item_id, kind, delta, stock_after, source, created_at)
                VALUES (?, 'opening', 1, 1, 'unbekannt', ?)
                """,
                (item_id, _NOW),
            )

    def test_reverts_movement_id_is_unique(self, raw_connection: sqlite3.Connection) -> None:
        migrate(raw_connection, MIGRATIONS_DIR)
        item_id = _create_minimal_item(raw_connection)
        original = raw_connection.execute(
            """
            INSERT INTO movements (item_id, kind, delta, stock_after, source, created_at)
            VALUES (?, 'withdrawal', -1, 0, 'qr', ?)
            """,
            (item_id, _NOW),
        ).lastrowid
        raw_connection.execute(
            """
            INSERT INTO movements (
                item_id, kind, delta, stock_after, source, reverts_movement_id, created_at
            ) VALUES (?, 'withdrawal', 1, 1, 'qr', ?, ?)
            """,
            (item_id, original, _NOW),
        )

        with pytest.raises(sqlite3.IntegrityError):
            raw_connection.execute(
                """
                INSERT INTO movements (
                    item_id, kind, delta, stock_after, source, reverts_movement_id, created_at
                ) VALUES (?, 'withdrawal', 1, 1, 'qr', ?, ?)
                """,
                (item_id, original, _NOW),
            )


class Test0002ShoppingListTaxonomySnapshots:
    """0002_shopping_list_taxonomy_snapshots.sql — M7, Frage 1 (docs/PLAN.md §9)."""

    def test_adds_four_nullable_columns_to_shopping_list_lines(
        self, raw_connection: sqlite3.Connection
    ) -> None:
        applied = migrate(raw_connection, MIGRATIONS_DIR)

        assert "0002_shopping_list_taxonomy_snapshots.sql" in applied
        columns = {
            row["name"] for row in raw_connection.execute("PRAGMA table_info(shopping_list_lines)")
        }
        assert {
            "store_snapshot",
            "store_position_snapshot",
            "category_snapshot",
            "category_position_snapshot",
        } <= columns

    def test_existing_database_with_data_survives_the_upgrade(
        self, raw_connection: sqlite3.Connection
    ) -> None:
        """Simuliert eine Datenbank, auf der bisher nur `0001_init.sql` lief: Zeilen aus der Zeit
        vor der Migration müssen intakt bleiben (CLAUDE.md §4, keine destruktive Operation ohne
        beschriebenen Rückweg — hier reicht die additive Migration selbst als Rückweg: Ein Rollback
        ist nicht nötig, die alten Spalten bleiben unangetastet)."""
        init_sql = (MIGRATIONS_DIR / "0001_init.sql").read_text(encoding="utf-8")
        raw_connection.executescript(f"BEGIN;\n{init_sql}\nCOMMIT;")
        raw_connection.execute(
            "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT)"
        )
        raw_connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES ('0001_init.sql', ?)",
            (_NOW,),
        )

        item_id = _create_minimal_item(raw_connection, name="Kaffee")
        list_id = _create_open_list(raw_connection)
        raw_connection.execute(
            """
            INSERT INTO shopping_list_lines (
                list_id, item_id, suggested_qty, name_snapshot, unit_snapshot, position
            ) VALUES (?, ?, 1, 'Kaffee', 'Packung', 0)
            """,
            (list_id, item_id),
        )

        applied = migrate(raw_connection, MIGRATIONS_DIR)

        assert applied == ["0002_shopping_list_taxonomy_snapshots.sql"]
        line = raw_connection.execute(
            "SELECT * FROM shopping_list_lines WHERE list_id = ?", (list_id,)
        ).fetchone()
        assert line["name_snapshot"] == "Kaffee"
        assert line["unit_snapshot"] == "Packung"
        assert line["store_snapshot"] is None
        assert line["category_position_snapshot"] is None
