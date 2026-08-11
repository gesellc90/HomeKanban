# HomeKanban — Gesamtplan

Detailplanung auf Basis von [`PROJEKT-PROMPT.md`](PROJEKT-PROMPT.md). Diese Datei ist ab jetzt die
verbindliche Referenz für Architektur, Datenmodell und Meilensteine. Weicht die Umsetzung ab, wird
sie im selben Pull Request nachgezogen.

**Stand:** M0 (Fundament & Entscheidungen) umgesetzt. M1 (Domänenmodell & Persistenz) umgesetzt.

---

## 1. Leitentscheidungen

Diese Entscheidungen tragen den Entwurf. Jede ist mit Begründung und verworfener Alternative
festgehalten; die vier mit `†` markierten werden in M0 als ADR unter `docs/adr/` formalisiert, weil
sie schwer umkehrbar sind.

| # | Entscheidung | Begründung | Verworfene Alternative |
| --- | --- | --- | --- |
| L1 † | **Ganzzahlige Mengen**, keine Dezimalwerte. Die Einheit benennt das zählbare Ding (Packung, Rolle, Flasche, „500-g-Paket“). | Kanban zählt, was im Schrank steht. Dezimalwerte versprechen eine Genauigkeit, die der Prozess nicht liefert — niemand wiegt bei der Entnahme das Mehl. Ganzzahlen halten Journalsummen exakt und die Domänenlogik trivial testbar. | `REAL`-Spalten (Rundungsdrift in Summen) oder Tausendstel-Integer (Komplexität in jeder Schicht, ohne Alltagsnutzen). **Rückweg:** Da alle Werte bereits Integer sind, könnte eine einzige Migration die Spaltensemantik auf Tausendstel umdeuten (`× 1000`), ohne Datenverlust. |
| L2 † | **Das Bewegungsjournal ist die Wahrheit**, `items.stock` ist ein mitgeführter Cache. Beide werden in derselben Transaktion geschrieben, jede Bewegung speichert zusätzlich `stock_after`. | Das Board rendert ohne Aggregation über das Journal, die Historie bleibt vollständig erklärbar. Die Invariante `SUM(movements.delta) == items.stock` ist prüfbar und wird getestet. | Bestand bei jedem Lesen aus dem Journal aggregieren (unnötige Last auf dem Pi, und Inventur braucht ohnehin einen Bezugspunkt). |
| L3 | **Kein Löschen, kein Überschreiben im Journal.** Rückgängig = ausgleichende Gegenbewegung mit `reverts_movement_id`. | Ein Journal, das nachträglich verändert wird, kann keine Verbrauchsprognose tragen. Undo bleibt so ein normaler Buchungsvorgang. | `DELETE` der Fehlbuchung (zerstört Nachvollziehbarkeit, bricht `stock_after`-Kette). |
| L4 | **Kein Drag & Drop im Board.** Spalten sind reine Gruppierung, Aktionen sind Buttons. | Der Status ist abgeleitet. Ein Artikel „nach Nachkaufen zu ziehen“ wäre eine Lüge — der Bestand bestimmt die Spalte, nicht umgekehrt. Spart zusätzlich eine JS-Abhängigkeit. | Sortable-Bibliothek mit Statusschreibung (widerspricht dem Mengenmodell). |
| L5 † | **Direktes SQL über `sqlite3` aus der Standardbibliothek**, dünne Repository-Schicht, kein ORM. | Sieben Tabellen, klar umrissene Zugriffe, volle Kontrolle über Transaktionen und Ledger-Semantik. Keine schwere Abhängigkeit auf dem Pi. | SQLAlchemy (Gewicht und Indirektion ohne Gegenwert in dieser Größe). |
| L6 | **Migrationen als numerierte `.sql`-Dateien** plus 40-zeiliger Runner, Versionsstand in `schema_migrations`. Anwendung beim Start, protokolliert. | Passt zu L5, keine weitere Abhängigkeit, in Git diffbar und auf dem Pi ohne Werkzeug nachvollziehbar. | Alembic (setzt SQLAlchemy voraus). |
| L7 | **QR-Codes mit `segno`**; SVG inline für Etikettenbögen, PNG für Einzeldownload. | Reines Python, keine C-Abhängigkeit, keine Pillow-Kompilierung auf ARM. SVG bleibt beim Druck bei jeder Auflösung scharf. | `qrcode` + Pillow (Bildstack als Abhängigkeit, nur um Quadrate zu zeichnen). |
| L8 | **Etikettenbögen als druckoptimierte HTML-Seite** mit `@page`-CSS und Millimeter-Raster, gedruckt über den Browserdialog. Keine PDF-Bibliothek. | Null zusätzliche Abhängigkeit, Vorschau im Browser, funktioniert von jedem Gerät. Gegen Skalierungsfehler gibt es eine Kalibrierseite. | ReportLab (echte PDF-Kontrolle, aber eine weitere Abhängigkeit; als Rückfallposition in M5 notiert, falls der Browserdruck nicht maßhaltig druckt). |
| L9 | **Ein Zeitstempel-Format:** UTC, ISO-8601 mit `Z`, als `TEXT`. Anzeige in `Europe/Berlin`. | SQLite hat keinen Datumstyp; ISO-8601-Text sortiert lexikalisch korrekt. UTC in der Datenbank macht die Zeitumstellung im März und Oktober unauffällig — sonst hätte die Nacht der Umstellung doppelte oder fehlende Stunden im Journal. | Lokalzeit speichern (Prognoserechnung wird um die Zeitumstellung falsch) oder Unix-Integer (in der Datenbank nicht lesbar). |
| L10 | **Letzter Schreibzugriff gewinnt** bei Artikelstammdaten; **Buchungen kollidieren nicht**, weil sie nur anhängen. Die Inventur schickt den erwarteten Bestand mit und warnt bei Abweichung. | Ein Haushalt braucht keine Sperren. Die einzige Stelle mit echtem Konfliktpotenzial ist das absolute Setzen des Bestands — dort reicht eine optimistische Prüfung. | Sperren oder Versionszähler auf allen Entitäten (Aufwand ohne Nutzen bei vier Personen). |
| L11 | **Docker ab M0**, nicht erst in M6. Entwicklung und Pi laufen im selben Image. | Verhindert das klassische „läuft bei mir“ am Ende. M6 reduziert sich damit auf Pi-Spezifika: Port, Volume, Autostart, Betriebshandbuch. | Container erst zum Deployment bauen (verschiebt alle Überraschungen an den spätesten Punkt). |
| L12 | **API-Key nur für die Export-Schnittstelle**, restliche App ohne Authentifizierung. | Der Export ist der einzige Endpunkt, den ein Gerät außerhalb des Browsers automatisiert aufruft; ein Key kostet dort nichts und verhindert versehentliche Fremdabrufe. Für die UI würde jede Hürde den Zwei-Tap-Anspruch brechen. | Alles offen (der Key ist billig) oder alles hinter PIN (widerspricht der Zugriffsentscheidung). |

