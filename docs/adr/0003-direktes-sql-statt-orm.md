# 0003 — Direktes SQL statt ORM

- **Status:** entschieden
- **Datum:** 2026-08-11
- **Meilenstein:** M0

## Kontext

Das Datenmodell umfasst sieben Tabellen (`items`, `movements`, `shopping_lists`,
`shopping_list_lines`, `categories`, `stores`, `schema_migrations`) mit klar umrissenen
Zugriffsmustern und einer Ledger-Semantik, die transaktional exakt sein muss (siehe ADR 0002). Die
Zielhardware ist ein Raspberry Pi, auf dem schwere Abhängigkeiten und Build-Ketten vermieden werden
sollen (`CLAUDE.md` §4).

## Entscheidung

Datenzugriff läuft über `sqlite3` aus der Python-Standardbibliothek, mit einer dünnen
Repository-Schicht in `app/repo/` (eine Datei je Tabelle bzw. Aggregat) und expliziten Transaktionen
über `app/db.py`. Kein ORM.

## Alternativen

- **SQLAlchemy:** Bringt Migrations-Tooling (Alembic) und Query-Abstraktion mit, aber auch Gewicht
  und eine Indirektionsebene, die bei sieben Tabellen und wenigen, gut verstandenen Zugriffen keinen
  Gegenwert liefert — insbesondere nicht für die Ledger-Semantik, die ohnehin handgeschriebene
  Transaktionslogik braucht.

## Konsequenzen

Volle Kontrolle über Transaktionsgrenzen und PRAGMAs (`app/db.py`), keine schwere Abhängigkeit auf
dem Pi, und SQL bleibt in Migrationsdateien und Repositories direkt lesbar. Der Preis: mehr
Handarbeit bei komplexeren Abfragen (z. B. der Prognose in M8) und keine automatische
Schema-Introspektion — dafür passt die Migrationslösung (numerierte `.sql`-Dateien plus schlanker
Runner, siehe `app/migrate.py`) ohne zusätzliches Werkzeug zu dieser Entscheidung.
