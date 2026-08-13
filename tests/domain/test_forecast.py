from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.forecast import (
    ConsumptionRate,
    WithdrawalObservation,
    consumption_rate,
    estimate_reach,
    suggested_reorder_level,
)

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _events(*offsets_and_quantities: tuple[int, int]) -> list[WithdrawalObservation]:
    """`(Tage seit _BASE, Menge)` je Entnahme, Reihenfolge in den Aufrufen egal."""
    return [
        WithdrawalObservation(occurred_at=_BASE + timedelta(days=days), quantity=quantity)
        for days, quantity in offsets_and_quantities
    ]


class TestConsumptionRateDataLock:
    def test_two_withdrawals_are_not_enough_data(self) -> None:
        # Definition of Done (§9): ein Artikel mit zwei Entnahmen zeigt „zu wenig Daten“.
        events = _events((0, 1), (20, 1))

        rate = consumption_rate(events)

        assert rate.has_enough_data is False
        assert rate.withdrawal_count == 2
        assert rate.per_day is None

    def test_exactly_three_withdrawals_is_enough_count(self) -> None:
        events = _events((0, 1), (10, 1), (20, 1))

        rate = consumption_rate(events)

        assert rate.withdrawal_count == 3
        # 20 Tage Spanne >= 14 Tage Sperre — hier greift nur die Mengensperre nicht mehr.
        assert rate.has_enough_data is True

    @pytest.mark.parametrize(
        ("span_days", "expected_has_enough_data"),
        [
            (13, False),  # knapp unter der Sperre
            (14, True),  # Fenstergrenze selbst zählt noch als ausreichend
        ],
    )
    def test_history_length_boundary_at_fourteen_days(
        self, span_days: int, expected_has_enough_data: bool
    ) -> None:
        events = _events((0, 1), (span_days // 2, 1), (span_days, 1))

        rate = consumption_rate(events)

        assert rate.has_enough_data is expected_has_enough_data

    def test_single_withdrawal_is_not_enough_data(self) -> None:
        events = _events((0, 1))

        rate = consumption_rate(events)

        assert rate.has_enough_data is False
        assert rate.withdrawal_count == 1
        assert rate.observed_days is None


class TestConsumptionRateFormula:
    def test_rate_uses_span_between_oldest_and_newest_withdrawal(self) -> None:
        # Fragerunde M8, Frage 1: Zähler = Summe − Menge der ältesten Entnahme, Nenner = Spanne
        # zwischen ältester und jüngster Entnahme. Vier Entnahmen zu je 1 Stück über 45 Tage:
        # (4 - 1) / 45 = 3/45.
        events = _events((0, 1), (15, 1), (30, 1), (45, 1))

        rate = consumption_rate(events)

        assert rate.has_enough_data is True
        assert rate.observed_days == pytest.approx(45.0)
        assert rate.per_day == pytest.approx(3 / 45)

    def test_rate_ignores_gaps_in_history_between_first_and_last_withdrawal(self) -> None:
        # Eine lange Lücke in der Mitte ändert an Zähler/Nenner nichts — nur die älteste und die
        # jüngste Entnahme im Fenster zählen für die Spanne (§9 Testfokus: Lücken).
        events = _events((0, 2), (5, 1), (70, 1))

        rate = consumption_rate(events)

        assert rate.observed_days == pytest.approx(70.0)
        assert rate.per_day == pytest.approx((2 + 1 + 1 - 2) / 70)

    def test_oldest_withdrawal_quantity_is_subtracted_not_just_one_unit(self) -> None:
        # Verallgemeinerung aus der Fragerunde: abgezogen wird die Menge der ältesten Entnahme,
        # nicht immer pauschal 1 Stück.
        events = _events((0, 4), (14, 1), (28, 1))

        rate = consumption_rate(events)

        assert rate.per_day == pytest.approx((4 + 1 + 1 - 4) / 28)

    def test_order_of_events_does_not_matter(self) -> None:
        forward = consumption_rate(_events((0, 1), (14, 1), (28, 1)))
        backward = consumption_rate(_events((28, 1), (0, 1), (14, 1)))

        assert forward == backward


class TestEstimateReach:
    def test_not_enough_data_propagates(self) -> None:
        rate = ConsumptionRate(has_enough_data=False, withdrawal_count=1)

        reach = estimate_reach(stock=5, rate=rate)

        assert reach.has_enough_data is False
        assert reach.days is None
        assert reach.is_unlimited is False

    def test_zero_rate_means_unlimited_reach_not_a_crash_or_zero_days(self) -> None:
        # §9 Testfokus: Division durch Null. Rate 0 heißt unendliche Reichweite.
        rate = ConsumptionRate(
            has_enough_data=True, withdrawal_count=3, observed_days=20.0, per_day=0.0
        )

        reach = estimate_reach(stock=5, rate=rate)

        assert reach.has_enough_data is True
        assert reach.is_unlimited is True
        assert reach.days is None

    def test_negative_rate_is_treated_defensively_as_unlimited(self) -> None:
        # Kann aus echten Daten nicht entstehen (Mengen sind immer positiv), aber die Funktion
        # bekommt eine ConsumptionRate von außen und darf bei einem unerwarteten Wert nicht
        # abstürzen oder eine falsche Zahl ausgeben.
        rate = ConsumptionRate(
            has_enough_data=True, withdrawal_count=3, observed_days=20.0, per_day=-0.1
        )

        reach = estimate_reach(stock=5, rate=rate)

        assert reach.is_unlimited is True

    def test_plausible_reach_from_a_realistic_rate(self) -> None:
        # Definition of Done (§9): ein Artikel mit Historie zeigt eine plausible Reichweite.
        rate = ConsumptionRate(
            has_enough_data=True, withdrawal_count=4, observed_days=45.0, per_day=3 / 45
        )

        reach = estimate_reach(stock=2, rate=rate)

        assert reach.has_enough_data is True
        assert reach.is_unlimited is False
        assert reach.days == pytest.approx(2 / (3 / 45))

    def test_zero_stock_with_positive_rate_is_zero_days_not_an_error(self) -> None:
        rate = ConsumptionRate(
            has_enough_data=True, withdrawal_count=3, observed_days=20.0, per_day=0.5
        )

        reach = estimate_reach(stock=0, rate=rate)

        assert reach.days == 0


class TestSuggestedReorderLevel:
    def test_none_when_not_enough_data(self) -> None:
        rate = ConsumptionRate(has_enough_data=False, withdrawal_count=1)

        assert suggested_reorder_level(rate=rate, lead_days=7, pack_size=1) is None

    @pytest.mark.parametrize(
        ("per_day", "lead_days", "pack_size", "expected", "reason"),
        [
            (0.2, 7, 1, 2, "ceil(0.2*7)=2, Kaufeinheit 1 rundet nicht weiter"),
            (0.2, 7, 4, 4, "roher Wert 2, auf die Kaufeinheit 4 aufgerundet"),
            (1.0, 10, 1, 10, "glatter Fall ohne Rundungseffekt"),
            (0.01, 7, 6, 6, "roher Wert 1, Minimum ist die Kaufeinheit selbst"),
        ],
    )
    def test_rounds_up_to_pack_size_via_existing_rounding(
        self, per_day: float, lead_days: int, pack_size: int, expected: int, reason: str
    ) -> None:
        rate = ConsumptionRate(
            has_enough_data=True, withdrawal_count=3, observed_days=20.0, per_day=per_day
        )

        result = suggested_reorder_level(rate=rate, lead_days=lead_days, pack_size=pack_size)

        assert result == expected, reason
