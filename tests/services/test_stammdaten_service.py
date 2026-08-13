from __future__ import annotations

import sqlite3

import pytest

from app.domain.stammdaten import StammdatenExport, StammdatenItem
from app.repo import items as items_repo
from app.repo import taxonomy as taxonomy_repo
from app.repo.movements import find_ledger_invariant_violations
from app.services import stammdaten as stammdaten_service
from app.services import stock


def _item(
    name: str = "Kaffee",
    *,
    unit: str = "Packung",
    stock: int = 2,
    reorder_level: int = 1,
    target_stock: int = 3,
    pack_size: int = 1,
    lead_days: int = 7,
    note: str | None = None,
    category: str | None = None,
    store: str | None = None,
) -> StammdatenItem:
    return StammdatenItem(
        name=name,
        unit=unit,
        note=note,
        stock=stock,
        reorder_level=reorder_level,
        target_stock=target_stock,
        pack_size=pack_size,
        lead_days=lead_days,
        category=category,
        store=store,
    )


class TestExportStammdaten:
    def test_empty_database_exports_empty_lists(self, connection: sqlite3.Connection) -> None:
        result = stammdaten_service.export_stammdaten(connection)

        assert result == StammdatenExport(categories=[], stores=[], items=[])

    def test_exports_items_with_taxonomy_names_not_ids(
        self, connection: sqlite3.Connection
    ) -> None:
        category_id = taxonomy_repo.insert(connection, "categories", name="Getränke", position=0)
        store_id = taxonomy_repo.insert(connection, "stores", name="REWE", position=0)
        stock.create_item(
            connection,
            name="Kaffee",
            unit="Packung",
            stock=2,
            reorder_level=1,
            target_stock=3,
            lead_days=7,
            category_id=category_id,
            store_id=store_id,
            position=0,
        )

        result = stammdaten_service.export_stammdaten(connection)

        assert result.categories == ["Getränke"]
        assert result.stores == ["REWE"]
        assert result.items == [
            _item(category="Getränke", store="REWE"),
        ]

    def test_archived_items_are_excluded(self, connection: sqlite3.Connection) -> None:
        item_id = stock.create_item(
            connection,
            name="Alt",
            unit="Stück",
            stock=0,
            reorder_level=0,
            target_stock=1,
            position=0,
        )
        items_repo.archive(connection, item_id, stock.utc_now_iso())

        result = stammdaten_service.export_stammdaten(connection)

        assert result.items == []


class TestImportIntoEmptyDatabase:
    def test_roundtrip_reproduces_stammdaten_with_opening_movements(
        self, connection: sqlite3.Connection
    ) -> None:
        category_id = taxonomy_repo.insert(connection, "categories", name="Getränke", position=0)
        store_id = taxonomy_repo.insert(connection, "stores", name="REWE", position=0)
        stock.create_item(
            connection,
            name="Kaffee",
            unit="Packung",
            stock=2,
            reorder_level=1,
            target_stock=3,
            lead_days=7,
            category_id=category_id,
            store_id=store_id,
            position=0,
        )
        exported = stammdaten_service.export_stammdaten(connection)

        empty_connection = _fresh_connection()
        try:
            result = stammdaten_service.import_stammdaten(empty_connection, exported)

            assert result.category_count == 1
            assert result.store_count == 1
            assert result.item_count == 1

            reimported = stammdaten_service.export_stammdaten(empty_connection)
            assert reimported == exported

            item = items_repo.list_active(empty_connection)[0]
            assert find_ledger_invariant_violations(empty_connection) == []
            assert item.stock == 2
        finally:
            empty_connection.close()

    def test_creates_taxonomy_referenced_by_items_without_duplicates(
        self, connection: sqlite3.Connection
    ) -> None:
        data = StammdatenExport(
            categories=["Getränke"],
            stores=[],
            items=[
                _item("Kaffee", category="Getränke"),
                _item("Tee", category="Getränke"),
            ],
        )

        stammdaten_service.import_stammdaten(connection, data)

        categories = taxonomy_repo.list_all(connection, "categories")
        assert [c.name for c in categories] == ["Getränke"]
        items = {item.name: item for item in items_repo.list_active(connection)}
        assert items["Kaffee"].category_id == items["Tee"].category_id == categories[0].id


