# CLAUDE.md — HomeKanban

Arbeitsanweisungen für Claude Code in diesem Repository. Diese Datei hat Vorrang vor allgemeinen
Gewohnheiten. Widersprüche zwischen dieser Datei und einer konkreten Anweisung des Nutzers löst
immer der Nutzer auf — frage nach, statt zu raten.

## Was dieses Projekt ist

HomeKanban ist eine private Web-App auf einem Raspberry Pi im Heimnetz, parallel zur bestehenden
App „Hängt! – jeder Strich zählt“. Sie führt Alltagsverbrauchsmittel eines Haushalts nach einem
Kanban-Prinzip mit Mengenzählung, nimmt Entnahmen über QR-Codes am Vorratsort auf und exportiert
auf Anfrage eine Einkaufsliste, die ein Apple-Kurzbefehl als abhakbare Checkliste in Apple Notes
schreibt.

Fachliche und technische Grundlage: **`docs/PROJEKT-PROMPT.md`** (Anforderungen, gesetzter
Technologie-Rahmen, Meilensteine). Lies sie, bevor du inhaltlich arbeitest. Sobald `docs/PLAN.md`
existiert, ist sie die verbindliche Detailplanung.

## 1. Aktives Nachfragen (wichtigste Regel)

Rate nicht bei Entscheidungen, die dem Nutzer gehören.

- **Frag nach, bevor du baust**, wenn eine Unklarheit das Ergebnis wesentlich verändert:
  fachliche Regeln, Datenmodell-Semantik, UI-Abläufe, Betriebsdetails auf dem Pi, alles was mit
  „Hängt!“ oder dem iPhone zusammenspielt.
- **Bündele Fragen** zu einer Runde (maximal vier), stelle sie über `AskUserQuestion`, gib zu
  jeder Frage eine **Empfehlung mit einer Zeile Begründung** und mach Auswirkungen der Optionen
  klar.
- **Blockiere nicht unnötig:** Erledige zuerst alles, was von der Antwort unabhängig ist, und
  frage dann am passenden Punkt. Blockierendes Nachfragen ist nur richtig, wenn jede Annahme die
  Arbeit unbrauchbar machen könnte.
- **Annahmen sind sichtbar zu machen.** Wenn du ohne Antwort weiterarbeiten musst, schreibe die
  Annahme als solche in den Plan, den Commit oder die PR-Beschreibung — nicht nur in den Chat.
- **Frag nicht** nach Dingen, die in `docs/PROJEKT-PROMPT.md`, `docs/PLAN.md` oder im Code stehen,
  und nicht nach Konventionen mit offensichtlichem Standard. Erst nachsehen, dann fragen.
- Nachfragen ersetzt nicht das Liefern: Nach der Antwort wird der **volle** Umfang umgesetzt,
  nicht eine verkleinerte Variante.
- Bereits getroffene Entscheidungen (siehe Abschnitt 3) werden **nicht neu aufgerollt**, außer der
  Nutzer öffnet sie selbst.

## 2. Sprache

