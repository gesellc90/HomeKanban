"""Zeitfenster fürs Rückgängigmachen, siehe docs/PLAN.md §5. Reine Logik: kein SQL, kein I/O."""

from __future__ import annotations

from datetime import datetime, timedelta


def is_within_undo_window(*, created_at: datetime, now: datetime, window_minutes: int) -> bool:
    """Ob eine Bewegung von `created_at` bei `now` noch rückgängig gemacht werden darf.

    Die Fenstergrenze selbst zählt noch als "innerhalb" (inklusive) — ein Rückgängig, das exakt
    im Moment des Ablaufs eintrifft, soll nicht von einer Millisekunden-Rundung abhängen.
    """
    return now - created_at <= timedelta(minutes=window_minutes)
