# Backup und Restore

Kurznotiz aus M9 (docs/PLAN.md §9), nach dem Vorbild von [`ops/ETIKETTEN.md`](ETIKETTEN.md), in M6
korrigiert und um die entschiedenen Wege ergänzt. [`ops/BETRIEB.md`](BETRIEB.md) verweist hierher
(Phase 11/12) statt den Inhalt zu duplizieren.

## Was gesichert wird — und was nicht

Zwei getrennte, unterschiedlich mächtige Wege:

| Weg | Werkzeug | Umfang | Wofür |
| --- | --- | --- | --- |
| **Datenbank-Backup** | `ops/backup.py` | die komplette SQLite-Datei: Artikel, **Bewegungsjournal**, Einkaufslisten, Kategorien, Läden | die eigentliche Sicherung (R5) |
| **Stammdaten-Export** | Seite `/stammdaten` im Browser | Artikel (mit Vorlaufzeit), Kategorien, Läden — **ohne** Bewegungen, **ohne** Einkaufslisten | zum Ansehen und Wiederanlegen, **keine** zweite Sicherung |

Ein Stammdaten-Import erzeugt neue Artikel über `app/services/stock.py::book_create_item()` und
damit **neue QR-Codes** — bestehende, geklebte Etiketten würden ins Leere zeigen und müssten neu
gedruckt werden. Für den unveränderten Bestand samt Verlauf ist ausschließlich das
Datenbank-Backup gedacht.

## Datenbank-Backup einrichten

`ops/backup.py` sichert über die SQLite-`.backup()`-API (kein `cp` auf die offene Datei — im
WAL-Modus wäre das Ergebnis eine stille Inkonsistenz), komprimiert mit gzip und wendet danach die
Aufbewahrungsregel an (siehe unten). Aufruf:

```sh
python ops/backup.py [--db-path PFAD] [--backup-dir PFAD]
```

Ohne Angabe werden `HOMEKANBAN_DB_PATH`/`HOMEKANBAN_BACKUP_DIR` aus `.env` verwendet. Ein
erfolgreicher Lauf meldet den geschriebenen Dateinamen und was die Aufbewahrungsregel gelöscht
hat; ein fehlgeschlagener Lauf endet mit einer deutschen Meldung auf stderr und einem von Null
verschiedenen Exit-Code — nie mit einem Stacktrace.

### Der Cron-Lauf — im Container (M6-Fragerunde, Frage 2)

`ops/compose.yaml` legt die Datenbank in das **benannte** Volume `homekanban-data`, nicht in
einen Bind-Mount. Ein Host-Cron sieht `/data/homekanban.db` deshalb nicht ohne Weiteres.
`ops/BACKUP.md` beschrieb dafür in M9 zwei mögliche Wege und entschied keinen — **entschieden in
M6, gegen die ursprüngliche Empfehlung „Bind-Mount + Host-Cron“:** alles bleibt im Container. Der
Cron-Eintrag steht auf dem **Host**, ruft aber `docker compose exec` auf:

```cron
# Jeden Tag um 3:10 Uhr, im Container gegen die Container-Pfade
10 3 * * * cd /pfad/zum/repo/ops && docker compose --env-file ../.env exec -T homekanban \
  python ops/backup.py --db-path /data/homekanban.db --backup-dir /data/backups
```

Damit das im Container überhaupt funktioniert, kopiert `ops/Dockerfile` seit M6 `ops/backup.py`
und `ops/restore.py` mit ins Image (`COPY ops/backup.py ops/restore.py ./ops/`) — **vorher war das
ein Defekt aus M9**: `ops/` lag nicht im Image, `docker compose exec … python ops/backup.py` wäre
mit „Datei nicht gefunden“ gescheitert.

**Konsequenz für R5:** Das Sicherungsverzeichnis liegt dadurch weiterhin **innerhalb** desselben
benannten Volumes wie die Datenbank — sicher gegen eine beschädigte oder gelöschte
`homekanban.db`, aber **nicht** gegen den Verlust der ganzen SD-Karte. Ein Backup-Ziel außerhalb
des Pi ist eine eigene, noch offene Baustelle — siehe unten.