def _fresh_connection() -> sqlite3.Connection:
    from pathlib import Path

    from app.migrate import migrate

    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations"
    migrate(conn, migrations_dir)
    return conn


class TestImportRejection:
    def test_conflicting_item_name_rejects_whole_import_without_writing_anything(
        self, connection: sqlite3.Connection
    ) -> None:
        stock.create_item(
            connection,
            name="Kaffee",
            unit="Packung",
            stock=1,
            reorder_level=1,
            target_stock=2,
            position=0,
        )
        before = _snapshot(connection)

        data = StammdatenExport(categories=[], stores=[], items=[_item("Kaffee"), _item("Tee")])

        with pytest.raises(stammdaten_service.StammdatenImportRejectedError) as excinfo:
            stammdaten_service.import_stammdaten(connection, data)

        assert any(
            "Kaffee" in error and "existiert bereits" in error for error in excinfo.value.errors
        )
        assert _snapshot(connection) == before  # Zeile für Zeile unverändert

    def test_conflicting_category_name_rejects_whole_import(
        self, connection: sqlite3.Connection
    ) -> None:
        taxonomy_repo.insert(connection, "categories", name="Getränke", position=0)
        before = _snapshot(connection)

        data = StammdatenExport(categories=["Getränke"], stores=[], items=[])

        with pytest.raises(stammdaten_service.StammdatenImportRejectedError) as excinfo:
            stammdaten_service.import_stammdaten(connection, data)

        assert any("Getränke" in error for error in excinfo.value.errors)
        assert _snapshot(connection) == before

    def test_duplicate_item_name_within_file_is_rejected(
        self, connection: sqlite3.Connection
    ) -> None:
        before = _snapshot(connection)
        data = StammdatenExport(categories=[], stores=[], items=[_item("Kaffee"), _item("Kaffee")])

        with pytest.raises(stammdaten_service.StammdatenImportRejectedError) as excinfo:
            stammdaten_service.import_stammdaten(connection, data)

        assert any("mehrfach" in error for error in excinfo.value.errors)
        assert _snapshot(connection) == before

    def test_item_referencing_undeclared_category_is_rejected(
        self, connection: sqlite3.Connection
    ) -> None:
        before = _snapshot(connection)
        data = StammdatenExport(
            categories=[], stores=[], items=[_item("Kaffee", category="Nirgends deklariert")]
        )

        with pytest.raises(stammdaten_service.StammdatenImportRejectedError) as excinfo:
            stammdaten_service.import_stammdaten(connection, data)

        assert any("unbekannte Kategorie" in error for error in excinfo.value.errors)
        assert _snapshot(connection) == before

    def test_domain_validation_violation_is_rejected(self, connection: sqlite3.Connection) -> None:
        before = _snapshot(connection)
        # target_stock <= reorder_level verletzt die Domänenregel (docs/PLAN.md §3).
        data = StammdatenExport(
            categories=[], stores=[], items=[_item("Kaffee", reorder_level=5, target_stock=5)]
        )

        with pytest.raises(stammdaten_service.StammdatenImportRejectedError) as excinfo:
            stammdaten_service.import_stammdaten(connection, data)

        assert any("Sollbestand" in error for error in excinfo.value.errors)
        assert _snapshot(connection) == before

    def test_multiple_problems_are_all_reported_at_once(
        self, connection: sqlite3.Connection
    ) -> None:
        data = StammdatenExport(
            categories=[],
            stores=[],
            items=[
                _item("Kaffee", category="Fehlt"),
                _item("Tee", reorder_level=5, target_stock=5),
            ],
        )

        with pytest.raises(stammdaten_service.StammdatenImportRejectedError) as excinfo:
            stammdaten_service.import_stammdaten(connection, data)

        assert len(excinfo.value.errors) >= 2


def _snapshot(connection: sqlite3.Connection) -> list[tuple[str, list[sqlite3.Row]]]:
    tables = ["items", "movements", "categories", "stores"]
    return [(table, connection.execute(f"SELECT * FROM {table}").fetchall()) for table in tables]
