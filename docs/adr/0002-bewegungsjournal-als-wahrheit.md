# 0002 — Bewegungsjournal als Wahrheit, `items.stock` als Cache

- **Status:** entschieden
- **Datum:** 2026-08-11
- **Meilenstein:** M0

## Kontext

Jede Bestandsänderung (Entnahme, Zugang, Korrektur, Inventur) muss nachvollziehbar sein — sowohl für
die Alltagsnutzung (Board zeigt den aktuellen Stand) als auch für die spätere Verbrauchsprognose
(M8), die auf der vollständigen Historie aufbaut. Zu entscheiden ist, ob der Bestand bei jedem Lesen
aus dem Journal aggregiert wird oder als eigene Spalte mitgeführt wird.

## Entscheidung

Das append-only Bewegungsjournal (`movements`) ist die Wahrheit. `items.stock` ist ein mitgeführter
Cache, der in derselben Transaktion wie die Bewegung geschrieben wird; jede Bewegung speichert
zusätzlich `stock_after`. Die Invariante `SUM(movements.delta) == items.stock` gilt ausnahmslos, wird
getestet (Testpflicht laut `CLAUDE.md` §5) und ab M1 von `/healthz` geprüft.

## Alternativen

- **Bestand bei jedem Lesen aus dem Journal aggregieren:** Vermeidet Cache-Inkonsistenzen per
  Konstruktion, erzeugt aber unnötige Last auf dem Pi bei jedem Board-Rendern, und eine Inventur
  braucht ohnehin einen Bezugspunkt, gegen den sie die Differenz bucht — ein reiner Aggregations-Weg
  löst das nicht von selbst.

## Konsequenzen

Das Board rendert ohne Aggregation über potenziell große Journale, die Historie bleibt vollständig
erklärbar (jede Zahl lässt sich auf eine Bewegung zurückführen), und Undo (ADR-würdig als L3, aber
nicht eigens formalisiert) bleibt ein normaler Buchungsvorgang: eine ausgleichende Gegenbewegung statt
einer Löschung. Der Preis ist Sorgfaltspflicht in jeder Schreiboperation — Journal und Cache müssen
atomar in derselben Transaktion geschrieben werden, sonst bricht die Invariante.