## Aufbewahrung

`HOMEKANBAN_BACKUP_KEEP=7d,4w` (Vorgabe seit M0). Entschieden (Fragerunde M9, Frage 1): **zwei
Töpfe nach Alter** — die 7 jüngsten Backups bleiben so oder so; aus dem Rest bleibt je Backup-Datei
das jüngste einer ISO-Kalenderwoche, für die letzten 4 Wochen, in denen überhaupt ein Backup übrig
war. Ein täglicher Lauf über 40 Tage behält damit 11 Dateien und deckt gut fünf Wochen ab —
unabhängig davon, an welchem Wochentag der Cron lief oder ausfiel. Details und alle Randfälle
(Lücken, Jahreswechsel, zwei Backups am selben Tag) stehen als Tests in
`tests/domain/test_retention.py`, die Regel selbst in `app/domain/retention.py`.

Fremde Dateien im Sicherungsverzeichnis fasst `ops/backup.py` nicht an, und das eben geschriebene
Backup wird nie gelöscht, unabhängig von der konfigurierten Regel.

## Backup-Ziel außerhalb des Pi

**Weiterhin offen** — schon in M9 zurückgestellt (Frage 4 dort) und in der M6-Fragerunde erneut
gefragt: Noch immer steht kein Gerät im Haushalt dafür fest (USB-Platte am Pi, NAS, Laptop). R5
bleibt damit zum Teil ungelöst — solange nur innerhalb des Volumes gesichert wird, schützt das
Backup vor einer beschädigten `homekanban.db`, aber **nicht** vor dem Verlust der ganzen SD-Karte.
`ops/backup.py` schreibt bewusst ausschließlich lokal nach `HOMEKANBAN_BACKUP_DIR` und kennt kein
Zielsystem — das bleibt unverändert.

**Bis ein Gerät feststeht: von Hand, aus dem Volume heraus.** Weil das Sicherungsverzeichnis seit
M6 im Container liegt (Frage 2), reicht ein Blick in den Bind-Mount nicht mehr — die Datei muss
aus dem laufenden Container kopiert werden:

```sh
cd /pfad/zum/repo/ops
docker compose --env-file ../.env cp homekanban:/data/backups/20260813T031000Z.db.gz .
```

Diese Kopie dann auf ein zweites Gerät bringen — USB-Stick, Laptop, NAS, was auch immer im
Haushalt vorhanden ist. Sobald ein Gerät feststeht, gehört das hier als eigener, automatisierter
Schritt ergänzt (z. B. ein zweiter Cron-Eintrag, der zuerst `docker compose cp` und danach
`rsync`/`scp` mit einem Schlüssel außerhalb des Repos ausführt).

## Restore — Schritt für Schritt

Ausgeführt vom Repo-Verzeichnis `ops/` aus, mit derselben `--env-file ../.env`-Angewohnheit wie
beim Backup-Cron (siehe oben und ops/compose.yaml).

1. **Container anhalten, Volume aber verfügbar lassen:** `docker compose --env-file ../.env stop
   homekanban` (**nicht** `down -v` — das würde das Volume und damit alle Backups löschen). Läuft
   die App weiter, entstehen sofort wieder frische `-wal`/`-shm`-Dateien gegen die alte Datenbank,
   während der Restore eine neue unterschiebt.
2. **Zurückspielen — im Container, mit `run` statt `exec`** (der reguläre Dienst steht ja gerade
   still):

   ```sh
   docker compose --env-file ../.env run --rm homekanban \
     python ops/restore.py --backup-file /data/backups/20260813T115650Z.db.gz \
     --db-path /data/homekanban.db
   ```

   `ops/restore.py` prüft das Backup (`PRAGMA integrity_check` + Kerntabellen), **bevor** eine
   vorhandene Datenbank überhaupt angefasst wird. Eine vorhandene Datenbank wird **nie gelöscht**,
   sondern nach `<name>.vor-restore-<Zeitstempel>` verschoben (CLAUDE.md §4) — inklusive
   liegengebliebener `-wal`/`-shm`-Dateien, die sonst gegen den frisch restaurierten Stand
   abgespielt würden und ihn verfälschen könnten. Kommt das Backup von einem externen Gerät statt
   aus `/data/backups` selbst, es zuerst mit `docker compose --env-file ../.env cp
   <lokale-datei>.db.gz homekanban:/data/backups/` ins Volume kopieren.