### Sichtbare Annahmen

| # | Annahme | Auswirkung, falls falsch |
| --- | --- | --- |
| A1 | „Hängt!“ belegt **nicht** Port `8181`. Der Port ist über `.env` frei setzbar; M6 enthält einen Prüfschritt auf dem Pi vor dem ersten Start. | Nur eine Zahl in `.env`, aber **vor** dem Etikettendruck zu klären — die Portnummer steht in jedem QR-Code. |
| A2 | Auf dem Pi läuft **kein** Reverse Proxy, der Namen auf Dienste verteilt; der Zugriff erfolgt direkt über `http://<hostname>.local:<port>`. | Mit Proxy wäre eine Pfad- oder Subdomain-Basis besser (`http://pi.local/kanban`) — das ist reine Konfiguration von `BASE_URL`, muss aber ebenfalls vor dem Etikettendruck stehen. |
| A3 | Das Pi-Betriebssystem ist 64-bit (`aarch64`). | Bei 32-bit armv7 muss das Basis-Image gewechselt werden; da alle Abhängigkeiten reines Python sind, entstehen keine Build-Probleme. |
| A4 | Bis zu fünf Personen, grob 30–80 Artikel, wenige Buchungen pro Tag. | Die Größenordnung rechtfertigt SQLite und serverseitiges Rendern; bei tausenden Artikeln wäre die Board-Ansicht zu paginieren. |
| A5 | Die Haushaltsmitglieder scannen mit der iPhone-Kamera, nicht mit einer Scanner-App. | Andere Scanner öffnen URLs teils in In-App-Browsern ohne Cookies — der Entwurf hängt bewusst an keinem Cookie. |

---

## 2. Architekturüberblick

Ein einziger FastAPI-Prozess, serverseitig gerenderte Jinja2-Templates, HTMX für Teilaktualisierungen,
eine SQLite-Datei auf einem Volume. Kein Build-Schritt, kein Node, keine Laufzeit-Abhängigkeit ins
Internet.

```
  iPhone-Kamera                     Browser (Handy / Laptop)          Apple Kurzbefehl
        │ scannt Etikett                    │                                │ POST + X-API-Key
        │ http://pi.local:8181/e/<token>    │                                │
        ▼                                   ▼                                ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  FastAPI-Anwendung (ein Container)                                                   │
│                                                                                      │
│  web/  HTML-Router          api/  JSON- und Text-Router                              │
│    board, artikel, e/…        shopping-list export, healthz                           │
│    liste, etiketten                                                                  │
│         │                              │                                             │
│         └──────────────┬───────────────┘                                             │
│                        ▼                                                             │
│  services/   Anwendungsfälle: Entnahme buchen, rückgängig, Inventur,                 │
│              Liste erzeugen/abgleichen, Position abhaken, Prognose                   │
│                        │                                                             │
│              ┌─────────┴─────────┐                                                   │
│              ▼                   ▼                                                   │
│  domain/  reine Logik        repo/  SQL-Zugriff, Transaktionen                        │
│    Status, Nachkaufmenge,        items, movements, shopping_lists                     │
│    Rundung, Prognose             (eine Transaktion je Buchung)                        │
│    (keine I/O, kein SQL)                │                                             │
└─────────────────────────────────────────┼─────────────────────────────────────────────┘
                                          ▼
                              SQLite (WAL)  /data/homekanban.db
                                          │
                                          ▼
                              Backup: .backup-API → /data/backups/*.db.gz
```

**Warum diese Schichtung:** Die gesamte Fachlogik, die falsch sein kann — Schwellenübergänge,
Rundung auf die Kaufeinheit, Prognose — liegt in `domain/` ohne Datenbank und ohne HTTP. Dort
entstehen schnelle, tabellengetriebene Tests. `services/` klebt Domäne und Repository in einer
Transaktion zusammen, `web/` und `api/` enthalten keine Fachregeln.

### Verzeichnisstruktur

```
app/
  main.py                 App-Factory, Router-Registrierung, Lifespan (Migrationen, Prüfungen)
  config.py               Einstellungen aus .env (pydantic-settings)
  db.py                   Verbindung, PRAGMAs, Transaktions-Kontextmanager
  migrate.py              Migrationsrunner
  domain/
    quantities.py         Rundung auf Kaufeinheit, Nachkaufmenge
    status.py             Statusableitung (OK / Nachkaufen / Auf Liste)
    forecast.py           Verbrauchsrate, Reichweite, Schwellenvorschlag   (M8)
  repo/
    items.py  movements.py  shopping_lists.py  taxonomy.py
  services/
    stock.py              Entnahme, Zugang, Inventur, Rückgängig
    shopping.py           Liste erzeugen, abgleichen, abhaken, abschließen
    labels.py             QR-Erzeugung, Bogenaufteilung
  web/                    HTML-Router
    board.py  items.py  scan.py  shopping.py  labels.py  history.py  taxonomy.py
  api/
    export.py  health.py
  templates/              Jinja2, base + Seiten + HTMX-Partials
  static/
    htmx.min.js           mitgeliefert, kein CDN
    app.css               eine Datei, keine Framework-Abhängigkeit
migrations/               0001_init.sql, 0002_….sql
tests/
  domain/  services/  web/  api/  conftest.py
ops/
  Dockerfile  compose.yaml  backup.py  BETRIEB.md
docs/
  PROJEKT-PROMPT.md  PLAN.md  KURZBEFEHL.md  adr/
```

---

## 3. Datenmodell

Alle Mengen sind Ganzzahlen (L1), alle Zeitstempel UTC-ISO-8601-Text (L9).

### `items`

| Spalte | Typ | Anmerkung |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | eindeutig unter den nicht archivierten Artikeln (partieller Index, `COLLATE NOCASE`) |
| `unit` | TEXT NOT NULL | zählbare Einheit: „Packung“, „Rolle“, „Flasche“ |
| `note` | TEXT | z. B. „Marke egal, aber ohne Duft“ |
| `stock` | INTEGER NOT NULL | Cache, siehe L2 |
| `reorder_level` | INTEGER NOT NULL | Meldeschwelle |
| `target_stock` | INTEGER NOT NULL | Sollbestand nach dem Einkauf |
| `pack_size` | INTEGER NOT NULL DEFAULT 1 | Kaufeinheit für die Rundung |
| `category_id` | INTEGER NULL → `categories` | Spalte ab M1, UI ab M7 |
| `store_id` | INTEGER NULL → `stores` | Spalte ab M1, UI ab M7 |
| `qr_token` | TEXT NOT NULL UNIQUE | `secrets.token_urlsafe(16)`, 22 Zeichen |
| `position` | INTEGER NOT NULL | Sortierung innerhalb der Spalte |
| `archived_at` | TEXT NULL | archiviert statt gelöscht — das Journal soll gültig bleiben |
| `created_at`, `updated_at` | TEXT NOT NULL | |

