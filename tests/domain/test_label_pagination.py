"""Bogenaufteilung und Rasterprüfung, tabellengetrieben (docs/PLAN.md §9 M5, §11).

Der Testfokus aus §9 für M5 lautet „Umbruch auf mehrere Bögen, Auswahl leer“. Dazu kommen die
Randfälle, die laut Auftrag **keine** Ausnahme werfen dürfen: keine Artikel, mehr Artikel als
Zellen, Raster mit null Spalten oder Zeilen.
"""

from __future__ import annotations

import pytest

from app.domain.labels import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    DEFAULT_GRID_KEY,
    GRID_PRESETS,
    LabelGrid,
    default_grid,
    paginate_labels,
    preset_by_key,
    validate_grid,
)

# Ein handliches Raster für die Aufteilungstabelle: 2 × 3 = 6 Zellen je Bogen.
SMALL = LabelGrid(columns=2, rows=3, label_width_mm=70.0, label_height_mm=37.0)


class TestPagination:
    @pytest.mark.parametrize(
        ("label_count", "expected_sheets", "expected_used_per_sheet"),
        [
            (0, 0, []),  # leere Auswahl: kein Fehler, nur nichts zu drucken
            (1, 1, [1]),
            (5, 1, [5]),
            (6, 1, [6]),  # genau voll
            (7, 2, [6, 1]),  # ein Etikett zu viel
            (12, 2, [6, 6]),  # genau zwei volle Bögen
            (13, 3, [6, 6, 1]),
        ],
    )
    def test_distribution(
        self, label_count: int, expected_sheets: int, expected_used_per_sheet: list[int]
    ) -> None:
        sheets = paginate_labels(label_count=label_count, grid=SMALL)

        assert len(sheets) == expected_sheets
        assert [len(sheet.used_slots) for sheet in sheets] == expected_used_per_sheet

    def test_every_sheet_reports_all_its_cells_including_the_empty_ones(self) -> None:
        """Ein Bogen liefert immer alle Zellen — die leeren am Ende sind als solche erkennbar."""
        sheets = paginate_labels(label_count=7, grid=SMALL)

        assert all(len(sheet.slots) == SMALL.cells_per_sheet for sheet in sheets)
        assert [slot.is_empty for slot in sheets[1].slots] == [False, True, True, True, True, True]

    def test_labels_are_placed_row_by_row_without_gaps_or_repeats(self) -> None:
        sheets = paginate_labels(label_count=8, grid=SMALL)

        placed = [slot.label_index for sheet in sheets for slot in sheet.slots if not slot.is_empty]
        assert placed == list(range(8)), "jedes Etikett genau einmal, in der Eingabereihenfolge"

        first_sheet_coordinates = [(slot.row, slot.column) for slot in sheets[0].slots]
        assert first_sheet_coordinates == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]

    def test_sheets_are_numbered_from_one(self) -> None:
        sheets = paginate_labels(label_count=13, grid=SMALL)
        assert [sheet.number for sheet in sheets] == [1, 2, 3]

    @pytest.mark.parametrize(
        "broken",
        [
            LabelGrid(columns=0, rows=3, label_width_mm=70.0, label_height_mm=37.0),
            LabelGrid(columns=2, rows=0, label_width_mm=70.0, label_height_mm=37.0),
            LabelGrid(columns=-1, rows=-1, label_width_mm=70.0, label_height_mm=37.0),
        ],
    )
    def test_a_grid_without_cells_yields_no_sheets_instead_of_dividing_by_zero(
        self, broken: LabelGrid
    ) -> None:
        assert broken.cells_per_sheet == 0
        assert paginate_labels(label_count=10, grid=broken) == ()

    def test_negative_label_count_is_treated_like_an_empty_selection(self) -> None:
        assert paginate_labels(label_count=-3, grid=SMALL) == ()


class TestGridValidation:
    def test_a_sane_grid_has_no_complaints(self) -> None:
        assert validate_grid(SMALL) == []

    @pytest.mark.parametrize("preset", GRID_PRESETS, ids=[p.key for p in GRID_PRESETS])
    def test_every_preset_fits_on_a4(self, preset: object) -> None:
        grid = preset.grid  # type: ignore[attr-defined]
        assert validate_grid(grid) == []
        assert grid.used_width_mm <= A4_WIDTH_MM
        assert grid.used_height_mm <= A4_HEIGHT_MM

    def test_the_default_grid_key_actually_exists(self) -> None:
        assert preset_by_key(DEFAULT_GRID_KEY) is not None
        assert default_grid().cells_per_sheet == 24

    def test_unknown_preset_key_is_not_invented(self) -> None:
        assert preset_by_key("gibt-es-nicht") is None

    @pytest.mark.parametrize(
        ("grid", "expected_fragment"),
        [
            (
                LabelGrid(columns=0, rows=3, label_width_mm=70.0, label_height_mm=37.0),
                "mindestens eine Spalte",
            ),
            (
                LabelGrid(columns=2, rows=0, label_width_mm=70.0, label_height_mm=37.0),
                "mindestens eine Zeile",
            ),
            (
                LabelGrid(columns=2, rows=3, label_width_mm=0.0, label_height_mm=37.0),
                "Etikettenbreite",
            ),
            (
                LabelGrid(columns=2, rows=3, label_width_mm=70.0, label_height_mm=-5.0),
                "Etikettenhöhe",
            ),
            (
                LabelGrid(
                    columns=2, rows=3, label_width_mm=70.0, label_height_mm=37.0, margin_left_mm=-1
                ),
                "Ränder",
            ),
            (
                LabelGrid(
                    columns=2, rows=3, label_width_mm=70.0, label_height_mm=37.0, row_gap_mm=-2
                ),
                "Abstände",
            ),
            (
                LabelGrid(columns=4, rows=3, label_width_mm=70.0, label_height_mm=37.0),
                "breiter als ein A4-Blatt",
            ),
            (
                LabelGrid(columns=2, rows=9, label_width_mm=70.0, label_height_mm=37.0),
                "höher als ein A4-Blatt",
            ),
        ],
    )
    def test_nonsense_is_reported_in_german(self, grid: LabelGrid, expected_fragment: str) -> None:
        errors = validate_grid(grid)

        assert errors, "unsinnige Rasterwerte müssen gemeldet werden"
        assert any(expected_fragment in error for error in errors), errors

    def test_a_broken_size_does_not_also_trigger_the_a4_message(self) -> None:
        """Auf „Breite muss größer als 0 sein“ soll keine verwirrende zweite Meldung folgen."""
        errors = validate_grid(
            LabelGrid(columns=2, rows=3, label_width_mm=0.0, label_height_mm=37.0)
        )

        assert not any("A4-Blatt" in error for error in errors), errors
