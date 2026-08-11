# HomeKanban

Kanban-Verwaltung für Alltagsverbrauchsmittel im Haushalt — läuft im Heimnetz auf einem
Raspberry Pi, parallel zur bestehenden Web-App „Hängt! – jeder Strich zählt“.

> **Status: Planungsphase.** Es gibt noch keinen Anwendungscode. Anforderungen, Technologie-Rahmen
> und Meilensteine stehen in [`docs/PROJEKT-PROMPT.md`](docs/PROJEKT-PROMPT.md).

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

Details zu Umfang, Definition of Done und Testfokus je Meilenstein:
[`docs/PROJEKT-PROMPT.md`](docs/PROJEKT-PROMPT.md).

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
docs/PLAN.md                     Detailplanung (entsteht im Planungsdurchgang)
docs/adr/                        Architekturentscheidungen, je eine Datei
.githooks/                       versionierte Git-Hooks (pre-commit, pre-push)
.github/                         PR- und Issue-Vorlagen (keine Workflows)
```

## Privatsphäre

Haushaltsdaten verlassen das Heimnetz nicht. Keine Cloud-Dienste, keine Telemetrie, keine externen
Assets zur Laufzeit. Auf dem Pi liegen keine Apple-Zugangsdaten — die Einkaufsliste wird vom
iPhone abgeholt, nicht vom Pi verschickt.