Prüfregeln (in der Domäne **und** als `CHECK`): `stock >= 0`, `reorder_level >= 0`,
`pack_size >= 1`, `target_stock > reorder_level`. Die letzte Regel ist die wichtigste: wäre
`target_stock <= reorder_level`, käme der Artikel nach dem Einkauf sofort wieder auf die Liste.

`category_id` und `store_id` entstehen bereits in M1, obwohl die Oberfläche dazu erst in M7 kommt —
so muss der Export in M4 nicht später umgebaut werden (die im Prompt angesprochene Abhängigkeit).

### `movements` — Bewegungsjournal, nur anfügen

| Spalte | Typ | Anmerkung |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `item_id` | INTEGER NOT NULL → `items` | |
| `kind` | TEXT NOT NULL | `opening`, `withdrawal`, `restock`, `adjustment` |
| `delta` | INTEGER NOT NULL | negativ bei Entnahme; bei Inventur die tatsächlich angewandte Differenz |
| `stock_after` | INTEGER NOT NULL | Bestand nach dieser Buchung |
| `source` | TEXT NOT NULL | `qr`, `board`, `shopping_list`, `import` |
| `line_id` | INTEGER NULL → `shopping_list_lines` | verbindet einen Zugang mit der abgehakten Position |
| `idempotency_key` | TEXT NULL UNIQUE | pro gerenderter Seite einmal, siehe §5 |
| `reverts_movement_id` | INTEGER NULL → `movements` UNIQUE | Gegenbuchung; eindeutig, damit nichts zweimal rückgängig gemacht wird |
| `note` | TEXT | |
| `created_at` | TEXT NOT NULL | |

Jeder Artikel bekommt beim Anlegen eine `opening`-Bewegung. Damit gilt ausnahmslos
`SUM(delta) == items.stock` — eine Invariante, die getestet und von `/healthz` geprüft wird.
Ob eine Bewegung zurückgenommen wurde, wird über `reverts_movement_id` **abgeleitet**, nicht als
Flag gespeichert; so bleibt die Tabelle wirklich anfügend.

Index: `(item_id, created_at)` für Verlauf und Prognose.

### `shopping_lists` / `shopping_list_lines`

| `shopping_lists` | | |
| --- | --- | --- |
| `id`, `created_at`, `closed_at` | | |
| `status` | TEXT | `open`, `done`, `cancelled` |
| `exported_at`, `export_count` | | vom Kurzbefehl gesetzt |

Es gibt **höchstens eine offene Liste** — erzwungen durch einen partiellen Unique-Index auf
`status = 'open'`. Eine zweite Exportanfrage erzeugt daher keine zweite Liste, sondern gleicht die
bestehende ab (§6).

| `shopping_list_lines` | | |
| --- | --- | --- |
| `id`, `list_id`, `item_id` | | `UNIQUE(list_id, item_id)` unter den nicht verworfenen Positionen |
| `suggested_qty` | INTEGER | zum Zeitpunkt des Abgleichs berechnet |
| `purchased_qty` | INTEGER NULL | tatsächlich gekauft, kann abweichen |
| `name_snapshot`, `unit_snapshot` | TEXT | Kopie zum Erzeugungszeitpunkt |
| `checked_at`, `dropped_at` | TEXT NULL | |
| `position` | INTEGER | |

Die Namenskopie ist Absicht: Wird ein Artikel umbenannt, während die Liste im Supermarkt offen ist,
soll die Liste nicht plötzlich anders heißen.

### `categories`, `stores`, `schema_migrations`

`categories(id, name UNIQUE, position)` und `stores(id, name UNIQUE, position)` — die `position`
bestimmt in M7 die Reihenfolge im Export, damit die Liste der Laufrichtung durch den Laden folgt.
`schema_migrations(version PK, applied_at)`.

---

## 4. Zustandsmodell

Der Status wird bei jedem Lesen aus Bestand, Schwelle und Listenzugehörigkeit berechnet und
**nirgends gespeichert**.

```
                    stock > reorder_level
      ┌──────────────────────────────────────────────┐
      │                                              │
      ▼                                              │
┌───────────┐   Entnahme senkt        ┌────────────┐  │  Zugang hebt Bestand
│ AUSREICHEND│  Bestand auf ≤ Schwelle │ NACHKAUFEN │  │  über die Schwelle
│    (OK)   │──────────────────────▶ │            │──┘  (abgehakte Position,
└───────────┘                        └────────────┘      Inventur)
      ▲                                     │
      │                                      │ Liste erzeugt / abgeglichen
      │                                      ▼
      │                              ┌──────────────┐
      └──────────────────────────────│ AUF LISTE    │
        Position abgehakt →           │ (offen,      │
        Zugang gebucht                │ nicht        │
                                      │ abgehakt)    │
                                      └──────────────┘
```

Regeln, jede einzeln getestet:

1. `stock > reorder_level` → **AUSREICHEND**.
2. `stock <= reorder_level` und keine offene, nicht abgehakte Position → **NACHKAUFEN**.
3. Offene, nicht abgehakte Position vorhanden → **AUF LISTE** (unabhängig vom Bestand — der
   Artikel ist bereits eingeplant und soll nicht doppelt in der Liste stehen).
4. Archivierte Artikel erscheinen nirgends.
5. **Teilkauf:** Ist der Bestand nach dem Abhaken weiter `<= reorder_level`, fällt der Artikel
   sofort zurück auf **NACHKAUFEN** und erhält beim nächsten Abgleich eine neue Position mit dem
   Rest. Das ist der Fall „nur eine statt zwei Packungen bekommen“.

**Nachkaufmenge:** `ceil((target_stock - stock) / pack_size) * pack_size`, mindestens `pack_size`.
Beispiele, die als Testtabelle in `tests/domain/` landen:

| stock | target | pack | Vorschlag | warum |
| --- | --- | --- | --- | --- |
| 0 | 4 | 6 | 6 | eine Kaufeinheit deckt mehr als den Bedarf — trotzdem kauft man 6 |
| 3 | 4 | 1 | 1 | glatter Fall |
| 1 | 10 | 4 | 12 | 9 Bedarf → drei Vierer-Packs |
| 2 | 2 | 1 | 1 | Schwelle erreicht, Bedarf rechnerisch 0 → Minimum greift |

---

## 5. QR-Entnahme-Flow