- **Kommunikation mit dem Nutzer: Deutsch.**
- **UI-Texte, Fehlermeldungen für Endnutzer und Dokumentation: Deutsch.**
- **Code, Bezeichner, Kommentare, Commit-Messages, PR-Titel: Englisch.**
- Domänenbegriffe werden im Code einheitlich englisch geschrieben. Glossar:
  Artikel → `item`, Bestand → `stock`, Mindestbestand → `reorder_level`, Sollbestand →
  `target_stock`, Kaufeinheit → `pack_size`, Entnahme → `withdrawal`, Zugang → `restock`,
  Korrektur → `adjustment`, Bewegung/Journal → `movement`/`ledger`, Einkaufsliste →
  `shopping_list`, Laden → `store`, Inventur → `inventory` (fachlicher Vorgang; die dabei
  geschriebene Bewegung bleibt vom `kind` her eine `adjustment`), Rückgängig → `undo`,
  Ausreichend → `ok`, Nachkaufen → `reorder`, Auf Liste → `on_list`, Archivieren → `archive`,
  Reaktivieren → `reactivate`, Scan/Entnahmeseite → `scan`, Zweitschlüssel gegen Doppelbuchung →
  `idempotency_key`, Zeitfenster fürs Rückgängigmachen → `undo_window` (Konfiguration:
  `undo_window_minutes`), Abgleich der Einkaufsliste → `reconciliation` (Funktion:
  `plan_reconciliation`), Position auf der Liste → `line` (`shopping_list_lines`), abgehakt →
  `checked` (Zeitpunkt: `checked_at`), verworfen/von der Liste genommen → `dropped`
  (`dropped_at`), vorgeschlagene Kaufmenge → `suggested_qty`, tatsächlich gekaufte Menge →
  `purchased_qty`, Kopie von Name und Einheit zum Erzeugungszeitpunkt → `snapshot`
  (`name_snapshot`, `unit_snapshot`), Einkauf abschließen → `complete`, Pluralform einer
  Einheit → `plural_unit`.
  Erweitere das Glossar, wenn ein neuer Begriff dazukommt.

## 3. Gesetzte Entscheidungen

Diese Punkte sind mit dem Nutzer abgestimmt und stehen fest:

- **Stack:** Python + FastAPI, serverseitige Templates + HTMX, SQLite.
- **Betrieb:** Docker Compose auf dem Raspberry Pi, eigener Container, eigener Port, eigenes
  Volume für die Datenbankdatei. Kollision mit „Hängt!“ ist ausgeschlossen zu halten.
- **Zugriff:** nur Heimnetz, kein Login, keine Benutzerverwaltung.
- **Kanban:** Mengenzählung mit Mindest- und Sollbestand; Status ist **abgeleitet**, nicht
  händisch gepflegt; alle Änderungen laufen über ein append-only Bewegungsjournal.
- **QR:** ein Code je Artikel, stabiles Zufallstoken; der Scan öffnet nur die Seite, gebucht wird
  erst durch bestätigenden POST.
- **Einkaufsliste:** Export über einen Endpoint, den ein Apple-Kurzbefehl abruft; Abhaken in der
  App bucht den Zugang ein.
- **Etiketten:** Einzel-QR je Artikel plus Sammel-PDF mit Etikettenbögen.
- **Checks laufen ausschließlich lokal** (siehe Abschnitt 5).
- **Keine Lizenz.** Lege **keine** `LICENSE` an und trage keine Lizenzangabe in Metadaten ein,
  solange der Nutzer sich nicht entschieden hat.

## 4. Grenzen, die nicht ohne Rückfrage überschritten werden

- **Keine GitHub Actions**, keine Workflow-Dateien, keine Cloud-CI. Wenn dir etwas fehlt, das nach
  CI verlangt, löse es als lokales Make-Target oder Git-Hook.
- **Keine externen CDNs, Fonts, Tracker oder Cloud-Dienste.** Alle Assets liegen im Repo und
  werden lokal ausgeliefert — die App muss ohne Internetverbindung vollständig funktionieren.
- **Keine Apple-Zugangsdaten und keine Secrets im Repo.** Der Pi liefert nur Daten aus; das iPhone
  holt sie ab. Konfiguration kommt aus `.env`, das nie eingecheckt wird.
- **Keine Telemetrie, keine Datenübertragung nach außen.** Es sind Haushaltsdaten einer Familie.
- **Kein Feature-Creep.** Arbeite im Umfang des aktuellen Meilensteins. Gute Ideen für später
  gehören als Notiz in den Plan, nicht in den Diff.
- **Keine schweren Abhängigkeiten.** Zielhardware ist ein Raspberry Pi: sparsam bei Paketen,
  kein aufwendiger Frontend-Build, Rücksicht auf Schreibzugriffe auf die SD-Karte. Jede neue
  Abhängigkeit wird im PR kurz begründet.
- **Keine destruktiven Datenoperationen ohne Sicherung.** Migrationen, die Spalten oder Tabellen
  entfernen, brauchen einen Backup-Schritt und einen beschriebenen Rückweg. Vor dem Überschreiben
  oder Löschen einer Datei erst hineinsehen.

