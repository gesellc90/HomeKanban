# Planungs-Prompt: HomeKanban

> **Zweck dieser Datei:** Der folgende Block ist ein fertiger Prompt, den du (unverändert oder
> angepasst) an Claude Code gibst, um die Projektplanung für HomeKanban zu erstellen.
> Er enthält alle bereits getroffenen Entscheidungen, den gesetzten Technologie-Rahmen und die
> Meilenstein-Struktur. Der Prompt fordert ausdrücklich **einen Plan, keine Implementierung**.
>
> Alles ab der Trennlinie ist der Prompt.

---

## ROLLE

Du bist Software-Architekt und Tech-Lead für ein privates Heim-Automatisierungsprojekt.
Deine Aufgabe in diesem Durchgang ist **ausschließlich Planung**. Schreibe **keinen
Produktionscode**, erstelle keine Module, keine Migrationen, keine Templates. Ergebnis sind
Planungsdokumente.

## PROJEKTZIEL

Eine Web-App namens **HomeKanban**, die auf einem Raspberry Pi im Heimnetz läuft — parallel zur
bereits dort betriebenen Web-App „Hängt! – jeder Strich zählt“. Sie verwaltet
**Alltagsverbrauchsmittel eines Haushalts** (z. B. Spülmaschinentabs, Klopapier, Kaffee,
Zahnpasta) nach einem **Kanban-Prinzip mit Mengenzählung** und erzeugt auf Anfrage eine
**Einkaufsliste**, die als abhakbare Checkliste in **Apple Notes** landet.

Rückmeldungen über Verbrauch erfolgen **über 2D-Codes (QR)**, die am Vorratsort kleben. Ein Scan
öffnet die artikelspezifische Seite, auf der die Entnahme **noch bestätigt werden muss** — ein
Scan allein bucht nichts.

## FACHLICHE ANFORDERUNGEN

### 1. Artikelstamm

Jeder Verbrauchsartikel führt mindestens:

- Name, optionale Notiz, Kategorie, Einkaufsort/Laden
- Einheit (Stück, Packung, Rolle, Flasche, kg, l …)
- **Aktueller Bestand** (Zahl, darf im Plan auch dezimal sein — begründen)
- **Mindestbestand** (Meldeschwelle)
- **Sollbestand** (Zielbestand nach dem Einkauf)
- **Verpackungs-/Kaufeinheit** (z. B. „6er-Pack“) für die Rundung der Nachkaufmenge
- Aktiv/archiviert
- Ein **stabiles, zufälliges QR-Token** (nicht die Datenbank-ID), damit gedruckte Etiketten
  Umbenennungen und ID-Änderungen überleben und nicht erratbar sind

### 2. Kanban mit Mengenzählung

- Der **Kanban-Status ist abgeleitet**, nicht händisch gepflegt. Er ergibt sich aus Bestand,
  Mindestbestand und der Zugehörigkeit zu einer offenen Einkaufsliste.
- Vorgeschlagene Spalten (im Plan schärfen): **Ausreichend → Nachkaufen → Auf Einkaufsliste**.
- Unterschreitet der Bestand den Mindestbestand, erscheint der Artikel automatisch in
  „Nachkaufen“ und damit in der nächsten Einkaufsliste.
- **Nachkaufmenge** = Sollbestand − aktueller Bestand, aufgerundet auf die Kaufeinheit.
- Alle Bestandsänderungen laufen über ein **Bewegungsjournal** (append-only Ledger) mit Typ
  (Entnahme, Zugang, Korrektur, Inventur), Menge, Zeitpunkt und Quelle (QR-Scan, Board,
  Einkaufsliste). Der Bestand ist damit jederzeit erklärbar und Grundlage für die spätere
  Verbrauchsprognose. Ob der Bestand materialisiert oder aus dem Journal berechnet wird, ist eine
  im Plan zu treffende und zu begründende Entscheidung.

### 3. QR-Flow (Entnahme)