3. **Container wieder starten:** `docker compose --env-file ../.env up -d`.
4. **Nachweis:** `GET /healthz` aufrufen. `{"status": "ok"}` heißt: die Journal-Invariante
   `SUM(movements.delta) == items.stock` (L2) hält über die gesamte restaurierte Datenbank. Ein
   Blick aufs Board bestätigt zusätzlich, dass der erwartete Bestand wieder da ist.

Der fachliche Ablauf (Backup schreiben, Datenbankdatei entfernen, restaurieren, `/healthz` und
Board prüfen) wurde im Rahmen von M9 tatsächlich durchgeführt — mit einer echten Datenbankdatei und
der laufenden App über `uvicorn`, weil in der Entwicklungsumgebung kein Docker-Daemon lief (siehe
docs/PLAN.md §9, M9). Die obigen Container-Befehle sind für M6 syntaktisch geprüft
(`docker compose config`, siehe `ops/BETRIEB.md`), aber **ein echter Restore-Rundlauf mit
laufendem Container steht weiterhin aus** — das ist genau der Nachweis, den `ops/BETRIEB.md`
Phase 12 am Pi verlangt.

## Was tun, wenn die Karte tot ist

1. Neue SD-Karte (oder besser: USB-SSD, siehe R5) mit demselben Compose-Setup einrichten.
2. Das jüngste Backup vom externen Gerät (siehe oben) auf die neue Karte kopieren.
3. Restore-Schritte oben durchführen — der Zielpfad ist einfach die neue, leere Datenbankdatei.
4. `GET /healthz` und Board prüfen.

Ohne ein Backup außerhalb der toten Karte ist an dieser Stelle nichts mehr zu retten — das ist
genau der Grund für den vorigen Abschnitt.

## Stammdaten-Export und -Import

Seite `/stammdaten` im Browser (Fragerunde M9, Frage 3 — als UI-Endpunkt statt CLI-Skript, gegen
die ursprüngliche Empfehlung, aber mit dem Nutzer so entschieden):

- **Export:** JSON oder CSV herunterladen. JSON ist das vollständige, verlustfreie Format
  (inklusive Kategorien/Läden ohne zugeordneten Artikel); CSV enthält nur Artikelzeilen —
  Kategorien und Läden ergeben sich aus den `category`/`store`-Spalten und gehen verloren, wenn
  ihnen kein Artikel zugeordnet ist.
- **Import:** Datei hochladen (Format an der Endung `.json`/`.csv` erkannt). Der Import ist
  **alles oder nichts**: Existiert auch nur ein Name bereits (Artikel, Kategorie, Laden) oder
  verweist ein Artikel auf eine nirgends deklarierte Kategorie/einen nirgends deklarierten Laden,
  wird der **gesamte** Import verweigert, mit einer Liste aller gefundenen Probleme auf Deutsch —
  nichts wird geschrieben, bestehende Daten bleiben unangetastet.
- Importierte Artikel bekommen **neue QR-Codes** (siehe oben) — für den unveränderten Bestand ist
  das Datenbank-Backup gedacht, nicht dieser Weg.

## Was hier ungeprüft bleibt

- Der tatsächliche Cron-Lauf auf dem Pi (der Aufrufweg oben ist mit `docker compose config`
  syntaktisch geprüft, aber nicht auf echter Pi-Hardware ausgeführt).
- Die Kopie auf ein Gerät außerhalb des Pi — welches Gerät das wird, ist weiterhin offen (siehe
  oben, M6-Fragerunde Frage 3).
- Der Container-Teil des Restore-Rundlaufs (`docker compose stop`/`run`/`up`) — in der
  Entwicklungsumgebung ohne laufenden Docker-Daemon durchgeführt, siehe oben. Nachweis folgt in
  `ops/BETRIEB.md` Phase 12.