**Etikett → URL:** `http://<BASE_URL>/e/<token>` — bewusst kurz. Jedes Zeichen mehr erhöht die
Modulzahl im QR-Code und damit die nötige Etikettengröße; `/e/` plus 22 Zeichen Token bleibt in
Version 3 und ist von einem 25-mm-Etikett auch bei schlechtem Licht im Vorratsschrank lesbar.

**Der GET verändert nichts.** Das ist keine Stilfrage: Kamera-Apps, Messenger-Vorschauen und
Browser laden URLs vorab. Deshalb:

- `GET /e/{token}` rendert nur, mit `Cache-Control: no-store`.
- Jede Buchung ist ein `POST` mit einem im Formular versteckten `idempotency_key`, der beim
  Rendern der Seite erzeugt wird. Ein zweites Absenden desselben Formulars — Reload, Zurück-Button,
  hektisches Doppeltippen — trifft auf den bestehenden Unique-Index und liefert **das vorhandene
  Ergebnis** statt einer zweiten Buchung.
- Nach dem POST: `303 See Other` auf `GET /e/{token}/ok/{movement_id}`. Damit ist auch das
  Neuladen der Ergebnisseite harmlos.

**Die Seite selbst** zeigt groß den Artikelnamen, den aktuellen Bestand und den Status. Primäre
Aktion ist ein einzelner großer Button „−1 entnommen“ — damit ist das Ziel von zwei Taps erreicht
(Scan bestätigen, Button drücken). Daneben ein Schrittwähler für „−N“ und, deutlich zurückgenommen,
„Bestand korrigieren“.

**Rückgängig:** Auf der Ergebnisseite steht für `UNDO_WINDOW_MINUTES` (Standard 10) ein
Rückgängig-Button. Er erzeugt eine Gegenbewegung (L3), keine Löschung. Nach Ablauf des Fensters ist
die Inventur der Korrekturweg.

**Der Weg für „ohne Liste gekauft“:** Die Entnahmeseite ist auf Entnehmen optimiert, weil das
99 % der Scans sind. Für Zugänge außerhalb der Einkaufsliste — jemand bringt spontan Klopapier mit —
führt „Bestand korrigieren“ auf derselben Seite zur Inventur. Damit gibt es keine Sackgasse, ohne
den Hauptfall zu verwässern.

**Die Inventur** schickt den beim Rendern gesehenen Bestand als `expected_stock` mit. Hat sich der
Bestand zwischenzeitlich geändert, wird nicht stillschweigend überschrieben, sondern nachgefragt
(L10). Sie schreibt eine `adjustment`-Bewegung mit der Differenz — nie eine direkte Änderung von
`items.stock`.

---

## 6. Einkaufsliste und Apple-Notes-Export

### Abgleich statt Neuerzeugung

Bei „Einkaufsliste erzeugen“ und bei jedem Export läuft derselbe Abgleich gegen die offene Liste:

- Artikel in **NACHKAUFEN** ohne Position → Position wird angefügt.
- Position, deren Artikel nicht mehr unter der Schwelle liegt und die **nicht** abgehakt ist →
  `dropped_at` wird gesetzt.
- Abgehakte Positionen bleiben unverändert stehen.
- `suggested_qty` wird für offene Positionen neu berechnet.

Damit beantwortet sich die Frage aus dem Prompt, was bei einer zweiten Exportanfrage passiert: Es
gibt nie zwei konkurrierende Listen, sondern eine Liste, die den aktuellen Bedarf zeigt.

**Teilweise abgehakte Liste:** „Einkauf abschließen“ verwirft die offenen Positionen und setzt die
Liste auf `done`. Die betroffenen Artikel liegen weiter unter ihrer Schwelle und stehen beim
nächsten Abgleich automatisch wieder drin — nichts geht verloren, und keine Liste schleppt sich über
Wochen.

### Abhaken bucht ein

`POST /liste/{id}/zeilen/{line_id}/abhaken` mit optionalem `purchased_qty`:

- ohne Angabe → `purchased_qty = suggested_qty`, Bestand wird auf `target_stock` gesetzt
- mit Angabe → `stock += purchased_qty`
- in beiden Fällen: eine `restock`-Bewegung mit `source = 'shopping_list'` und `line_id`, in einer
  Transaktion mit dem Setzen von `checked_at`
- Rücknahme („doch nicht gekauft“) erzeugt die Gegenbewegung und leert `checked_at`

