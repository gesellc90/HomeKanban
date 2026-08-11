from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.undo import is_within_undo_window

_CREATED_AT = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("elapsed", "window_minutes", "expected"),
    [
        (timedelta(0), 10, True),  # sofortiges Undo
        (timedelta(minutes=5), 10, True),  # deutlich innerhalb
        (timedelta(minutes=9, seconds=59), 10, True),  # knapp innerhalb
        (timedelta(minutes=10), 10, True),  # genau auf der Fenstergrenze — zählt noch
        (timedelta(minutes=10, seconds=1), 10, False),  # knapp abgelaufen
        (timedelta(minutes=11), 10, False),  # deutlich abgelaufen
        (timedelta(0), 0, True),  # Fenster von 0 Minuten: die Grenze selbst zählt noch
        (timedelta(seconds=1), 0, False),  # ... aber schon eine Sekunde später nicht mehr
    ],
)
def test_is_within_undo_window(elapsed: timedelta, window_minutes: int, expected: bool) -> None:
    now = _CREATED_AT + elapsed

    assert (
        is_within_undo_window(created_at=_CREATED_AT, now=now, window_minutes=window_minutes)
        is expected
    )
