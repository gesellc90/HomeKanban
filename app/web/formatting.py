"""Anzeige-Helfer für Zeitstempel (docs/PLAN.md L9).

Gespeichert wird immer UTC, angezeigt wird `Europe/Berlin` — ein einziger Helfer für die ganze
App, damit keine Umrechnung in Templates landet. Gehört bewusst nicht zu `app/domain/`: das ist
Anzeigeformatierung, keine Fachregel.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.status import ItemStatus

_DISPLAY_TZ = ZoneInfo("Europe/Berlin")


def format_local(iso_utc: str) -> str:
    """Formatiert einen UTC-ISO-8601-Zeitstempel (`...Z`, siehe `utc_now_iso`) für die Anzeige."""
    utc_dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    local_dt = utc_dt.astimezone(_DISPLAY_TZ)
    return local_dt.strftime("%d.%m.%Y %H:%M")


_MOVEMENT_KIND_LABELS = {
    "opening": "Anfangsbestand",
    "withdrawal": "Entnahme",
    "restock": "Zugang",
    "adjustment": "Inventur",
}


def movement_kind_label(kind: str) -> str:
    """Deutsches Label für `movements.kind`, siehe docs/PLAN.md §3."""
    return _MOVEMENT_KIND_LABELS.get(kind, kind)


_STATUS_LABELS = {
    ItemStatus.OK: "Ausreichend",
    ItemStatus.REORDER: "Nachkaufen",
    ItemStatus.ON_LIST: "Auf Liste",
}


def status_label(status: ItemStatus) -> str:
    """Deutsches Label für `ItemStatus`, siehe docs/PLAN.md §4."""
    return _STATUS_LABELS[status]
