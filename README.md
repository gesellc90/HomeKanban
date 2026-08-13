# HomeKanban

Kanban-Verwaltung für Alltagsverbrauchsmittel im Haushalt — läuft im Heimnetz auf einem
Raspberry Pi, parallel zur bestehenden Web-App „Hängt! – jeder Strich zählt“.

> **Status: M0–M5 und M7–M9 umgesetzt (Fundament, Domänenmodell & Persistenz, Board &
> Artikelpflege, QR-Entnahme-Flow, Einkaufsliste & Apple-Notes-Export, Etiketten, Kategorien &
> Ladenzuordnung, Verbrauchshistorie & Prognose, Backup & Restore).**
> Vier Punkte stehen noch aus, alle brauchen ein iPhone, einen Drucker, Wochen echter Nutzung oder
> den Pi selbst statt Code: Der iOS-Kurzbefehl aus M4 ist noch nicht auf dem iPhone durchgeführt
> worden — das gilt seit M7 auch für den geänderten, gruppierten Export
> ([`docs/KURZBEFEHL.md`](docs/KURZBEFEHL.md)) —, die Etiketten aus M5 sind noch nicht gedruckt,
> gemessen und gescannt ([`ops/ETIKETTEN.md`](ops/ETIKETTEN.md)), ob die in M8 gerechnete
> Reichweite im echten Haushalt plausibel ist, kann erst echte Buchungshistorie zeigen, keine
> Testsuite, und der Container-Teil des M9-Restores sowie der Cron-Lauf und die Kopie eines
> Backups auf ein Gerät außerhalb des Pi sind mangels Docker/Pi in der Entwicklungsumgebung
> ungeprüft ([`ops/BACKUP.md`](ops/BACKUP.md)).
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
| Etiketten | Einzel-QR je Artikel + druckoptimierte A4-Etikettenbögen (ADR 0004) |
| Checks | Ausschließlich lokal (Git-Hooks + Make), **keine GitHub Actions** |
| Lizenz | **Noch nicht festgelegt** — bewusst keine `LICENSE` im Repo |

## Meilensteine

| # | Meilenstein | Status |
| --- | --- | --- |
| M0 | Fundament & technische Entscheidungen | erledigt |
| M1 | Domänenmodell & Persistenz | erledigt |
| M2 | Kanban-Board & Artikelpflege | erledigt |
| M3 | QR-Entnahme-Flow | erledigt |
| M4 | Einkaufsliste & Apple-Notes-Export | erledigt — iPhone-Verifikation des Kurzbefehls steht aus |
| M5 | Etiketten (Einzel-QR + Druckbögen) | erledigt — Testdruck, Messung und Scanprobe stehen aus |
| M6 | Deployment auf dem Raspberry Pi | offen |
| M7 | Kategorien & Ladenzuordnung | erledigt — iPhone-Verifikation des geänderten Exports steht aus |
| M8 | Verbrauchshistorie & Prognose | erledigt — Plausibilität der Reichweite im echten Haushalt steht aus |
| M9 | Backup & Restore | erledigt — Container-Teil des Restores, Cron-Lauf und externe Kopie stehen aus |

Umfang, Definition of Done und Testfokus je Meilenstein: [`docs/PLAN.md`](docs/PLAN.md) §9.

**Pi-Zugriff:** `192.168.0.15` im Heimnetz, aktuell ohne Reverse Proxy vor „Hängt!“ (ein Proxy ist
dort vorgesehen und könnte später ergänzt werden, siehe `docs/PLAN.md` §10, O2). HomeKanban wird
trotzdem über einen mDNS-Hostnamen statt der festen IP angesprochen, damit die gedruckten
QR-Etiketten einen Hardware- oder Adresswechsel überleben. Seit M5 steht der Wert fest:
`http://homekanban.local:8181` — er steckt in jedem gedruckten Code und ist ohne Neudruck nicht
mehr zu ändern (`docs/PLAN.md` §8, R6). Der mDNS-Alias auf dem Pi und der Nachweis, dass Port
`8181` frei ist (`ss -ltnp`), gehören nach M6 — beides muss aber **vor** dem ersten Etikettendruck
erledigt sein.

## Tests laufen lokal — nicht in der Cloud

Dieses Repository hat **absichtlich keine GitHub Actions**. Alle Prüfungen für Commits und Pull
Requests laufen auf dem Entwicklungsrechner über versionierte Git-Hooks in `.githooks/`.

Einmalig nach dem Klonen:

```bash
make hooks     # aktiviert die Git-Hooks (setzt core.hooksPath)
make setup     # richtet die Entwicklungsumgebung ein (venv, Abhängigkeiten aus pyproject.toml)
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

Seit M0 tun die Targets echte Arbeit: `ruff` (Format + Lint), `mypy` (scharf auf `app/domain/`)
und `pytest`.

## Repository-Struktur

```
CLAUDE.md                        Arbeitsanweisungen für Claude Code in diesem Projekt
Makefile                         Einstiegspunkt für alle lokalen Checks
docs/PROJEKT-PROMPT.md           Anforderungen, Technologie-Rahmen, Meilensteine
docs/PLAN.md                     Detailplanung: Architektur, Datenmodell, Risiken, Szenarien
docs/KURZBEFEHL.md               Anleitung für den iOS-Kurzbefehl (Apple Notes / Erinnerungen)
docs/adr/                        Architekturentscheidungen, je eine Datei
ops/ETIKETTEN.md                 Etikettenformat, Größe, Scanreichweite, Schritte vor dem Druck
.githooks/                       versionierte Git-Hooks (pre-commit, pre-push)
.github/                         PR- und Issue-Vorlagen (keine Workflows)
```

## Privatsphäre

Haushaltsdaten verlassen das Heimnetz nicht. Keine Cloud-Dienste, keine Telemetrie, keine externen
Assets zur Laufzeit. Auf dem Pi liegen keine Apple-Zugangsdaten — die Einkaufsliste wird vom
iPhone abgeholt, nicht vom Pi verschickt.
