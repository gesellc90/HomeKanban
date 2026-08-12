"""Etikettenraster und Bogenaufteilung, siehe docs/PLAN.md §5 und §9 (M5).

Hier steht die Frage „welches Etikett landet auf welchem Bogen in welcher Zelle“ — und sonst
nichts. Reine Logik: kein SQL, kein I/O, kein HTML. Millimeter kommen als Eingabe vor (ein Raster
ist nun einmal in Millimetern definiert, und die Prüfung gegen das A4-Blatt ist eine reine Regel),
aber nichts hier formatiert Millimeter für die Ausgabe — das tut die Druckansicht.

Zwei Aufgabenteilungen, die den Rest der Datei erklären:

- **`validate_grid` meldet, `paginate_labels` rechnet.** Unsinnige Rasterwerte werden von
  `validate_grid` als deutsche Meldung gemeldet, damit die Web-Schicht mit einem
  Nicht-500-Status antworten kann. `paginate_labels` wirft trotzdem nie — es behandelt kaputte
  Eingaben still als „nichts zu drucken“ (CLAUDE.md §8: Fehlbedienung endet nie in einem
  Stacktrace).
- **Leere Zellen sind Zellen.** Ein Bogen liefert immer *alle* seine Zellen, auch die leeren am
  Ende — sonst wüsste der Aufrufer nicht, wie viel Bogen ungenutzt bleibt, und ein Renderer, der
  die Zellen der Reihe nach setzt (CSS-Grid, Tabelle), bekäme ein verrutschtes Raster. Die
  Druckansicht positioniert absolut in Millimetern und zeichnet deshalb nur die belegten Zellen;
  `used_slots` liefert genau die.

**Bewusst nicht enthalten: eine wählbare Startposition** für angebrochene Bögen. Mit dem Nutzer
entschieden (M5, Fragerunde 1): Jeder Druck beginnt bei Zelle 1, ein Nachdruck einzelner Etiketten
(R9) verbraucht damit einen frischen Bogen. Das hält Oberfläche und Logik einfacher; kommt der
Wunsch später doch, ist es ein Versatz in `paginate_labels` und ein Formularfeld.
"""

from __future__ import annotations

from dataclasses import dataclass

A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0


@dataclass(frozen=True)
class LabelGrid:
    """Ein Etikettenraster auf A4, so wie es die Bogenpackung angibt.

    Alle Maße in Millimetern. `margin_left_mm`/`margin_top_mm` sind die Ränder bis zur ersten
    Zelle, die Abstände liegen *zwischen* den Zellen, nicht am Rand.
    """

    columns: int
    rows: int
    label_width_mm: float
    label_height_mm: float
    margin_left_mm: float = 0.0
    margin_top_mm: float = 0.0
    column_gap_mm: float = 0.0
    row_gap_mm: float = 0.0

    @property
    def cells_per_sheet(self) -> int:
        """Zellen je Bogen. Bei kaputtem Raster (null oder negativ) bewusst `0`, nie negativ."""
        if self.columns < 1 or self.rows < 1:
            return 0
        return self.columns * self.rows

    @property
    def used_width_mm(self) -> float:
        """Vom Blattrand bis zur rechten Kante der letzten Spalte."""
        if self.columns < 1:
            return 0.0
        return (
            self.margin_left_mm
            + self.columns * self.label_width_mm
            + (self.columns - 1) * self.column_gap_mm
        )

    @property
    def used_height_mm(self) -> float:
        if self.rows < 1:
            return 0.0
        return (
            self.margin_top_mm
            + self.rows * self.label_height_mm
            + (self.rows - 1) * self.row_gap_mm
        )


@dataclass(frozen=True)
class GridPreset:
    """Ein benanntes Raster für die Auswahlseite.

    Die Maße folgen den gängigen A4-Etikettenbögen, sind aber **nicht** vom Hersteller bestätigt —
    Papierformate schwanken je Charge und Marke. Deshalb gibt es zusätzlich das frei einstellbare
    Raster und die Kalibrierseite: Was am Ende zählt, ist das Lineal auf dem echten Ausdruck.
    """

    key: str
    label: str
    grid: LabelGrid


GRID_PRESETS: tuple[GridPreset, ...] = (
    GridPreset(
        key="70x37",
        label="70 × 37 mm — 24 je Bogen (3 × 8)",
        grid=LabelGrid(
            columns=3, rows=8, label_width_mm=70.0, label_height_mm=37.0, margin_top_mm=0.5
        ),
    ),
    GridPreset(
        key="63x38",
        label="63,5 × 38,1 mm — 21 je Bogen (3 × 7)",
        grid=LabelGrid(
            columns=3,
            rows=7,
            label_width_mm=63.5,
            label_height_mm=38.1,
            margin_left_mm=7.75,
            margin_top_mm=15.15,
            column_gap_mm=2.5,
        ),
    ),
    GridPreset(
        key="48x25",
        label="48,5 × 25,4 mm — 40 je Bogen (4 × 10)",
        grid=LabelGrid(
            columns=4,
            rows=10,
            label_width_mm=48.5,
            label_height_mm=25.4,
            margin_left_mm=8.0,
            margin_top_mm=21.5,
        ),
    ),
)