### Export-Schnittstelle für den Kurzbefehl

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/shopping-list?format=text\|json` | lesen ohne Nebenwirkung (Debugging, Vorschau) |
| `POST` | `/api/shopping-list/export?format=text\|json` | Abgleich ausführen, `exported_at` setzen, Liste liefern |

Der Kurzbefehl nutzt `POST` — nicht aus Formalismus, sondern weil der Aufruf einen Abgleich
auslöst und protokolliert wird; ein `GET` mit Nebenwirkung wäre genau der Fehler, den §5 vermeidet.
Authentifizierung über Header `X-API-Key`; `?key=` wird zusätzlich akzeptiert, weil sich das in
Kurzbefehlen leichter zusammenbauen lässt (L12).

Textformat, eine Zeile pro Position, ab M7 mit Gruppenüberschrift:

```
Spülmaschinentabs — 1 Packung
Klopapier — 10 Rollen
Kaffee — 2 Packungen
```

### Der Kurzbefehl (`docs/KURZBEFEHL.md`, entsteht in M4)

Schritte: *URL* → *Inhalte von URL abrufen* (Methode `POST`, Header `X-API-Key`) → *Text teilen*
an Zeilenumbrüchen → *An Notiz anhängen* auf eine feste Notiz „Einkauf“.

**Hier liegt das größte Restrisiko des Projekts, und es ist ein Apple-Risiko, kein Code-Risiko:**
Shortcuts hat keine offizielle Aktion, die eine Notiz *als Checkliste* erzeugt. Der gangbare Weg
ist eine dauerhaft vorhandene Notiz, deren letzter Block bereits eine Checkliste ist — angehängte
Zeilen führen diese Checkliste fort. Das ist verbreitete Praxis, aber von Apple nicht garantiert
und kann sich mit einer iOS-Version ändern. Ich kann es hier nicht verifizieren, deshalb steht es
als Risiko R1 in §10 mit zwei Rückfallpositionen. M4 gilt erst als fertig, wenn du den Kurzbefehl
auf deinem iPhone einmal durchgeführt hast — das ist der eine Punkt, den keine lokale Testsuite
abdecken kann.

---

## 7. Endpunkte

Oberfläche auf deutschen Pfaden (sie sind sichtbar und werden getippt), Schnittstelle auf
englischen.

| Methode | Pfad | Zweck | M |
| --- | --- | --- | --- |
| GET | `/` | Board, drei Spalten | 2 |
| GET | `/artikel/neu` · POST `/artikel` | Artikel anlegen (mit `opening`-Bewegung) | 2 |
| GET | `/artikel/{id}` | Detail: Stammdaten, QR, Verlauf | 2 |
| POST | `/artikel/{id}` | Stammdaten ändern | 2 |
| POST | `/artikel/{id}/inventur` | Bestand absolut setzen, mit `expected_stock` | 2 |
| POST | `/artikel/{id}/archivieren` · `/reaktivieren` | | 2 |
| GET | `/e/{token}` | **Entnahmeseite** — nur lesend | 3 |
| POST | `/e/{token}/entnahme` | Entnahme buchen, `303` → Ergebnis | 3 |
| GET | `/e/{token}/ok/{movement_id}` | Ergebnis mit Rückgängig-Button | 3 |
| POST | `/bewegungen/{id}/rueckgaengig` | Gegenbuchung im Undo-Fenster | 3 |
| GET | `/liste` | offene Liste zum Abhaken | 4 |
| POST | `/liste/erzeugen` | Abgleich, Liste anlegen falls nötig | 4 |
| POST | `/liste/{id}/zeilen/{line_id}/abhaken` · `/zuruecknehmen` | HTMX-Partial der Zeile | 4 |
| POST | `/liste/{id}/abschliessen` | offene Positionen verwerfen, Liste schließen | 4 |
| GET | `/api/shopping-list` | lesen, `text` oder `json`, API-Key | 4 |
| POST | `/api/shopping-list/export` | Abgleich + Export für den Kurzbefehl | 4 |
| GET | `/artikel/{id}/qr.svg` · `qr.png` | Einzel-QR | 5 |
| GET | `/etiketten` | Auswahl und Rasterwahl | 5 |
| GET | `/etiketten/druck` | druckoptimierte Bogenansicht | 5 |
| GET | `/etiketten/kalibrierung` | Maßstabskontrolle vor dem Druck | 5 |
| GET | `/healthz` | Bereitschaft **und** Invariantenprüfung `SUM(delta) == stock` | 0 |
| GET | `/kategorien` · `/laeden` (+ POST) | Taxonomie pflegen | 7 |
| GET | `/verlauf` · `/artikel/{id}/verlauf` | Journal, Verbrauchsrate, Reichweite | 8 |

---

## 8. Konfiguration

Alles aus `.env`, Vorlage als `.env.example` im Repo. Keine Geheimnisse in Git.

| Variable | Standard | Anmerkung |
| --- | --- | --- |
| `HOMEKANBAN_BASE_URL` | `http://raspberrypi.local:8181` | **steckt in jedem gedruckten QR-Code** — vor dem Etikettendruck festlegen |
| `HOMEKANBAN_PORT` | `8181` | muss frei sein, siehe A1 |
| `HOMEKANBAN_DB_PATH` | `/data/homekanban.db` | Volume |
| `HOMEKANBAN_API_KEY` | — | Pflicht; ohne Wert verweigert der Export-Endpunkt den Dienst |
| `HOMEKANBAN_UNDO_WINDOW_MINUTES` | `10` | |
| `HOMEKANBAN_LEAD_DAYS` | `7` | Vorlaufzeit für Schwellenvorschläge (M8) |
| `HOMEKANBAN_BACKUP_DIR` | `/data/backups` | (M9) |
| `HOMEKANBAN_BACKUP_KEEP` | `7d,4w` | (M9) |
| `TZ` | `Europe/Berlin` | nur Anzeige, Speicherung bleibt UTC (L9) |
| `LOG_LEVEL` | `info` | nach stdout, nicht auf die SD-Karte |

**Der Hostname statt der IP in `BASE_URL` ist wichtig:** Vergibt der Router dem Pi per DHCP eine
neue Adresse, wären sonst alle geklebten Etiketten Altpapier.

---

## 9. Meilensteinplan

Jeder Meilenstein ist ein Pull Request, ist einzeln nutzbar und lässt sich vorführen.

### M0 — Fundament und Entscheidungen

**Status:** erledigt.

**Ziel:** Ein startbarer, leerer Dienst im Container, mit funktionierender Werkzeugkette.
**Drin:** Projektstruktur nach §2, `pyproject.toml`, `ruff` (Format + Lint), `pytest`, `mypy` nur
auf `app/domain`, `config.py`, `db.py` mit PRAGMAs (`journal_mode=WAL`, `foreign_keys=ON`,
`synchronous=NORMAL`, `busy_timeout=5000`), Migrationsrunner, `/healthz`, Dockerfile und
`compose.yaml` (L11), `.env.example`, die vier ADRs zu L1/L2/L5 und L8.
**Draußen:** jede Fachlogik.
**Abhängigkeiten:** keine.
**Definition of Done:** `make check` läuft grün durch (statt wie heute zu überspringen);
`docker compose up` liefert `/healthz` mit `200`; die Hooks greifen; `make test` enthält mindestens
einen echten Test.
**Testfokus:** Migrationsrunner ist idempotent und läuft zweimal ohne Schaden.
**Artefakte:** lauffähiges Skelett, `docs/adr/0001`–`0004`.

### M1 — Domänenmodell und Persistenz

**Status:** erledigt.

**Ziel:** Die Rechenregeln des Haushalts stehen und sind bewiesen — ohne Oberfläche.
**Drin:** `0001_init.sql` mit allen sieben Tabellen aus §3 (inklusive `category_id`/`store_id`),
Repositories, `services/stock.py` (Entnahme, Zugang, Inventur, Rückgängig), `domain/quantities.py`,
`domain/status.py`.
**Draußen:** HTML, QR, Export.
**Abhängigkeiten:** M0.
**Definition of Done:** Alle Regeln aus §4 sind als Test abgedeckt; die Invariante
`SUM(delta) == stock` hält über zufällige Buchungsfolgen; ein Skript legt Beispieldaten an.
**Testfokus:** die vier Rundungsfälle aus §4, jeder Schwellenübergang in beiden Richtungen,
Inventur mit veraltetem `expected_stock`, Gegenbuchung, `CHECK`-Verletzungen.
**Artefakte:** Schema, getestete Domänenschicht.

### M2 — Board und Artikelpflege

**Ziel:** Der Haushalt ist im Browser erfassbar und sichtbar.
**Drin:** Board mit drei abgeleiteten Spalten, Anlegen/Ändern/Archivieren, Inventur aus der
Detailansicht, `base.html` und `app.css`, mitgeliefertes HTMX.
**Draußen:** QR-Erzeugung, Einkaufsliste.
**Abhängigkeiten:** M1.
**Definition of Done:** Auf einem iPhone im Hochformat bedienbar, Trefferflächen ≥ 44 px;
kein Netzwerkzugriff nach außen (im Browser-Netzwerkprotokoll geprüft); 60 Artikel rendern
spürbar sofort.
**Testfokus:** Endpunkttests je Route, Zuordnung Artikel → Spalte, Validierungsfehler werden
verständlich deutsch gemeldet.
**Artefakte:** bedienbare Oberfläche, ab hier lässt sich der Vorrat pflegen.

