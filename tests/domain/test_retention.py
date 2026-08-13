from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.retention import (
    RetentionPolicy,
    RetentionPolicyError,
    parse_backup_keep,
    select_backups_to_keep,
)


class TestParseBackupKeep:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("7d,4w", RetentionPolicy(daily=7, weekly=4)),
            ("4w,7d", RetentionPolicy(daily=7, weekly=4)),  # Reihenfolge egal
            ("0d,0w", RetentionPolicy(daily=0, weekly=0)),
            (" 7d , 4w ", RetentionPolicy(daily=7, weekly=4)),  # Leerraum wird toleriert
            ("14d,8w", RetentionPolicy(daily=14, weekly=8)),
        ],
    )
    def test_valid_values(self, value: str, expected: RetentionPolicy) -> None:
        assert parse_backup_keep(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "7d",  # w fehlt
            "4w",  # d fehlt
            "7d,4w,1d",  # d doppelt
            "7d,4w,4w",  # w doppelt
            "7x,4w",  # unbekannte Einheit
            "sieben,4w",  # keine Zahl
            "-1d,4w",  # negative Zahl
            "7d,4w,",  # leerer dritter Abschnitt
            "7d,,4w",  # leerer mittlerer Abschnitt
            "7 d,4w",  # Leerraum innerhalb eines Abschnitts
        ],
    )
    def test_invalid_values_raise_understandable_error(self, value: str) -> None:
        with pytest.raises(RetentionPolicyError):
            parse_backup_keep(value)


def _days_ago(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


class TestSelectBackupsToKeep:
    def test_empty_input_keeps_nothing(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        assert select_backups_to_keep([], policy=RetentionPolicy(7, 4), now=now) == set()

    def test_fewer_backups_than_policy_keeps_everything(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        timestamps = [_days_ago(now, d) for d in (0, 1, 2)]

        kept = select_backups_to_keep(timestamps, policy=RetentionPolicy(7, 4), now=now)

        assert kept == set(timestamps)

    def test_forty_daily_runs_keep_eleven_spanning_seven_daily_and_four_weekly(self) -> None:
        """Das durchgerechnete Beispiel aus der Fragerunde M9, Frage 1: täglicher Lauf über
        40 Tage behält die 7 jüngsten Tage plus je ein Backup aus den 4 Kalenderwochen davor."""
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        timestamps = [_days_ago(now, d) for d in range(40)]

        kept = select_backups_to_keep(timestamps, policy=RetentionPolicy(7, 4), now=now)

        assert len(kept) == 11
        daily_expected = {_days_ago(now, d) for d in range(7)}
        weekly_expected = {_days_ago(now, d) for d in (7, 14, 21, 28)}
        assert kept == daily_expected | weekly_expected

    def test_gap_in_daily_runs_still_finds_a_weekly_representative(self) -> None:
        """Fällt der Cron mehrere Tage aus, bleibt trotzdem das jeweils jüngste Backup jeder noch
        vertretenen Woche erhalten — anders als bei einer festen Wochentagsmarkierung reißt eine
        Lücke hier keine ganze Woche aus der Aufbewahrung."""
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        # Nur ein Backup 10 Tage zuvor statt eines täglichen Laufs — liegt außerhalb des
        # 7-Tage-Topfs und muss über die Wochenzugehörigkeit gefunden werden.
        timestamps = [now, _days_ago(now, 10)]

        kept = select_backups_to_keep(timestamps, policy=RetentionPolicy(7, 4), now=now)

        assert kept == set(timestamps)

    def test_two_backups_same_iso_week_keep_only_the_newer_one(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        older_same_week = _days_ago(now, 8)  # 2026-03-07, Woche (2026, 10)
        newer_same_week = _days_ago(now, 7)  # 2026-03-08, Woche (2026, 10)
        assert older_same_week.isocalendar()[:2] == newer_same_week.isocalendar()[:2]

        timestamps = [now, older_same_week, newer_same_week]
        # policy.daily=1 zwingt beide Wochenkandidaten in den "Rest".
        kept = select_backups_to_keep(
            timestamps, policy=RetentionPolicy(daily=1, weekly=4), now=now
        )

        assert kept == {now, newer_same_week}
        assert older_same_week not in kept

    def test_daily_and_weekly_pools_do_not_overlap(self) -> None:
        """Ein Backup, das schon im 7-Tage-Topf liegt, wird nicht zusätzlich als Wochenvertreter
        gezählt — sonst könnten am Ende weniger als die konfigurierten `weekly` Wochen übrig
        bleiben, obwohl genug Historie da wäre."""
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        timestamps = [_days_ago(now, d) for d in range(7)]  # alle in den letzten 7 Tagen

        kept = select_backups_to_keep(
            timestamps, policy=RetentionPolicy(daily=7, weekly=4), now=now
        )

        assert kept == set(timestamps)  # kein Wochenkandidat übrig, aber auch keine Dopplung

    def test_more_than_four_distinct_weeks_keeps_only_the_four_most_recent(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        # Ein Backup je Woche über 8 Wochen, alle außerhalb des Daily-Topfs.
        timestamps = [_days_ago(now, 10 + 7 * i) for i in range(8)]

        kept = select_backups_to_keep(
            timestamps, policy=RetentionPolicy(daily=0, weekly=4), now=now
        )

        assert kept == set(timestamps[:4])  # die vier jüngsten Wochenvertreter

    def test_year_boundary_with_iso_week_53_orders_correctly(self) -> None:
        """2026 hat eine ISO-Woche 53, die bis in den Januar 2027 reicht (Woche (2026, 53)).
        Ein Backup vom 4. Januar 2027 liegt bereits in Woche (2027, 1) — die numerisch kleinere
        Jahreszahl 2026 der Vorwoche darf die Sortierung nicht verfälschen."""
        now = datetime(2027, 1, 10, 12, 0, tzinfo=UTC)
        in_new_year_week_1 = datetime(2027, 1, 4, 12, 0, tzinfo=UTC)
        assert in_new_year_week_1.isocalendar()[:2] == (2027, 1)
        in_old_year_week_53 = datetime(2026, 12, 28, 12, 0, tzinfo=UTC)
        assert in_old_year_week_53.isocalendar()[:2] == (2026, 53)
        even_older = datetime(2026, 12, 20, 12, 0, tzinfo=UTC)

        timestamps = [now, in_new_year_week_1, in_old_year_week_53, even_older]

        kept = select_backups_to_keep(
            timestamps, policy=RetentionPolicy(daily=1, weekly=3), now=now
        )

        assert kept == {now, in_new_year_week_1, in_old_year_week_53, even_older}

    def test_future_timestamp_is_ignored(self) -> None:
        """Eine falsch gestellte Uhr darf kein Backup dauerhaft unlöschbar machen (siehe
        app/domain/retention.py, Moduldoc)."""
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        future = now + timedelta(days=1)

        kept = select_backups_to_keep([future, now], policy=RetentionPolicy(7, 4), now=now)

        assert kept == {now}

    def test_duplicate_timestamps_are_deduplicated(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)

        kept = select_backups_to_keep([now, now, now], policy=RetentionPolicy(7, 4), now=now)

        assert kept == {now}