DEFAULT_GRID_KEY = "70x37"

# Schlüssel des frei einstellbaren Rasters — kein Preset, sondern „nimm die Formularwerte“.
CUSTOM_GRID_KEY = "frei"


def preset_by_key(key: str) -> GridPreset | None:
    for preset in GRID_PRESETS:
        if preset.key == key:
            return preset
    return None


def default_grid() -> LabelGrid:
    preset = preset_by_key(DEFAULT_GRID_KEY)
    assert preset is not None  # DEFAULT_GRID_KEY steht in GRID_PRESETS — durch Test abgesichert.
    return preset.grid


@dataclass(frozen=True)
class LabelSlot:
    """Eine Zelle des Bogens. `label_index` zeigt in die übergebene Etikettenliste.

    `None` heißt: Zelle bleibt leer, weil die Etiketten ausgegangen sind.
    """

    row: int
    column: int
    label_index: int | None

    @property
    def is_empty(self) -> bool:
        return self.label_index is None


@dataclass(frozen=True)
class LabelSheet:
    number: int  # 1-basiert, so wie im Ausdruck gezählt wird
    slots: tuple[LabelSlot, ...]

    @property
    def used_slots(self) -> tuple[LabelSlot, ...]:
        return tuple(slot for slot in self.slots if not slot.is_empty)


def validate_grid(grid: LabelGrid) -> list[str]:
    """Liefert deutsche Fehlermeldungen zum Raster; eine leere Liste heißt: alles gut.

    Gleiche Bauart wie `validate_item` in `app/domain/validation.py`: melden statt werfen, damit
    die Web-Schicht das Formular mit `422` und lesbarem Text zurückgeben kann.
    """
    errors: list[str] = []

    if grid.columns < 1:
        errors.append("Das Raster braucht mindestens eine Spalte.")
    if grid.rows < 1:
        errors.append("Das Raster braucht mindestens eine Zeile.")
    if grid.label_width_mm <= 0:
        errors.append("Die Etikettenbreite muss größer als 0 mm sein.")
    if grid.label_height_mm <= 0:
        errors.append("Die Etikettenhöhe muss größer als 0 mm sein.")
    if grid.margin_left_mm < 0 or grid.margin_top_mm < 0:
        errors.append("Die Ränder dürfen nicht negativ sein.")
    if grid.column_gap_mm < 0 or grid.row_gap_mm < 0:
        errors.append("Die Abstände zwischen den Etiketten dürfen nicht negativ sein.")

    # Passt das Raster überhaupt aufs Blatt? Erst prüfen, wenn die Einzelmaße plausibel sind —
    # sonst folgt auf „Breite muss größer als 0 sein“ noch eine verwirrende zweite Meldung.
    if not errors:
        if grid.used_width_mm > A4_WIDTH_MM:
            errors.append(
                f"Das Raster ist mit {grid.used_width_mm:.1f} mm breiter als ein A4-Blatt "
                f"({A4_WIDTH_MM:.0f} mm)."
            )
        if grid.used_height_mm > A4_HEIGHT_MM:
            errors.append(
                f"Das Raster ist mit {grid.used_height_mm:.1f} mm höher als ein A4-Blatt "
                f"({A4_HEIGHT_MM:.0f} mm)."
            )

    return errors


def paginate_labels(*, label_count: int, grid: LabelGrid) -> tuple[LabelSheet, ...]:
    """Verteilt `label_count` Etiketten zeilenweise auf Bögen des Rasters `grid`.

    Wirft nie. Randfälle:

    - `label_count <= 0` → keine Bögen (leere Auswahl ist kein Fehler, nur nichts zu drucken)
    - Raster ohne Spalten oder Zeilen → keine Bögen statt Division durch null
    - mehr Etiketten als Zellen → so viele Bögen, wie nötig sind; der letzte bleibt teils leer
    """
    cells = grid.cells_per_sheet
    if cells == 0 or label_count <= 0:
        return ()

    sheets: list[LabelSheet] = []
    next_label = 0
    sheet_number = 1
    while next_label < label_count:
        slots: list[LabelSlot] = []
        for cell in range(cells):
            row, column = divmod(cell, grid.columns)
            if next_label >= label_count:
                slots.append(LabelSlot(row=row, column=column, label_index=None))
                continue
            slots.append(LabelSlot(row=row, column=column, label_index=next_label))
            next_label += 1
        sheets.append(LabelSheet(number=sheet_number, slots=tuple(slots)))
        sheet_number += 1

    return tuple(sheets)
