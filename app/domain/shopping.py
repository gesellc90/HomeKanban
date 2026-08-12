"""Abgleich der offenen Einkaufsliste, siehe docs/PLAN.md §6.

Der Abgleich (`reconciliation`) läuft bei „Liste erzeugen“ **und** bei jedem Export identisch:
er leitet aus dem aktuellen Zustand ab, welche Positionen anzufügen, welche zu verwerfen und
welche neu zu berechnen sind. Hier steht nur die Entscheidung — Ausführung und Transaktion
liegen in `app/services/shopping.py`.

Reine Logik: kein SQL, kein I/O.

**Zur Kollision zwischen §4 Regel 5 und `ux_shopping_list_lines_active`:** Der partielle
Unique-Index lässt je Liste höchstens eine *nicht verworfene* Position pro Artikel zu, und eine
abgehakte Position ist nicht verworfen. Ein teilweise gekaufter Artikel kann seine Restposition
deshalb nicht in derselben Liste bekommen. Entschieden (mit dem Nutzer, siehe docs/PLAN.md §4
Regel 5): Angefügt wird nur für Artikel **ohne nicht verworfene Position**. Der teilweise
gekaufte Artikel steht sofort wieder in NACHKAUFEN und bekommt seine Restposition mit der
nächsten Liste, sobald die aktuelle abgeschlossen ist. Das hält §6 („Abgehakte Positionen bleiben
unverändert stehen“) ein und kommt ohne Schemaänderung aus.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.pluralization import format_quantity
from app.domain.quantities import reorder_quantity

# Trennzeichen im Textformat des Exports (§6): Geviertstrich mit Leerzeichen, „Klopapier — 10
# Rollen“. Steht hier als Konstante, weil das Format zeichengenau getestet wird (§9).
EXPORT_SEPARATOR = " — "


@dataclass(frozen=True)
class ReconciliationItem:
    """Ein aktiver Artikel, wie ihn der Abgleich sieht. Archivierte kommen gar nicht erst her.

    `store_name`/`store_position`/`category_name`/`category_position` tragen den Stand von
    Laden und Kategorie zum Zeitpunkt des Abgleichs — beim Anfügen werden sie in die neue
    Position eingefroren (M7, Frage 1 der Fragerunde: Snapshot statt Live-Join, konsistent mit
    `name`/`unit` oben). `None` heißt „nicht zugeordnet“, landet in der Gruppe „Sonstiges“
    (siehe `app/domain/grouping.py`).
    """

    item_id: int
    name: str
    unit: str
    stock: int
    reorder_level: int
    target_stock: int
    pack_size: int
    store_name: str | None = None
    store_position: int | None = None
    category_name: str | None = None
    category_position: int | None = None

    @property
    def below_threshold(self) -> bool:
        """§4: Bedarf besteht ab `stock <= reorder_level`, die Schwelle selbst zählt mit."""
        return self.stock <= self.reorder_level


@dataclass(frozen=True)
class ReconciliationLine:
    """Eine bestehende Position der offenen Liste."""

    line_id: int
    item_id: int
    suggested_qty: int
    is_checked: bool
    is_dropped: bool


@dataclass(frozen=True)
class LineToAppend:
    item_id: int
    suggested_qty: int
    name_snapshot: str
    unit_snapshot: str
    position: int
    store_snapshot: str | None = None
    store_position_snapshot: int | None = None
    category_snapshot: str | None = None
    category_position_snapshot: int | None = None


@dataclass(frozen=True)
class QuantityUpdate:
    line_id: int
    suggested_qty: int


@dataclass(frozen=True)
class ReconciliationPlan:
    to_append: tuple[LineToAppend, ...] = ()
    to_drop: tuple[int, ...] = ()
    to_requantify: tuple[QuantityUpdate, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.to_append or self.to_drop or self.to_requantify)


def plan_reconciliation(
    *,
    items: Sequence[ReconciliationItem],
    lines: Sequence[ReconciliationLine],
    next_position: int,
) -> ReconciliationPlan:
    """Leitet den Abgleich ab, ohne ihn auszuführen.

    `items` sind die aktiven Artikel in der Reihenfolge, in der neue Positionen angefügt werden
    sollen; `lines` sind **alle** Positionen der offenen Liste, auch die bereits verworfenen.
    `next_position` ist die nächste freie `position` innerhalb der Liste.

    Die vier Fälle aus §6, plus ein fünfter, den §6 nicht nennt:

    1. Artikel unter der Schwelle ohne nicht verworfene Position → anfügen.
    2. Nicht abgehakte Position, deren Artikel nicht mehr unter der Schwelle liegt → verwerfen.
    3. Abgehakte Positionen bleiben unverändert — weder verworfen noch neu berechnet.
    4. `suggested_qty` offener Positionen wird neu berechnet.
    5. Nicht abgehakte Position, deren Artikel inzwischen archiviert wurde (also nicht mehr in
       `items` steht) → verwerfen. §4 Regel 4 verlangt, dass archivierte Artikel nirgends
       erscheinen; ohne diesen Fall bliebe eine Karteileiche in der Liste stehen.
    """
    items_by_id = {item.item_id: item for item in items}
    active_line_item_ids = {line.item_id for line in lines if not line.is_dropped}

    to_drop: list[int] = []
    to_requantify: list[QuantityUpdate] = []

    for line in lines:
        if line.is_dropped or line.is_checked:
            continue  # Fall 3: abgehakte Positionen bleiben unangetastet.

        item = items_by_id.get(line.item_id)
        if item is None or not item.below_threshold:
            to_drop.append(line.line_id)  # Fälle 2 und 5.
            continue

        quantity = reorder_quantity(
            stock=item.stock, target_stock=item.target_stock, pack_size=item.pack_size
        )
        if quantity != line.suggested_qty:
            to_requantify.append(QuantityUpdate(line_id=line.line_id, suggested_qty=quantity))

    to_append: list[LineToAppend] = []
    position = next_position
    for item in items:
        if not item.below_threshold or item.item_id in active_line_item_ids:
            continue
        to_append.append(
            LineToAppend(
                item_id=item.item_id,
                suggested_qty=reorder_quantity(
                    stock=item.stock, target_stock=item.target_stock, pack_size=item.pack_size
                ),
                name_snapshot=item.name,
                unit_snapshot=item.unit,
                position=position,
                store_snapshot=item.store_name,
                store_position_snapshot=item.store_position,
                category_snapshot=item.category_name,
                category_position_snapshot=item.category_position,
            )
        )
        position += 1

    return ReconciliationPlan(
        to_append=tuple(to_append),
        to_drop=tuple(to_drop),
        to_requantify=tuple(to_requantify),
    )


def format_export_line(*, name: str, quantity: int, unit: str) -> str:
    """Eine Zeile des Textformats aus §6: `Klopapier — 10 Rollen`.

    Benutzt wird der Name aus dem Schnappschuss der Position, nicht der Live-Artikelname — dafür
    sind `name_snapshot`/`unit_snapshot` da (§3): Wird ein Artikel umbenannt, während die Liste
    im Supermarkt offen ist, soll die Liste nicht plötzlich anders heißen.
    """
    return f"{name}{EXPORT_SEPARATOR}{format_quantity(quantity=quantity, unit=unit)}"


def format_export_group_header(label: str) -> str:
    """Eine Gruppenüberschrift im Textformat (§6, ab M7: „mit Gruppenüberschrift“).

    Entschieden in der M7-Fragerunde (Frage 2): Der Kurzbefehl teilt den Text stur an
    Zeilenumbrüchen und hängt jede Zeile als Checklistenpunkt an — eine Überschriftszeile wird
    dadurch selbst zu einem abhakbaren Punkt (z. B. „REWE“). Bewusst in Kauf genommen, weil die
    sichtbare Struktur im Laden hier schwerer wiegt als der eine überflüssige Haken je Gruppe;
    siehe `docs/KURZBEFEHL.md` Abschnitt 4. Reine Textzeile, keine Dekoration — jedes Sonderzeichen
    würde in Apple Notes nur als Teil des Checklistenpunkts erscheinen, nicht als Formatierung.
    """
    return label


def format_export_text(lines: Sequence[str]) -> str:
    """Fügt die Zeilen zum Textkörper des Exports zusammen.

    Bewusst **ohne** abschließenden Zeilenumbruch: Der Kurzbefehl teilt den Text an
    Zeilenumbrüchen, ein Umbruch am Ende ergäbe einen leeren Punkt in der Notiz. Eine leere Liste
    liefert entsprechend einen leeren Text — ein gültiges Ergebnis, kein Fehler (§6).
    """
    return "\n".join(lines)