## 5. Tests und Checks — nur lokal

Es gibt bewusst keine CI. Die Qualitätssicherung hängt an lokalen Hooks:

- `make setup` — Umgebung und Abhängigkeiten
- `make hooks` — Git-Hooks aktivieren (setzt `core.hooksPath` auf `.githooks/`)
- `make fmt` / `make lint` / `make test` — einzeln
- `make check` — alles, was vor einem Push laufen muss

Regeln:

- **Der `pre-commit`-Hook** hält Format und Lint auf den geänderten Dateien.
- **Der `pre-push`-Hook** führt die vollständigen Tests aus. Ein roter Push wird abgebrochen.
- **Hooks werden nicht umgangen.** `--no-verify` ist keine Lösung. Schlägt ein Check fehl, wird
  die Ursache behoben — oder der Nutzer entscheidet.
- **Nichts wird als fertig gemeldet, ohne dass die Checks liefen.** Sag klar, was du ausgeführt
  hast und was dabei herauskam. Schlagen Tests fehl, benenne sie mit Ausgabe, statt es zu
  glätten. Was du nicht prüfen konntest (z. B. echtes Verhalten auf dem Pi oder der iOS-Kurzbefehl),
  benenne als ungeprüft.
- **Testpflicht** für: Rundung der Nachkaufmenge auf die Kaufeinheit, Schwellenübergänge des
  Status, Idempotenz beim Doppelscan, Undo-Fenster, Teil-Abhaken einer Einkaufsliste,
  Bestandskorrekturen.

## 6. Git-Konventionen

- Entwicklung findet auf Feature-Branches statt, **nie direkt auf `main`**.
- Branch-Namen: `feature/…`, `fix/…`, `docs/…`, `chore/…` — oder der vom Nutzer vorgegebene Branch.
- **Conventional Commits** in Englisch, ein Commit pro logischer Änderung, aussagekräftige
  Beschreibung statt „update“.
- **Push nur auf den Branch, den der Nutzer benannt hat.** Kein Push auf andere Branches ohne
  ausdrückliche Erlaubnis.
- **Pull Requests nur auf ausdrückliche Bitte.** Wenn einer erstellt wird, folge
  `.github/pull_request_template.md` und dokumentiere, welche lokalen Checks gelaufen sind.
- Ein Meilenstein aus dem Plan entspricht in der Regel einem PR.

## 7. Umgang mit dem Plan

- `docs/PROJEKT-PROMPT.md` beschreibt Anforderungen und Rahmen und ändert sich nur, wenn der
  Nutzer die Anforderungen ändert.
- `docs/PLAN.md` ist die Detailplanung und wird **mitgepflegt**: Weicht die Umsetzung vom Plan ab,
  wird der Plan im selben PR nachgezogen — ein Plan, der der Realität widerspricht, ist
  schlimmer als keiner.
- Technische Entscheidungen mit Tragweite werden als kurzes ADR unter `docs/adr/` festgehalten
  (Kontext, Entscheidung, Alternativen, Konsequenz). Kurz halten: eine Seite reicht.
- Beim Abschluss eines Meilensteins den Status im Plan aktualisieren.

## 8. Alltagstauglichkeit als Entwurfsmaßstab

Diese App wird nur benutzt, wenn Buchen schneller geht als es zu lassen:

- Der Weg von „QR gescannt“ bis „gebucht“ soll **zwei Taps** nicht überschreiten.
- Mobile-first ist keine Option, sondern der Hauptfall — bedienbar mit einer Hand, große
  Trefferflächen, lesbar bei schlechtem Licht im Vorratsschrank.
- Rechne mit Fehlbedienung: Doppelscans, Reloads, verlorene Verbindung mitten im Vorgang,
  vergessene Scans. Nichts davon darf Daten unrettbar verfälschen; für alles gibt es einen
  Korrekturweg.
- Rechne mit mehreren Personen im Haushalt, die gleichzeitig scannen.
