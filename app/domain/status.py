"""Statusableitung, siehe docs/PLAN.md §4.

Der Status wird bei jedem Lesen berechnet und nirgends gespeichert. Reine Logik: kein SQL,
kein I/O. Regel 3 ("Auf Liste") braucht die Information, ob eine offene, nicht abgehakte
Position existiert — die kommt hier als Parameter herein, die Abfrage macht das Repository.
Archivierte Artikel (Regel 4) werden bereits vor dem Aufruf ausgefiltert, nicht hier.
"""

from __future__ import annotations

from enum import StrEnum


class ItemStatus(StrEnum):
    OK = "ok"
    REORDER = "reorder"
    ON_LIST = "on_list"


def derive_status(*, stock: int, reorder_level: int, has_open_list_line: bool) -> ItemStatus:
    """Regeln 1–3 aus §4, in dieser Reihenfolge angewendet.

    Eine offene, nicht abgehakte Position gewinnt unabhängig vom Bestand (Regel 3) — der
    Artikel ist bereits eingeplant und soll nicht doppelt auf die Liste kommen.
    """
    if has_open_list_line:
        return ItemStatus.ON_LIST
    if stock > reorder_level:
        return ItemStatus.OK
    return ItemStatus.REORDER
