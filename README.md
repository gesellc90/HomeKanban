# HomeKanban

Kanban-Verwaltung für Alltagsverbrauchsmittel im Haushalt — läuft im Heimnetz auf einem
Raspberry Pi, parallel zur bestehenden Web-App „Hängt! – jeder Strich zählt“.

> **Status: Planung abgeschlossen, Umsetzung noch nicht begonnen.**
> Anforderungen und Rahmen: [`docs/PROJEKT-PROMPT.md`](docs/PROJEKT-PROMPT.md).
> Architektur, Datenmodell, Meilensteine, Risiken: [`docs/PLAN.md`](docs/PLAN.md).

## Idee in drei Sätzen

Jedes Verbrauchsmittel (Spülmaschinentabs, Klopapier, Kaffee …) hat einen Bestand, einen
Mindestbestand und einen QR-Code am Vorratsort. Wer etwas entnimmt, scannt den Code und bestätigt
die Entnahme auf der Artikelseite — der Scan allein bucht nichts. Fällt der Bestand unter den
Mindestbestand, landet der Artikel automatisch auf der Einkaufsliste, die ein Apple-Kurzbefehl als
abhakbare Checkliste in Apple Notes holt.

## Entschiedener Rahmen

| Bereich | Entscheidung |
| --- | --- |
| Backend | Python + FastAPI |
| Frontend | Serverseitige Templates + HTMX, mobile-first, Assets lokal (keine CDNs) |
| Datenbank | SQLite |
| Betrieb | Docker Compose auf dem Raspberry Pi, eigener Port und eigenes Volume |
| Zugriff | Nur Heimnetz, kein Login |
| Kanban | Mengenzählung mit Mindest-/Sollbestand, abgeleiteter Status, Bewegungsjournal |
| Rückmeldung | QR-Code je Artikel → Artikelseite → Entnahme bestätigen |
| Einkaufsliste | Export-Endpoint, den ein iOS-Kurzbefehl in Apple Notes schreibt |
| Etiketten | Einzel-QR je Artikel + Sammel-PDF mit Etikettenbögen |
| Checks | Ausschließlich lokal (Git-Hooks + Make), **keine GitHub Actions** |
| Lizenz | **Noch nicht festgelegt** — bewusst keine `LICENSE` im Repo |

## Meilensteine

| # | Meilenstein | Status |
| --- | --- | --- |
| M0 | Fundament & technische Entscheidungen | offen |
| M1 | Domänenmodell & Persistenz | offen |
| M2 | Kanban-Board & Artikelpflege | offen |
| M3 | QR-Entnahme-Flow | offen |
| M4 | Einkaufsliste & Apple-Notes-Export | offen |
| M5 | Etiketten (Einzel-QR + PDF-Bögen) | offen |
| M6 | Deployment auf dem Raspberry Pi | offen |
| M7 | Kategorien & Ladenzuordnung | offen |
| M8 | Verbrauchshistorie & Prognose | offen |
| M9 | Backup & Restore | offen |

Umfang, Definition of Done und Testfokus je Meilenstein: [`docs/PLAN.md`](docs/PLAN.md) §9.

**Vor dem Etikettendruck (M5) zu klären:** welchen Port „Hängt!“ belegt und ob ein Reverse Proxy
davor liegt — die Basis-URL steckt in jedem gedruckten QR-Code. Siehe `docs/PLAN.md` §10, O2.

## Tests laufen lokal — nicht in der Cloud

Dieses Repository hat **absichtlich keine GitHub Actions**. Alle Prüfungen für Commits und Pull
Requests laufen auf dem Entwicklungsrechner über versionierte Git-Hooks in `.githooks/`.

Einmalig nach dem Klonen:

```bash
make hooks     # aktiviert die Git-Hooks (setzt core.hooksPath)
make setup     # richtet die Entwicklungsumgebung ein (ab M0)
```

Danach greifen automatisch:

- **`pre-commit`** → Format- und Lint-Prüfung
- **`pre-push`** → vollständiger Testlauf; ein roter Lauf bricht den Push ab

Manuell:

```bash
make fmt       # formatieren
make lint      # statische Prüfung
make test      # Tests
make check     # alles zusammen (das, was vor einem Push laufen muss)
```

Solange die Toolchain noch nicht steht (M0), melden die Targets sich als „noch nicht
konfiguriert“ und blockieren nicht.

## Repository-Struktur

```
CLAUDE.md                        Arbeitsanweisungen für Claude Code in diesem Projekt
Makefile                         Einstiegspunkt für alle lokalen Checks
docs/PROJEKT-PROMPT.md           Anforderungen, Technologie-Rahmen, Meilensteine
docs/PLAN.md                     Detailplanung: Architektur, Datenmodell, Risiken, Szenarien
docs/KURZBEFEHL.md               Anleitung für den iOS-Kurzbefehl (entsteht in M4)
docs/adr/                        Architekturentscheidungen, je eine Datei
.githooks/                       versionierte Git-Hooks (pre-commit, pre-push)
.github/                         PR- und Issue-Vorlagen (keine Workflows)
```

## Privatsphäre

Haushaltsdaten verlassen das Heimnetz nicht. Keine Cloud-Dienste, keine Telemetrie, keine externen
Assets zur Laufzeit. Auf dem Pi liegen keine Apple-Zugangsdaten — die Einkaufsliste wird vom
iPhone abgeholt, nicht vom Pi verschickt.