### M3 — QR-Entnahme-Flow

**Ziel:** Scannen und Buchen im Alltag, sicher gegen Fehlbedienung.
**Drin:** Tokenvergabe beim Anlegen, `/e/{token}`, Buchung per POST mit Idempotenzschlüssel,
`303`-Weiterleitung, Ergebnisseite mit Rückgängig, „Bestand korrigieren“ als Nebenweg.
**Draußen:** Etikettendruck (M5) — zum Testen genügt der Einzel-QR aus der Detailansicht.
**Abhängigkeiten:** M2.
**Definition of Done:** Zwei Taps von Scan bis Buchung; doppeltes Absenden bucht nachweislich
einmal; ein `GET` auf die Entnahmeseite verändert keinen Bestand; unbekanntes Token liefert eine
freundliche Seite, keinen Stacktrace.
**Testfokus:** Idempotenz bei zwei parallelen POSTs mit gleichem Schlüssel, Undo innerhalb und
nach Ablauf des Fensters, Bestand vor/nach `GET` unverändert, Token nicht erratbar.
**Artefakte:** der eigentliche Rückmeldeweg des Systems.

### M4 — Einkaufsliste und Apple-Notes-Export

**Ziel:** Vom Bedarf zur abhakbaren Liste im iPhone und zurück zum Bestand.
**Drin:** Abgleichlogik (§6), Listenansicht mit HTMX-Abhaken, abweichende Mengen, Abschließen,
`GET`- und `POST`-Schnittstelle mit API-Key, `docs/KURZBEFEHL.md`.
**Draußen:** Sortierung nach Laden (M7).
**Abhängigkeiten:** M1, M2.
**Definition of Done:** Der Kurzbefehl ist **auf dem iPhone durchgeführt** und die Notiz enthält
abhakbare Punkte; Abhaken bucht den Zugang; Abschließen einer halb erledigten Liste lässt die
offenen Artikel im Nachkaufen stehen; fehlender oder falscher API-Key liefert `401`.
**Testfokus:** Abgleich in allen vier Fällen (neu, entfallen, abgehakt bleibt, Menge neu
berechnet), Teilkauf nach Regel 5, zweiter Export ohne zweite Liste, Textformat zeichengenau.
**Artefakte:** der Nutzen, um den es dem Projekt geht.

### M5 — Etiketten

**Ziel:** Ein Bogen zum Ausdrucken, damit der Haushalt beklebt werden kann.
**Drin:** `segno`-Anbindung, Einzel-QR als SVG und PNG, Auswahlseite, Bogenansicht mit
Millimeter-Raster für gängige A4-Etiketten, Kalibrierseite mit 100-mm-Referenz.
**Draußen:** Etikettendrucker mit Rollenware.
**Abhängigkeiten:** M3.
**Definition of Done:** Ein echter Ausdruck ist maßhaltig (Kalibrierseite geprüft) und die Codes
sind vom geklebten Etikett aus 20 cm Entfernung scanbar; nur nicht archivierte Artikel erscheinen.
**Testfokus:** QR-Inhalt entspricht `BASE_URL` + Token, Umbruch auf mehrere Bögen, Auswahl leer.
**Artefakte:** Etikettenbögen, `ops/`-Hinweis zur Etikettengröße.

### M6 — Deployment auf dem Raspberry Pi

**Ziel:** Läuft dauerhaft neben „Hängt!“, startet nach Stromausfall selbst.
**Drin:** Härtung von Dockerfile und Compose (Nicht-Root, `restart: unless-stopped`,
`HEALTHCHECK`, Speicherlimit), Volume, Portprüfung auf dem Pi (`ss -ltnp`), Zugriff über
`.local`-Hostname, `ops/BETRIEB.md` (Start, Stopp, Update, Log lesen, Datenbank sichern, was tun
wenn nichts geht).
**Draußen:** Reverse Proxy, HTTPS, Zugriff von außen.
**Abhängigkeiten:** M0 (Container existiert schon), sinnvoll nach M4.
**Definition of Done:** Nach `reboot` des Pi ist die App ohne Handgriff erreichbar; „Hängt!“ läuft
unbeeinträchtigt weiter; ein zweites Haushaltsmitglied hat die App auf dem eigenen Handy geöffnet.
**Testfokus:** manuell nach Checkliste in `BETRIEB.md`; zwei Geräte buchen gleichzeitig ohne
`database is locked`.
**Artefakte:** Betriebshandbuch, laufende Installation.

> **Empfehlung zur Reihenfolge:** M6 ist bewusst klein gehalten, weil der Container ab M0 mitläuft.
> Sinnvoll ist ein früher Probelauf auf dem Pi bereits nach M3 — dann scannt der Haushalt echte
> Etiketten, während M4 entsteht, und die Bestandsdaten sind von Anfang an echt.

### M7 — Kategorien und Ladenzuordnung

**Ziel:** Die Liste folgt dem Weg durch den Laden.
**Drin:** Pflege von Kategorien und Läden mit Reihenfolge, Zuordnung im Artikel, Gruppierung im
Board, Gruppierung und Sortierung in Ansicht und Export.
**Abhängigkeiten:** M4. Die Datenfelder bestehen seit M1, deshalb ist hier kein Umbau nötig.
**Definition of Done:** Export gruppiert nach Laden, innerhalb nach Kategorie-Position; Artikel
ohne Zuordnung landen in „Sonstiges“ und verschwinden nicht.
**Testfokus:** Sortierstabilität, Artikel ohne Kategorie, Laden löschen mit zugeordneten Artikeln.

### M8 — Verbrauchshistorie und Prognose

**Ziel:** Das Journal beantwortet „reicht das noch?“ und schlägt bessere Schwellen vor.
**Drin:** Verbrauchsrate aus `withdrawal`-Bewegungen der letzten 90 Tage, Reichweite in Tagen,
Vorschlag `reorder_level = ceil(rate × LEAD_DAYS)` auf Kaufeinheit gerundet, Verlaufsansicht je
Artikel.
**Abhängigkeiten:** M3 (ohne Buchungen keine Daten).
**Umgang mit dünner Datenlage:** Unter drei Entnahmen oder unter 14 Tagen Historie wird **keine**
Zahl gezeigt, sondern „zu wenig Daten“. Vorschläge ändern **nie** selbsttätig einen Wert; sie
werden angezeigt und mit einem Tap übernommen. Gegenbuchungen und ihre Ursprünge fließen nicht in
die Rate ein, sonst zählt ein korrigierter Fehlscan doppelt.
**Definition of Done:** Ein Artikel mit zwei Entnahmen zeigt „zu wenig Daten“; ein Artikel mit
Historie zeigt eine plausible Reichweite; Übernehmen schreibt den Wert und ist im Journal
nachvollziehbar.
**Testfokus:** Rate bei Lücken, Rate bei genau einer Entnahme, Ausschluss zurückgenommener
Buchungen, Division durch Null.

