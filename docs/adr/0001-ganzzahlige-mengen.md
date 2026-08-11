# 0001 — Ganzzahlige Mengen statt Dezimalwerte

- **Status:** entschieden
- **Datum:** 2026-08-11
- **Meilenstein:** M0

## Kontext

Jeder Artikel führt einen Bestand, einen Mindestbestand, einen Sollbestand und eine Kaufeinheit
(`pack_size`). Diese Werte müssen sich addieren, subtrahieren und auf die Kaufeinheit runden lassen,
und zwar in einem append-only Bewegungsjournal, dessen Summe exakt dem gecachten Bestand entsprechen
muss (siehe ADR 0002). Die Frage ist, ob diese Mengen als Dezimalwerte (`REAL`) oder als Ganzzahlen
(`INTEGER`) geführt werden.

## Entscheidung

Alle Mengen (Bestand, Mindestbestand, Sollbestand, Kaufeinheit, Bewegungsdelta) sind Ganzzahlen. Die
Einheit (`unit`) benennt das zählbare Ding — „Packung“, „Rolle“, „Flasche“, „500-g-Paket“ — statt
dass die Zahl selbst gebrochen wird.

## Alternativen

- **`REAL`-Spalten:** Erlaubt „1,5 Packungen“, führt aber zu Rundungsdrift in Journalsummen und zu
  einer Genauigkeit, die der Entnahmeprozess nicht liefert — niemand wiegt beim Griff in den Schrank
  ab, wie viel Mehl übrig ist.
- **Tausendstel-Integer** (Mengen intern × 1000): Vermeidet Fließkomma-Rundungsfehler, bringt aber in
  jeder Schicht (Domäne, Templates, Export-Text) zusätzliche Komplexität ohne Alltagsnutzen.

## Konsequenzen

Journalsummen sind exakt, `SUM(delta) == stock` ist trivial und ohne Toleranzband testbar
(siehe ADR 0002), und die Rundung der Nachkaufmenge auf die Kaufeinheit (`ceil` auf `INTEGER`)
bleibt eine einfache, vollständig tabellengetrieben testbare Funktion in `app/domain/`.

**Rückweg:** Da alle Werte bereits `INTEGER` sind, könnte eine einzige Migration die Spaltensemantik
nachträglich auf Tausendstel umdeuten (`× 1000`), ohne Datenverlust — falls sich doch einmal ein
Artikel mit echtem Bedarf an Bruchmengen zeigt.