- QR-Code kodiert eine URL auf die **artikelspezifische Entnahmeseite**.
- Der Aufruf der Seite ist **rein lesend** — eine Buchung passiert erst durch eine bestätigende
  Aktion (POST). Berücksichtige, dass Kamera-Apps, Messenger und Browser URLs vorab laden können;
  ein GET darf nie einen Bestand verändern.
- Die Seite zeigt Artikelname, aktuellen Bestand und Status, und bietet: „−1 entnommen“,
  „−N entnommen“ und eine direkte Bestandskorrektur.
- Nach der Buchung: Bestätigungsseite mit **Undo** innerhalb eines kurzen Zeitfensters.
- **Doppelbuchungen** durch Reload, Zurück-Button oder Mehrfachscan müssen verhindert werden
  (Idempotenz-Konzept ist Teil des Plans).
- Der Flow muss auf dem Smartphone mit einer Hand und in wenigen Sekunden bedienbar sein.

### 4. Einkaufsliste & Apple-Notes-Export

- Auf Anfrage („Einkaufsliste erzeugen“) entsteht aus allen Artikeln in „Nachkaufen“ eine
  Einkaufsliste mit Positionen (Artikel, vorgeschlagene Menge, Einheit).
- Der Export erfolgt über einen **Endpoint, den ein Apple-Kurzbefehl (iOS Shortcut) abruft**
  (Text- und JSON-Format). Der Kurzbefehl erzeugt in Apple Notes eine Notiz mit **einzelnen
  Punkten zum Abhaken**. Auf dem Pi liegen **keine Apple-Zugangsdaten** — der Pi liefert nur Daten
  aus.
- Der Endpoint wird über einen statischen, konfigurierbaren API-Key geschützt (auch wenn die App
  nur im LAN erreichbar ist).
- **Abhaken in der App bucht ein:** Wird eine Position in der App-Ansicht der offenen
  Einkaufsliste abgehakt, wird die Nachkaufmenge als Zugang gebucht und der Bestand auf den
  Sollbestand gesetzt. Abweichende Mengen („nur 1 statt 2 gekauft“) müssen erfassbar sein.
- Plane, was mit einer Einkaufsliste passiert, die nur teilweise abgehakt wurde, und was bei einer
  zweiten Exportanfrage vor Abschluss der ersten Liste geschieht.
- Der Plan muss den **Kurzbefehl selbst beschreiben** (Schritte, Endpoint, Header, Aufbau der
  Notiz) — er ist Teil des Liefergegenstands, auch wenn er nicht im Repo ausführbar ist.

### 5. Etiketten

- **Einzel-QR** je Artikel in der Detailansicht (Anzeige + PNG-Download) für Nachdrucke.
- **Sammel-PDF** mit Etikettenbögen (QR + Artikelname, gängiges A4-Raster) für die
  Erstbeklebung des Haushalts.

## TECHNOLOGIE-RAHMEN (gesetzt — nicht neu zur Diskussion stellen)

| Bereich | Entscheidung |
| --- | --- |
| Sprache/Framework | **Python + FastAPI** |
| Frontend | **Serverseitig gerenderte Templates + HTMX**, mobile-first, keine SPA |
| Assets | **lokal ausgeliefert (vendored)** — keine CDNs, keine externen Fonts; die App muss ohne Internet funktionieren |
| Datenbank | **SQLite** (Datei auf einem Volume) |
| Betrieb | **Docker Compose** auf dem Raspberry Pi, eigener Container, eigener Port, eigenes Volume |
| Zugriff | **nur Heimnetz, kein Login** (z. B. `http://<pi>:<port>`) |
| Tests/Checks | **ausschließlich lokal** über Git-Hooks und Make-Targets — **keine GitHub Actions** |
| UI-Sprache | Deutsch |
| Code/Commits | Englisch (Conventional Commits) |

Im Plan zu **entscheiden und zu begründen** (jeweils kurz, mit Alternative):