### M9 — Backup und Restore

**Ziel:** Ein SD-Karten-Tod kostet Bastelzeit, keine Daten.
**Drin:** `ops/backup.py` über die SQLite-`.backup`-API (**kein** `cp` auf eine offene Datenbank —
das erzeugt im WAL-Modus stille Inkonsistenz), gzip, Aufbewahrung 7 täglich + 4 wöchentlich,
Auslösung per Host-Cron, Stammdaten-Export/-Import als JSON und CSV.
**Abhängigkeiten:** M1.
**Definition of Done:** Ein Restore ist **durchgeführt** worden — Backup auf einen leeren Container
zurückgespielt, Board zeigt denselben Stand; der Weg steht in `BETRIEB.md`; das Backup liegt
nachweislich nicht nur auf der SD-Karte.
**Testfokus:** Backup während laufender Schreibzugriffe ist lesbar, Aufbewahrungsregel löscht das
Richtige, Import lehnt kaputte Dateien ab, ohne bestehende Daten anzufassen.

---

## 10. Risiken

| # | Risiko | Auswirkung | Umgang |
| --- | --- | --- | --- |
| R1 | **Checklisten-Formatierung in Apple Notes** ist von Shortcuts nicht offiziell unterstützt (§6). | Der Export landet als Fließtext statt als abhakbare Punkte — der Kern des gewünschten Ablaufs. | Anhängen an eine Vorlagennotiz, deren letzter Block eine Checkliste ist. Rückfall 1: einmaliges manuelles „Als Checkliste formatieren“ pro Liste (ein Tap). Rückfall 2: parallel Export nach Apple Erinnerungen, wo Häkchen offiziell unterstützt sind — dieselbe Schnittstelle, nur ein anderer Kurzbefehl. In M4 zuerst zu verifizieren, bevor die Oberfläche darauf aufbaut. |
| R2 | **Doppeltes Abhaken:** In der Notiz wird im Laden abgehakt, gebucht wird aber in der App. | Doppelte Arbeit, und genau daran stirbt die Disziplin. | Auf `/liste` ein „Alles gekauft“-Button, der alle offenen Positionen in einem Zug bucht — dann kostet der Heimweg einen Tap. Die Notiz ist die Ansicht im Laden, die App die Buchung. **Offene Frage O1.** |
| R3 | **Bestandsdrift** durch nicht gescannte Entnahmen. | Die Liste wird unglaubwürdig, danach nutzt sie keiner mehr. | „Bestand korrigieren“ ist auf jeder Entnahmeseite erreichbar, nicht in einem Untermenü; M8 markiert unplausibel niedrigen Verbrauch; Etiketten kleben am Entnahmeort, nicht am Vorratsschrank. Vollständig lösen lässt sich das nicht — die Gegenmaßnahme ist, dass Korrigieren so billig ist wie Buchen. |
| R4 | **Kollision mit „Hängt!“** über Port, Hostname oder Speicher. | Im schlimmsten Fall steht die bestehende App. | Eigener Container, eigenes Volume, Port aus `.env` mit Prüfschritt in M6, Speicherlimit im Compose. Vor dem ersten Start zu klären (A1). |
| R5 | **SD-Karten-Ausfall.** | Totalverlust von Historie und Stammdaten. | WAL, `synchronous=NORMAL`, keine Logs auf die Karte, M9 mit geprüftem Restore, Backup-Ziel außerhalb des Pi. Empfehlung: Systemlaufwerk auf USB-SSD. |
| R6 | **`BASE_URL` ändert sich** nach dem Etikettendruck. | Alle geklebten QR-Codes zeigen ins Nichts. | Hostname statt IP (§8), `BASE_URL` als Pflichtentscheidung vor M5, in `BETRIEB.md` als „nicht ohne Neudruck ändern“ vermerkt. Erwägenswert: eine Weiterleitung, die alte Basis-URLs toleriert. |
| R7 | **Gleichzeitige Schreibzugriffe** auf SQLite. | `database is locked` mitten im Scan. | WAL, `busy_timeout=5000`, kurze Transaktionen, keine Transaktion über einen Render-Vorgang hinweg. In M6 mit zwei Geräten geprüft. |
| R8 | **Die App wird nach drei Wochen nicht mehr benutzt.** Das ist das eigentliche Projektrisiko. | Aufwand ohne Nutzen. | Zwei-Tap-Anspruch als Abnahmekriterium in M3, kein Login, früher Echtbetrieb ab M3 statt großer Fertigstellung, wenige Artikel zu Beginn (10–15 statt „alles“). |
| R9 | **Etikettenpflege:** neue Artikel, abgefallene Aufkleber. | Löcher im System, gerade bei selten gekauften Dingen. | Nachdruck einzelner Etiketten aus der Detailansicht, `qr_token` bleibt bei Umbenennung stabil, Reservebogen im Vorratsschrank. |

### Offene Fragen an dich

| # | Frage | Empfehlung |
| --- | --- | --- |
| O1 | Wenn du mit der Notiz im Laden abhakst — soll die App danach nur „Alles gekauft“ anbieten, oder willst du wirklich Position für Position bestätigen? | „Alles gekauft“ als großer Standardweg, Einzelabhaken für Abweichungen. Sonst ist der Heimweg zu teuer (R2). |
| O3 | Soll `HOMEKANBAN_LEAD_DAYS` global gelten oder pro Artikel? Klopapier hat eine andere Vorlaufzeit als Kaffee. | Erst global mit 7 Tagen; pro Artikel nur, wenn M8 zeigt, dass es nötig ist. |
| O4 | Wer soll Artikel anlegen dürfen — alle im Haushalt oder nur du? | Alle. Ohne Login ist die Alternative ohnehin nur eine Bitte, und Archivieren ist reversibel. |

**O2 — beantwortet:** Der Pi ist im Heimnetz unter der festen Adresse `192.168.0.15` erreichbar;
„Hängt!“ läuft aktuell **ohne** Reverse Proxy davor, ein Proxy ist im Projekt „Hängt!“ aber
vorgesehen und könnte später ergänzt werden. Damit ist A2 bestätigt: HomeKanban wird direkt über
`http://<host>:<port>` angesprochen, ohne Pfad- oder Subdomain-Präfix. Zwei Punkte bleiben in
M6 zu erledigen, unverändert zum bisherigen Plan:

