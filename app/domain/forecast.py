"""Verbrauchsrate, Reichweite und Schwellenvorschlag, siehe docs/PLAN.md §9 (M8).

Reine Logik: kein SQL, kein I/O, kein HTTP. Nimmt bereits gefilterte Entnahmen entgegen — der
Ausschluss von Gegenbuchungen und ihren Ursprüngen ist Sache der Abfrage
(`app/repo/movements.py::list_unreverted_withdrawals_for_item_since` /
`list_unreverted_withdrawals_since`), nicht dieser Datei. Ebenso liegt der 90-Tage-Zuschnitt beim
Aufrufer (die Abfrage bekommt `since`); diese Funktionen vertrauen dem übergebenen Zeitraum.

**Rate-Nenner (Fragerunde M8, Frage 1):** Spanne zwischen der ältesten und der jüngsten Entnahme
im betrachteten Fenster — nicht die volle Fensterlänge und nicht der Beobachtungszeitraum ab
Artikelanlage. Der Zähler zieht die Menge der ältesten Entnahme von der Gesamtmenge ab: Die
älteste Entnahme markiert den Start der Beobachtung und wird nicht durch die seither vergangene
Zeit erklärt — nur was danach folgte, zählt als „Verbrauch innerhalb der Spanne“ (entspricht
N-1 Intervallen bei N Zeitpunkten). Damit ist der Zähler bei mindestens zwei Entnahmen nach der
ältesten stets positiv; ein rechnerisch negativer oder Null-Zähler kann aus echten Daten nicht
entstehen (jede Entnahmemenge ist positiv), `estimate_reach` bleibt trotzdem defensiv gegen
`rate_per_day <= 0`, weil das Testfeld genau diesen Randfall verlangt (§9, Division durch Null).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.domain.quantities import reorder_quantity

#: Unter drei Entnahmen oder unter dieser Historienlänge gibt es keine Zahl, sondern „zu wenig
#: Daten“ (§9). Beide Sperren teilen sich dieselbe Definition von „Historie“ wie der Rate-Nenner:
#: die Spanne zwischen ältester und jüngster Entnahme im Fenster.
MIN_WITHDRAWAL_COUNT = 3
MIN_HISTORY_DAYS = 14.0

#: Betrachtungsfenster für die Verbrauchsrate (§9). Der Zuschnitt selbst passiert beim Aufrufer
#: (Repository-Abfrage mit `since = now - RATE_WINDOW_DAYS`); hier nur zur Dokumentation und für
#: Aufrufer, die `since` daraus ableiten wollen.
RATE_WINDOW_DAYS = 90


@dataclass(frozen=True)
class WithdrawalObservation:
    """Eine einzelne, bereits um Gegenbuchungen bereinigte Entnahme."""

    occurred_at: datetime
    quantity: int


@dataclass(frozen=True)
class ConsumptionRate:
    """Ergebnis der Ratenberechnung — `has_enough_data` statt `None`, damit ein Aufrufer eine
    fehlende Zahl nicht versehentlich als 0 behandelt (§9)."""

    has_enough_data: bool
    withdrawal_count: int
    observed_days: float | None = None
    per_day: float | None = None


@dataclass(frozen=True)
class ReachEstimate:
    """Reichweite in Tagen. `is_unlimited=True` (Rate 0) ist ein eigener, gültiger Zustand —
    keine Zahl und kein Fehler (§9)."""

    has_enough_data: bool
    is_unlimited: bool = False
    days: float | None = None


def consumption_rate(events: list[WithdrawalObservation]) -> ConsumptionRate:
    """Verbrauchsrate aus den übergebenen Entnahmen (Reihenfolge egal, wird selbst sortiert).

    Sperre bei dünner Datenlage (§9): unter `MIN_WITHDRAWAL_COUNT` Entnahmen oder unter
    `MIN_HISTORY_DAYS` Tagen Spanne zwischen ältester und jüngster Entnahme gibt es keine Rate.
    Die Fenstergrenzen zählen jeweils noch als ausreichend (inklusive), wie beim Undo-Fenster
    in `app/domain/undo.py`.
    """
    count = len(events)
    if count < MIN_WITHDRAWAL_COUNT:
        return ConsumptionRate(has_enough_data=False, withdrawal_count=count)

    ordered = sorted(events, key=lambda event: event.occurred_at)
    oldest, newest = ordered[0], ordered[-1]
    observed_days = (newest.occurred_at - oldest.occurred_at).total_seconds() / 86400

    if observed_days < MIN_HISTORY_DAYS:
        return ConsumptionRate(
            has_enough_data=False, withdrawal_count=count, observed_days=observed_days
        )

    total_quantity = sum(event.quantity for event in ordered)
    countable_quantity = total_quantity - oldest.quantity
    rate = countable_quantity / observed_days

    return ConsumptionRate(
        has_enough_data=True,
        withdrawal_count=count,
        observed_days=observed_days,
        per_day=rate,
    )


def estimate_reach(*, stock: int, rate: ConsumptionRate) -> ReachEstimate:
    """Reichweite in Tagen aus Bestand und Rate. Rate 0 (oder, defensiv, negativ) bedeutet
    unendliche Reichweite — kein Absturz, keine „0 Tage“ (§9)."""
    if not rate.has_enough_data:
        return ReachEstimate(has_enough_data=False)

    assert rate.per_day is not None  # has_enough_data=True liefert immer eine Rate.
    if rate.per_day <= 0:
        return ReachEstimate(has_enough_data=True, is_unlimited=True)

    return ReachEstimate(has_enough_data=True, days=stock / rate.per_day)


def suggested_reorder_level(*, rate: ConsumptionRate, lead_days: int, pack_size: int) -> int | None:
    """Schwellenvorschlag `ceil(rate × lead_days)`, auf die Kaufeinheit gerundet — über die
    vorhandene Rundung aus `app/domain/quantities.py::reorder_quantity`, nicht neu geschrieben.
    `None`, wenn die Datenlage keine Rate hergibt (§9); der Aufrufer zeigt dann „zu wenig Daten“
    statt eines Vorschlags.
    """
    if not rate.has_enough_data:
        return None

    assert rate.per_day is not None
    raw_threshold = max(math.ceil(rate.per_day * lead_days), 0)
    return reorder_quantity(stock=0, target_stock=raw_threshold, pack_size=pack_size)