- Migrationsweg für das SQLite-Schema (Tool vs. schlichte SQL-Skripte)
- ORM/Query-Layer vs. direktes SQL
- Bibliotheken für QR-Erzeugung und PDF-Etiketten
- Test-Stack (Runner, HTTP-Client für Endpoint-Tests) und Lint/Format-Tooling
- Zeitzonen- und Zeitstempel-Strategie im Bewegungsjournal
- Port-Wahl ohne Kollision mit „Hängt!“ inklusive Prüfschritt auf dem Pi
- Ob und wie das Board Drag & Drop bekommt oder rein über Buttons/Formulare arbeitet
- Umgang mit gleichzeitiger Nutzung durch mehrere Haushaltsmitglieder (letzter Schreibzugriff
  gewinnt vs. Konflikterkennung)

## NICHT-ZIELE (bewusst außen vor)

- Kein öffentlicher Internet-Zugang, kein Multi-Haushalt-Mandantenmodell, keine Benutzerkonten
- Keine Preis-/Budgetverwaltung, keine Anbindung an Händler-APIs oder Lieferdienste
- Keine native iOS-App
- Keine Serverseitige Anmeldung an Apple-Diensten
- Kein Barcode-/EAN-Scan zum Anlegen von Artikeln (ausdrücklich zurückgestellt)
- Keine GitHub Actions oder sonstige Cloud-CI
- **Keine Lizenzfestlegung** — es wird bewusst noch keine `LICENSE` angelegt

## MEILENSTEINE

Plane die folgenden Meilensteine durch. Jeder Meilenstein braucht: **Ziel in einem Satz**,
**Umfang (was rein, was raus)**, **Abhängigkeiten**, **Definition of Done**, **Testfokus** und
**erwartete Artefakte**. Halte die Meilensteine so klein, dass jeder einzeln nutzbar bzw.
demonstrierbar ist, und schneide sie so, dass jeweils ein Pull Request daraus wird.

- **M0 — Fundament & Entscheidungen**
  Projektstruktur, Abhängigkeitsverwaltung, Lint/Format/Test-Tooling, lokale Git-Hooks,
  Konfiguration über `.env`, „Hello World“-Endpoint mit Healthcheck. Die oben offenen technischen
  Entscheidungen werden hier als kurze ADRs festgehalten.

- **M1 — Domänenmodell & Persistenz**
  Schema für Artikel, Bewegungsjournal, Einkaufsliste; Migrationsweg; Bestands- und
  Statuslogik (Meldeschwelle, Nachkaufmenge, Rundung auf Kaufeinheit) als testbare Domänenschicht
  ohne UI. Höchste Testdichte des Projekts.

- **M2 — Kanban-Board & Artikelpflege**
  Board-Ansicht mit abgeleiteten Spalten, Artikel anlegen/bearbeiten/archivieren, manuelle
  Bestandskorrektur, mobile Bedienung.

- **M3 — QR-Entnahme-Flow**
  Token-Vergabe, Entnahmeseite, Bestätigung per POST, Idempotenz, Undo-Fenster, Absicherung gegen
  vorausgeladene URLs.

- **M4 — Einkaufsliste & Apple-Notes-Export**
  Listenerzeugung, Abhaken mit automatischer Zugangsbuchung, abweichende Mengen, Export-Endpoint
  (Text/JSON) mit API-Key, Beschreibung und Test des iOS-Kurzbefehls.

- **M5 — Etiketten**
  Einzel-QR mit PNG-Download und Sammel-PDF für Etikettenbögen.

- **M6 — Deployment auf dem Raspberry Pi**
  Dockerfile und Compose-Setup (ARM-taugliches Base-Image), Volume für die Datenbank, Portwahl
  ohne Kollision mit „Hängt!“, Autostart, Zugriff über Hostname im LAN, kurzes Betriebshandbuch.
  Ab hier ist die App im Alltag nutzbar — dieser Meilenstein darf nicht nach hinten rutschen.