- Mit `ss -ltnp` auf dem Pi prüfen, welcher Port von „Hängt!“ belegt ist, und `HOMEKANBAN_PORT`
  entsprechend frei wählen (A1) — der genaue Port von „Hängt!“ selbst ist ohne Belang, da
  HomeKanban einen eigenen Container mit eigenem Port bekommt.
- `HOMEKANBAN_BASE_URL` auf den mDNS-Hostnamen setzen (z. B. `raspberrypi.local`), **nicht** auf
  `192.168.0.15`. Reserviert der Router die IP nicht per DHCP fest, überlebt eine feste IP im
  QR-Code einen Neustart des Pi zwar, einen Tausch der Hardware aber nicht — der Hostname übersteht
  beides. Falls „Hängt!“ perspektivisch einen Reverse Proxy bekommt, ändert das nichts an
  HomeKanban, solange dessen eigener Port und Hostname unberührt bleiben (siehe R6).

---

## 11. Teststrategie

Es gibt keine CI. Die Absicherung hängt an den Hooks aus `.githooks/`: `pre-commit` prüft Format
und Lint, `pre-push` fährt `make check` (Lint, Typprüfung auf `app/domain`, alle Tests). Ein roter
Lauf bricht den Push ab; `--no-verify` ist keine Option.

| Ebene | Werkzeug | Was dort geprüft wird |
| --- | --- | --- |
| Domäne | `pytest`, tabellengetrieben | Rundung, Schwellen, Status, Prognose. Schnell, ohne Datenbank — hier liegt die höchste Testdichte. |
| Dienste | `pytest` mit temporärer SQLite-Datei, echte Migrationen | Transaktionsgrenzen, Journal-Invariante, Abgleich der Liste, Gegenbuchungen. |
| Endpunkte | `httpx` gegen die ASGI-App | Statuscodes, Weiterleitungen, Idempotenz, API-Key, „`GET` verändert nichts“. |
| HTML | dieselben Endpunkttests, leichte Zusicherungen | dass die entscheidenden Elemente da sind (Button „−1 entnommen“, Bestandsanzeige) — kein Abbild des Markups, das nur bremst. |
| Manuell | Checkliste je Meilenstein im PR | iPhone-Bedienung, echter Etikettendruck, Kurzbefehl, Pi-Neustart, Restore. |

**Fälle mit Testpflicht** — sie stehen so auch in `CLAUDE.md`:

1. Rundung der Nachkaufmenge auf die Kaufeinheit, inklusive der vier Fälle aus §4
2. Schwellenübergänge in beiden Richtungen, auch genau *auf* der Schwelle
3. Idempotenz beim Doppelscan und beim erneuten Absenden desselben Formulars
4. Rückgängig innerhalb und nach Ablauf des Fensters
5. Teilweises Abhaken einer Liste und der Rückfall nach NACHKAUFEN (Regel 5)
6. Inventur mit zwischenzeitlich verändertem Bestand
7. Invariante `SUM(movements.delta) == items.stock` über zufällige Buchungsfolgen
8. Migrationsrunner zweimal hintereinander

Kein Zielwert für Testabdeckung als Zahl. Die Regel ist: Jede Zeile in `app/domain/` ist getestet,
jeder Endpunkt hat mindestens einen Test, und für jeden gefundenen Fehler entsteht zuerst der Test.

---

## 12. Alltags-Szenarien, durchgespielt

**1 — Die letzte Rolle Klopapier.**
Zustand: `stock = 1`, `reorder_level = 1`, `target = 10`, `pack_size = 10`, Einheit „Rolle“.
Jemand nimmt die letzte Rolle, scannt das Etikett an der Schranktür, tippt „−1 entnommen“.
Gebucht wird `withdrawal delta = −1`, `stock_after = 0`. `0 <= 1` → **NACHKAUFEN**. Die
Ergebnisseite bestätigt: „Klopapier — Bestand 0. Steht auf der nächsten Einkaufsliste.“ Beim
nächsten Abgleich erscheint „Klopapier — 10 Rollen“ (`ceil((10−0)/10) × 10`). Zwei Taps, kein
Nachdenken.

**2 — Einkauf mit dem iPhone.**
Vor dem Losfahren: Kurzbefehl starten. Der Pi gleicht ab, setzt `exported_at`, liefert die Zeilen;
in Notes steht eine Checkliste. Im Laden wird dort abgehakt — offline, ohne WLAN, ohne die App.
Zu Hause: `/liste` öffnen, „Alles gekauft“ (O1). Für jede Position entsteht eine `restock`-Bewegung
mit `source = 'shopping_list'`, der Bestand geht auf `target_stock`, die Liste wird `done`. Beim
Kaffee gab es nur eine statt zwei Packungen: dort statt „Alles gekauft“ die Menge auf 1 korrigieren
— Bestand `+1`, weiter unter der Schwelle, also sofort wieder **NACHKAUFEN** und beim nächsten
Abgleich mit Restmenge dabei (Regel 5).

**3 — Jemand vergisst zu scannen.**
Das System glaubt an drei Packungen Spülmaschinentabs, im Schrank steht eine. Der Nächste sieht die
Lücke, scannt das Etikett und tippt „Bestand korrigieren“ → 1. Es entsteht `adjustment delta = −2`
mit dem Hinweis „Inventur“; liegt 1 unter der Schwelle, ist der Artikel unmittelbar in
**NACHKAUFEN**. Nichts muss aufgeräumt werden, das Journal bleibt widerspruchsfrei, und M8 kann
später zeigen: bei diesem Artikel weicht der gebuchte vom tatsächlichen Verbrauch ab.

**4 — Spontan mitgebracht.**
Jemand bringt ungefragt Kaffee mit. Etikett scannen → „Bestand korrigieren“ → 3. `adjustment`
mit `delta = +2`, Bestand über der Schwelle, Status **AUSREICHEND**. Stand der Kaffee auf der
offenen Liste, wird seine nicht abgehakte Position beim nächsten Abgleich verworfen — er
verschwindet also von selbst aus der Liste, ohne dass jemand daran denken muss.

---

## 13. Was dieser Plan nicht enthält

Kein Produktionscode — das war der Auftrag dieses Durchgangs. Ebenfalls bewusst außerhalb:
öffentlicher Zugriff, Benutzerkonten, Preise und Budget, Händler-Schnittstellen, EAN-Scan zum
Anlegen, native App, GitHub Actions. Und weiterhin **keine Lizenzfestlegung**.

Nächster Schritt ist M0 — sobald du die offenen Fragen aus §10 beantwortet hast, wobei nur O2 vor
M5 zwingend geklärt sein muss.
