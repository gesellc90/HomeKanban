"""Sortierung und Gruppierung für Einkaufsliste und Export, siehe docs/PLAN.md §7, §9 (M7).

Reine Logik: kein SQL, kein HTML (§2). Ordnet Einträge — bei M7 sind das die offenen Positionen
der Einkaufsliste mit ihren beim Anfügen eingefrorenen `store_snapshot`/`category_snapshot`-Werten
(Fragerunde M7, Frage 1: Snapshot statt Live-Join auf `items`, konsistent mit der Namenskopie aus
§3) — zuerst nach Laden-Position, innerhalb nach Kategorie-Position, innerhalb nach der Position
des Eintrags selbst (`sort_position`, bei Listenpositionen `shopping_list_lines.position`).

Einträge ohne Laden landen gemeinsam in der Gruppe „Sonstiges“ am Ende, statt unsichtbar aus der
Liste zu verschwinden (Definition of Done, §9 M7). Wirft nie — Randfälle wie „kein Laden angelegt“,
„alle Artikel ohne Zuordnung“ oder „zwei Läden mit gleicher Position“ liefern ein wohlgeformtes,
nachvollziehbares Ergebnis statt einer Ausnahme (CLAUDE.md §8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby
from typing import Protocol

MISC_LABEL = "Sonstiges"


class Groupable(Protocol):
    """Was die Gruppierung von einem Eintrag braucht — unabhängig davon, ob er aus einem
    Schnappschuss der Einkaufsliste stammt oder aus einer anderen Quelle mit Laden-/
    Kategoriezuordnung."""

    store_name: str | None
    store_position: int | None
    category_name: str | None
    category_position: int | None
    sort_position: int


@dataclass(frozen=True)
class Group[T: Groupable]:
    label: str
    entries: tuple[T, ...]


def _sort_key(entry: Groupable) -> tuple[int, int, str, int, int, str, int]:
    store_missing = entry.store_name is None
    category_missing = entry.category_name is None
    return (
        1 if store_missing else 0,
        entry.store_position if entry.store_position is not None else 0,
        entry.store_name or "",
        1 if category_missing else 0,
        entry.category_position if entry.category_position is not None else 0,
        entry.category_name or "",
        entry.sort_position,
    )


def group_and_sort[T: Groupable](entries: Sequence[T]) -> tuple[Group[T], ...]:
    """Gruppiert nach Laden, sortiert innerhalb einer Gruppe nach Kategorie-Position und zuletzt
    nach `sort_position` als Tie-Breaker.

    Zwei Einträge mit identischer Laden- und Kategorieposition landen dank des Tie-Breakers in
    einer festen, nachvollziehbaren Reihenfolge — nicht in der, die die Eingabe zufällig mitbringt.
    Zwei Läden mit derselben Position werden zusätzlich nach Namen sortiert, aus demselben Grund.
    """
    ordered = sorted(entries, key=_sort_key)

    groups: list[Group[T]] = []
    for store_name, members in groupby(ordered, key=lambda entry: entry.store_name):
        member_list = tuple(members)
        groups.append(Group(label=store_name or MISC_LABEL, entries=member_list))
    return tuple(groups)
