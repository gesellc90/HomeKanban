"""Aufbewahrungsregel für Backups, siehe docs/PLAN.md §9 (M9, Fragerunde Frage 1).

Reine Logik: kein Dateisystem, kein SQL. Nimmt eine Liste von Backup-Zeitpunkten und „jetzt“
entgegen, liefert zurück, welche Zeitpunkte behalten werden — der Aufrufer (`app/services/
backup.py`) übersetzt das in tatsächliche Dateien und löscht den Rest.

**Entschieden (Fragerunde M9, Frage 1):** „Zwei Töpfe nach Alter“ — die `daily` jüngsten Backups
plus, aus dem verbleibenden Rest, je das jüngste Backup einer ISO-Kalenderwoche für die letzten
`weekly` Wochen, in denen überhaupt ein Backup übrig war. Anders als eine feste Wochentags-
markierung (z. B. „immer Sonntag“) hängt das Ergebnis nicht davon ab, an welchem Wochentag der
Cron lief oder ausfiel — eine Lücke verschiebt nur, *welches* Backup einer Woche das jeweils
jüngste ist, nicht *ob* die Woche vertreten ist. Durchgerechnetes Beispiel aus der Fragerunde:
täglicher Lauf über 40 Tage behält die 7 jüngsten Tage plus je ein Backup aus den vier
Kalenderwochen davor — 11 Dateien, die zusammen gut fünf Wochen abdecken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

#: `HOMEKANBAN_BACKUP_KEEP` ist genau zwei kommagetrennte Segmente: eine Zahl gefolgt von `d`
#: (täglich) oder `w` (wöchentlich), in beliebiger Reihenfolge — z. B. `"7d,4w"`.
_SEGMENT_PATTERN = re.compile(r"^(\d+)([dw])$")


class RetentionPolicyError(ValueError):
    """`HOMEKANBAN_BACKUP_KEEP` lässt sich nicht sinnvoll interpretieren.

    Verständliche deutsche Meldung statt eines Absturzes beim nächtlichen Cron-Lauf
    (docs/PLAN.md §9, Aufgabe 1/5)."""


@dataclass(frozen=True)
class RetentionPolicy:
    daily: int
    weekly: int


def parse_backup_keep(value: str) -> RetentionPolicy:
    """Parst `HOMEKANBAN_BACKUP_KEEP` (Format `"7d,4w"`, Reihenfolge egal).

    Erwartet genau ein `d`-Segment und genau ein `w`-Segment; alles andere — leerer Wert,
    unbekannte Einheit, doppeltes Segment, negative oder nicht-ganzzahlige Zahl, fehlendes
    Segment — wird als `RetentionPolicyError` mit einer erklärenden deutschen Meldung gemeldet.
    """
    segments = [segment.strip() for segment in value.split(",")]
    if not value.strip() or any(not segment for segment in segments):
        raise RetentionPolicyError(
            f"Ungültiger Wert für HOMEKANBAN_BACKUP_KEEP: „{value}“ – erwartet z. B. „7d,4w“."
        )

    counts: dict[str, int] = {}
    for segment in segments:
        match = _SEGMENT_PATTERN.match(segment)
        if match is None:
            raise RetentionPolicyError(
                f"Ungültiger Wert für HOMEKANBAN_BACKUP_KEEP: „{value}“ – Abschnitt „{segment}“ "
                "erwartet eine Zahl gefolgt von „d“ (täglich) oder „w“ (wöchentlich), z. B. „7d“."
            )
        count_text, unit = match.groups()
        if unit in counts:
            raise RetentionPolicyError(
                f"Ungültiger Wert für HOMEKANBAN_BACKUP_KEEP: „{value}“ – „{unit}“ kommt mehrfach "
                "vor."
            )
        counts[unit] = int(count_text)

    missing = {"d", "w"} - counts.keys()
    if missing:
        missing_labels = ", ".join(sorted(f"„{unit}“" for unit in missing))
        raise RetentionPolicyError(
            f"Ungültiger Wert für HOMEKANBAN_BACKUP_KEEP: „{value}“ – es fehlt ein Abschnitt für "
            f"{missing_labels}, erwartet z. B. „7d,4w“."
        )

    return RetentionPolicy(daily=counts["d"], weekly=counts["w"])


def select_backups_to_keep(
    timestamps: list[datetime], *, policy: RetentionPolicy, now: datetime
) -> set[datetime]:
    """Welche der übergebenen Zeitpunkte die Aufbewahrungsregel behält.

    Zeitpunkte in der Zukunft (Uhr auf dem Pi falsch gestellt) fließen nicht ein — sie würden
    sonst nie in die 7-täglich-Zählung hineinrutschen und liefen Gefahr, dauerhaft als „jüngstes“
    Backup einer Woche zu gelten, obwohl ihr Zeitpunkt nicht vertrauenswürdig ist.
    """
    candidates = sorted({timestamp for timestamp in timestamps if timestamp <= now}, reverse=True)
    if not candidates:
        return set()

    daily_keep = set(candidates[: policy.daily])
    remaining = [timestamp for timestamp in candidates if timestamp not in daily_keep]

    # `remaining` ist absteigend sortiert: der erste Treffer je Woche ist automatisch der jüngste.
    weeks_seen: dict[tuple[int, int], datetime] = {}
    for timestamp in remaining:
        week_key = timestamp.isocalendar()[:2]
        weeks_seen.setdefault(week_key, timestamp)

    newest_weeks = sorted(weeks_seen.keys(), reverse=True)[: policy.weekly]
    weekly_keep = {weeks_seen[week_key] for week_key in newest_weeks}

    return daily_keep | weekly_keep
