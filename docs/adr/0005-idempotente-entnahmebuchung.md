# 0005 — Idempotente Entnahmebuchung über Unique-Index statt Vorab-Prüfung

- **Status:** teilweise ersetzt durch 0008 (nur der `threading.Lock` um `transaction()`; die
  Idempotenzprüfung selbst gilt unverändert)
- **Datum:** 2026-08-11
- **Meilenstein:** M3

## Kontext

Jede Buchung über `POST /e/{token}/entnahme` trägt einen beim Rendern der Seite erzeugten
`idempotency_key` als verstecktes Formularfeld (§5). Reload, Zurück-Button und hektisches
Doppeltippen senden denselben Schlüssel ein zweites Mal; R7 nennt zusätzlich echte Gleichzeitigkeit
durch mehrere Haushaltsmitglieder. Ein einzelner Vorab-`SELECT` auf
`movements.idempotency_key` genügt nicht: Zwei nahezu gleichzeitige Aufrufe können beide den
Vorab-`SELECT` mit „noch nicht vorhanden“ durchlaufen, bevor der erste seinen `INSERT` committet
hat (TOCTOU). Ohne Gegenmaßnahme würde der zweite `INSERT` schlicht am UNIQUE-Index scheitern und
als `sqlite3.IntegrityError` bis zur Web-Schicht durchschlagen — eine 500er-Seite, die genau die
Fehlbedienung nicht abfängt, die §5 ausdrücklich verlangt abzufangen.

Beim Nachbau des Zwei-Verbindungen-Falls (siehe `tests/services/test_stock.py::TestConcurrentWithdraw`)
zeigte sich zusätzlich ein latentes Problem in `app/db.py`: `BEGIN` (deferred) nimmt die
Schreibsperre erst bei der ersten schreibenden Anweisung, wodurch zwei echte Verbindungen bei
exakt gleichzeitigem Schreiben sofort `OperationalError: database is locked` statt eines von
`busy_timeout` abgefederten Wartens erhielten. Und ein einzelnes `sqlite3.Connection`-Objekt
(die App hält genau eine, siehe `app.state.db`) lässt pro Prozess nur eine offene Transaktion zu —
zwei Python-Threads, die durch FastAPIs Threadpool gleichzeitig in `transaction()` laufen, konnten
sich mit `OperationalError: cannot start a transaction within a transaction` gegenseitig aus dem
Weg räumen, ganz unabhängig vom Idempotenz-Schlüssel.

## Entscheidung

`services/stock.withdraw()` prüft optimistisch per Vorab-`SELECT` auf `idempotency_key` (spart im
Normalfall den zweiten Schreibversuch), fängt aber zusätzlich `sqlite3.IntegrityError` aus dem
`INSERT` ab und schlägt danach erneut auf `idempotency_key` nach. Nur wenn dieser zweite Nachschlag
tatsächlich eine Bewegung findet, gilt der Aufruf als Duplikat und liefert deren ID zurück; sonst
wird der `IntegrityError` weitergereicht (z. B. eine `CHECK`-Verletzung, die nichts mit Idempotenz
zu tun hat). Die eigentliche Garantie ist der UNIQUE-Index auf `movements.idempotency_key`
(seit M1), nicht der Vorab-`SELECT`.

Damit das im Ernstfall tatsächlich einen `IntegrityError` statt eines `OperationalError` liefert,
ändert `app/db.py`s `transaction()`-Kontextmanager zwei Dinge:

1. `BEGIN IMMEDIATE` statt `BEGIN` — die Schreibsperre wird sofort angefordert, `busy_timeout`
   greift dadurch zuverlässig, statt sofort mit „database is locked“ aufzugeben.
2. Ein `threading.Lock` um die gesamte Transaktion — serialisiert parallele Buchungen auf
   derselben Verbindung, statt sie mit „cannot start a transaction within a transaction“
   abzubrechen. Jede Transaktion ist kurz (eine Buchung), die Wartezeit unter dem Lock bleibt
   entsprechend klein.

## Alternativen

- **Nur der Vorab-`SELECT`, kein `try`/`except`:** Löst die Race Condition nicht (TOCTOU), siehe
  Kontext. Verworfen.
- **`INSERT OR IGNORE` statt `INSERT` + Fehlerbehandlung:** Verschluckt auch andere
  Integritätsverletzungen (etwa `CHECK (stock >= 0)`) stillschweigend — genau die Fälle, die §5
  stattdessen als verständliche deutsche Fehlermeldung sehen will. Verworfen.
- **Eigene `idempotency_keys`-Tabelle mit Sperre statt UNIQUE-Index auf `movements`:** Zusätzliche
  Tabelle und zusätzliche Schreiblast ohne Mehrwert gegenüber dem bereits seit M1 vorhandenen
  Index. Verworfen (L5: keine Komplexität ohne Gegenwert).
- **Verbindung pro Request statt einer geteilten `app.state.db`:** Würde das Lock-Problem
  strukturell umgehen, ist aber eine größere Änderung am Verbindungsmodell aus M0/M1 und gehört
  eher zur echten Mehrgeräte-Prüfung in M6 (R7: „In M6 mit zwei Geräten geprüft“) als in diesen
  Durchgang. Zurückgestellt — **umgesetzt in M6, siehe ADR 0008.**

## Konsequenzen

Ein zweites Absenden desselben Formulars — ob nacheinander oder echt gleichzeitig, über dieselbe
oder über zwei verschiedene Verbindungen — bucht nachweislich genau einmal (siehe
`tests/services/test_stock.py::TestWithdrawIdempotency`,
`tests/services/test_stock.py::TestConcurrentWithdraw`,
`tests/web/test_scan.py::TestConcurrentDoubleTap`).

**Nachtrag M6 (ADR 0008):** Der hier beschriebene `threading.Lock` um `transaction()` sicherte nur
die Transaktionen der einen geteilten `app.state.db`-Verbindung ab, nicht Lesezugriffe außerhalb
einer Transaktion — das blieb bis M6 ein offener Defekt (docs/PLAN.md §10, „Offener Defekt zu
R7“). ADR 0008 ersetzt die geteilte Verbindung durch eine Verbindung je Anfrage und den Lock
dadurch ersatzlos; die Idempotenzprüfung selbst (Vorab-`SELECT` + `IntegrityError`-Abfang auf dem
UNIQUE-Index) bleibt unverändert wie oben beschrieben.