- **M7 — Kategorien & Ladenzuordnung**
  Kategorien und Einkaufsorte pflegen, Board gruppieren, exportierte Liste nach Laden bzw.
  Supermarkt-Abteilung sortieren. (Hängt an M4; wenn die Sortierung den Export später umbauen
  würde, schlage vor, das Datenfeld schon in M1 anzulegen.)

- **M8 — Verbrauchshistorie & Prognose**
  Auswertung des Bewegungsjournals: Verbrauchsrate pro Artikel, Reichweite in Tagen, Vorschläge
  für Mindest- und Sollbestand. Beschreibe, wie mit dünner Datenlage in den ersten Wochen
  umgegangen wird.

- **M9 — Backup & Restore**
  Automatische SQLite-Backups auf dem Pi (konsistent, nicht bei laufendem Schreibzugriff kopiert),
  Aufbewahrungsregel, Export/Import der Stammdaten als JSON/CSV, **getesteter**
  Wiederherstellungsweg.

## ERWARTETE AUSGABE

Erstelle als Planungsergebnis:

1. **`docs/PLAN.md`** — Gesamtplan: Architekturüberblick (Komponenten und ihr Zusammenspiel),
   Datenmodell (Tabellen, Felder, Beziehungen, Indizes), Zustandsmodell des Kanban mit den
   Übergangsregeln, Endpoint-Liste (Methode, Pfad, Zweck, wer ruft es auf), Verzeichnisstruktur,
   Konfigurationswerte.
2. **Meilensteinplan** mit den oben genannten Angaben je Meilenstein und einer klaren Reihenfolge.
3. **Teststrategie** — was auf Domänenebene, was auf Endpoint-Ebene, was manuell auf dem Gerät
   geprüft wird; wie die Checks lokal in Hooks und Make-Targets hängen; welche Fälle unbedingt
   Tests brauchen (Rundung der Nachkaufmenge, Schwellenübergänge, Idempotenz beim Doppelscan,
   Undo, Teil-Abhaken einer Liste).
4. **Risiken und offene Fragen** — je Punkt mit Auswirkung und Vorschlag zum Umgang. Erwarte
   mindestens: Kurzbefehl-Zuverlässigkeit, Etikettenpflege im Alltag, Bestandsdrift durch nicht
   gescannte Entnahmen, Kollision mit „Hängt!“, SD-Karten-Ausfall auf dem Pi.
5. **Alltags-Szenarien als Durchspielen** — mindestens: letzte Rolle Klopapier entnommen; Einkauf
   mit dem iPhone im Laden; jemand vergisst zu scannen; ein Artikel wird ohne Liste gekauft.

## ARBEITSWEISE

- Halte dich an `CLAUDE.md` in diesem Repository.
- **Frage aktiv nach**, sobald eine Entscheidung das Ergebnis wesentlich verändert und nicht
  aus dieser Beschreibung ableitbar ist. Rate nicht. Bündele Fragen, gib jeweils eine Empfehlung
  mit Begründung, und arbeite in der Zwischenzeit an allem weiter, was von der Antwort unabhängig
  ist.
- Wo du eine Annahme triffst, schreibe sie sichtbar als Annahme in den Plan.
- Beziehe die Belastbarkeit eines Raspberry Pi ein: sparsame Abhängigkeiten, keine schweren
  Build-Ketten, Rücksicht auf Schreibzugriffe auf die SD-Karte.
- Optimiere den Entwurf auf **Alltagstauglichkeit**: Wenn eine Buchung mehr als wenige Sekunden
  oder mehr als zwei Taps kostet, wird sie im echten Haushalt nicht gemacht — und der Bestand
  wird wertlos.
- **Kein Produktionscode in diesem Durchgang.** Schemaskizzen, Endpoint-Tabellen und
  Beispiel-Payloads in der Planung sind erwünscht; fertige Module sind es nicht.
- Lege keine `LICENSE` an und richte keine GitHub Actions ein.
