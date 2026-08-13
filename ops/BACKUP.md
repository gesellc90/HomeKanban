# Backup und Restore

Kurznotiz aus M9 (docs/PLAN.md §9), nach dem Vorbild von [`ops/ETIKETTEN.md`](ETIKETTEN.md).
`ops/BETRIEB.md` bleibt M6 vorbehalten (Start/Stopp/Update/Log/Portprüfung) und verweist später
hierher — solange M6 aussteht, ist diese Datei der vollständige Weg für Sicherung und
Wiederherstellung.

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

### Zwei Aufrufwege — die Datenbank liegt in einem benannten Docker-Volume

`ops/compose.yaml` legt die Datenbank in das **benannte** Volume `homekanban-data`, nicht in
einen Bind-Mount. Ein Host-Cron sieht `/data/homekanban.db` deshalb **nicht** ohne Weiteres.
Solange M6 das nicht löst, bleiben zwei Wege, und `ops/backup.py` selbst trifft keine Annahme über
`/data` — beide funktionieren mit denselben `--db-path`/`--backup-dir`-Optionen:

**a) Im Container** (einfachster Weg, kein zusätzlicher Mount nötig):

```cron
# Jeden Tag um 3:10 Uhr, im Container gegen die Container-Pfade
10 3 * * * docker compose -f /pfad/zu/ops/compose.yaml exec -T homekanban \
  python ops/backup.py --db-path /data/homekanban.db --backup-dir /data/backups
```

Das Sicherungsverzeichnis liegt dann **innerhalb** desselben Volumes wie die Datenbank — sicher
gegen den Verlust der SQLite-Datei selbst, aber **nicht** gegen den Verlust der ganzen SD-Karte,
solange kein zusätzlicher Bind-Mount oder Kopierschritt nach draußen führt (siehe unten).

**b) Auf dem Host**, mit einem zusätzlichen Bind-Mount nur für das Sicherungsverzeichnis (in
`ops/compose.yaml` zu ergänzen, z. B. `- /pfad/auf/dem/host/backups:/data/backups`):

```cron
10 3 * * * cd /pfad/zum/repo && .venv/bin/python ops/backup.py \
  --db-path /var/lib/docker/volumes/.../homekanban.db --backup-dir /pfad/auf/dem/host/backups
```

Weg (b) ist der, der die Sicherung tatsächlich von der SD-Karte herunterbekommt, ohne
`docker exec`. **Welcher der beiden Wege auf dem Pi eingerichtet wird, ist noch offen** — das
gehört zu M6, wenn Compose gehärtet und der Bind-Mount tatsächlich ergänzt wird.

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

**Entschieden (Fragerunde M9, Frage 4):** In diesem Durchgang **nichts automatisiert** — R5
verlangt ein Backup-Ziel außerhalb des Pi, aber welches Gerät im Haushalt dafür infrage kommt, war
zum Zeitpunkt dieses Durchgangs noch nicht entschieden. `ops/backup.py` schreibt bewusst
ausschließlich lokal nach `HOMEKANBAN_BACKUP_DIR` und kennt kein Zielsystem.

**Bis dahin: von Hand.** Das Sicherungsverzeichnis (`HOMEKANBAN_BACKUP_DIR`, per Cron-Weg (b) auf
dem Host sichtbar) regelmäßig auf ein zweites Gerät kopieren — USB-Stick, Laptop, NAS, was auch
immer im Haushalt vorhanden ist. Ein Backup, das nur auf derselben SD-Karte liegt wie die
Datenbank, übersteht einen Kartentod nicht. Sobald ein Gerät feststeht, gehört das hier als zweiter
Cron-Eintrag (`rsync`/`scp`, Schlüssel außerhalb des Repos) ergänzt.

## Restore — Schritt für Schritt

1. **Container stoppen.** `docker compose stop homekanban` (oder `down`). Läuft die App weiter,
   entstehen sofort wieder frische `-wal`/`-shm`-Dateien gegen die alte Datenbank, während der
   Restore eine neue unterschiebt.
2. **Zurückspielen:**

   ```sh
   python ops/restore.py --backup-file /pfad/zur/20260813T115650Z.db.gz --db-path /data/homekanban.db
   ```

   `ops/restore.py` prüft das Backup (`PRAGMA integrity_check` + Kerntabellen), **bevor** eine
   vorhandene Datenbank überhaupt angefasst wird. Eine vorhandene Datenbank wird **nie gelöscht**,
   sondern nach `<name>.vor-restore-<Zeitstempel>` verschoben (CLAUDE.md §4) — inklusive
   liegengebliebener `-wal`/`-shm`-Dateien, die sonst gegen den frisch restaurierten Stand
   abgespielt würden und ihn verfälschen könnten.
3. **Container wieder starten:** `docker compose up -d`.
4. **Nachweis:** `GET /healthz` aufrufen. `{"status": "ok"}` heißt: die Journal-Invariante
   `SUM(movements.delta) == items.stock` (L2) hält über die gesamte restaurierte Datenbank. Ein
   Blick aufs Board bestätigt zusätzlich, dass der erwartete Bestand wieder da ist.

Dieser Rundlauf wurde im Rahmen von M9 tatsächlich durchgeführt — mit einer echten Datenbankdatei
und der laufenden App (Docker war in der Entwicklungsumgebung nicht verfügbar, der
Container-spezifische Teil bleibt daher ungeprüft, siehe docs/PLAN.md §9, M9).

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

- Der tatsächliche Cron-Lauf auf dem Pi (beide Aufrufwege oben sind nur beschrieben, nicht auf
  echter Pi-Hardware ausgeführt).
- Der Zugriff auf das benannte Docker-Volume aus einem Host-Cron heraus.
- Die Kopie auf ein Gerät außerhalb des Pi — welches Gerät das wird, ist offen (siehe oben).
- Der Container-Teil des Restore-Rundlaufs (`docker compose stop`/`up`) — in der
  Entwicklungsumgebung ohne Docker durchgeführt, siehe oben.
