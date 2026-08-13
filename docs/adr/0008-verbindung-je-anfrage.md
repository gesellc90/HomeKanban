# 0008 — Verbindung je Anfrage statt geteilter `app.state.db`

- **Status:** entschieden
- **Datum:** 2026-08-13
- **Meilenstein:** M6

## Kontext

Bis M6 hielt die App **eine einzige** `sqlite3.Connection` in `app.state.db`, erzeugt beim Start
und über die gesamte Laufzeit von allen Anfragen gemeinsam benutzt. FastAPI führt synchrone
Endpoints in einem Threadpool aus — mehrere Haushaltsmitglieder buchen also aus verschiedenen
Threads auf demselben Verbindungsobjekt.

ADR 0005 sicherte davon nur die *Transaktionen* ab: `app/db.py::transaction()` nahm einen
prozessweiten `threading.Lock`, damit zwei Threads nicht gleichzeitig `BEGIN IMMEDIATE` auf
derselben Verbindung versuchen (`OperationalError: cannot start a transaction within a
transaction`). **Lesende Zugriffe außerhalb einer Transaktion blieben ungeschützt** — etwa der
Vorab-`SELECT` auf `idempotency_key` in `services/stock.py::withdraw`, oder jeder Lesezugriff beim
Rendern einer Seite. Trifft ein solcher Lesezugriff auf dieselbe Verbindung, während ein anderer
Thread mitten in einer Transaktion steckt, kann `sqlite3.InterfaceError: bad parameter or other API
misuse` auftreten — im Alltag eine 500er-Seite mitten im Scan, genau der Fall, den R7
(docs/PLAN.md §10) beschreibt.

`docs/PLAN.md` benannte den Defekt bereits unter „Offener Defekt zu R7“ und verwies ihn ausdrücklich
auf M6: „Sie gehört nach M6, wo R7 ohnehin mit zwei Geräten geprüft wird“. Reproduziert war er in
`tests/web/test_scan.py::TestConcurrentDoubleTap` — sporadisch, etwa einmal in zwölf Läufen auf
unverändertem Code. Die Definition of Done von M6 verlangt „zwei Geräte buchen gleichzeitig ohne
`database is locked`“; mit dem bestehenden Defekt war das nicht ehrlich abnehmbar.

## Entscheidung

**Eine Verbindung je Anfrage** statt einer geteilten. `app/deps.py::get_db` ist eine
FastAPI-Dependency (Generator), die für jede Anfrage über `app/db.py::connect()` eine eigene
Verbindung öffnet und sie am Ende der Anfrage wieder schließt:

```python
def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    connection = connect(request.app.state.settings.db_path)
    try:
        yield connection
    finally:
        connection.close()


DbConnection = Annotated[sqlite3.Connection, Depends(get_db)]
```

Alle 40 bisherigen Zugriffsstellen auf `request.app.state.db` in 11 Dateien (`app/main.py`,
`app/api/{export,health}.py`, `app/web/{board,history,items,labels,scan,shopping,stammdaten,
taxonomy}.py`) sind auf `connection: DbConnection` als Parameter umgestellt. `app/main.py`s
Lifespan hält keine Verbindung mehr über die Laufzeit — sie öffnet beim Start nur noch kurz eine
für die Migration und schließt sie sofort danach.

Getrennte Verbindungen räumen die `OperationalError`-Klasse aus ADR 0005 strukturell aus dem Weg:
Jede Verbindung hat ihren eigenen Transaktionszustand, „cannot start a transaction within a
transaction“ kann zwischen zwei Verbindungen nicht mehr auftreten. Gleichzeitige Schreibzugriffe
regelt SQLite selbst über WAL, `busy_timeout=5000` und `BEGIN IMMEDIATE` (unverändert in
`app/db.py::transaction()`) — der Weg, den ADR 0005 für den mehrprozessigen Fall ohnehin schon
beschrieb und den die Nebenläufigkeitstests mit echten, getrennten Verbindungen
(`tests/services/test_stock.py::TestConcurrentWithdraw`) zuverlässig bestehen. Der
`threading.Lock` aus ADR 0005 entfällt ersatzlos: Er serialisierte nur die Konkurrenz auf der einen
geteilten Verbindung, die es jetzt nicht mehr gibt.

`check_same_thread=False` bleibt in `connect()` bestehen — FastAPIs Threadpool bindet auch eine
Verbindung je Anfrage nicht zuverlässig an einen einzelnen OS-Thread: Öffnen (Dependency-Eintritt)
und Schließen (Dependency-Austritt) eines sync-Generators können über separate
`run_in_threadpool`-Aufrufe auf unterschiedlichen Threads laufen.

**ADR 0005 gilt als teilweise ersetzt:** Die dortige Entscheidung für den optimistischen
Vorab-`SELECT` mit nachträglichem `IntegrityError`-Abfang bei der Idempotenzprüfung bleibt
unverändert gültig — das ist unabhängig vom Verbindungsmodell. Ersetzt ist nur der dort
beschriebene `threading.Lock` um `transaction()`; die als „zurückgestellt“ notierte Alternative
„Verbindung pro Request statt einer geteilten `app.state.db`“ ist die hier getroffene Entscheidung.

## Alternativen

- **Thread-lokale Verbindung hinter einer Fabrik** (`threading.local()`, eine Verbindung je
  Threadpool-Thread statt je Anfrage): deutlich kleinerer Diff, dieselbe Trennung zwischen echten
  Threads. Verworfen, weil Verbindungen dann so lange leben wie die Threadpool-Threads selbst —
  eine über Stunden offene Verbindung ist ein WAL-Checkpoint-Risiko und schwerer zu testen als eine,
  deren Lebensdauer exakt an die Anfrage gebunden ist.
- **Alle Zugriffe unter den bestehenden Lock ziehen, auch lesende:** kleinster Diff, aber
  serialisiert damit auch das Rendern von Seiten ohne jeden Schreibzugriff. Bei fünf Personen
  praktisch belanglos, aber ein konzeptioneller Umweg um das eigentliche Problem (eine geteilte
  Verbindung) statt eine Lösung dafür. Verworfen, mit dem Nutzer in der M6-Fragerunde entschieden.
- **Nichts ändern, den Defekt als bekannte Einschränkung stehen lassen:** hätte die
  Nebenläufigkeitszeile der Definition of Done als ungeprüft statt bestanden geführt. Verworfen —
  M6 ist der Moment, in dem der Haushalt zum ersten Mal tatsächlich gleichzeitig scannt; ein
  Stacktrace an diesem Abend wiegt schwerer als der Diff.

## Konsequenzen

**Leichter:** Die `OperationalError`/`InterfaceError`-Klasse aus dem R7-Defekt ist strukturell
ausgeschlossen, nicht nur seltener gemacht. `TestConcurrentDoubleTap` läuft nach dieser Änderung
verlässlich grün (30 von 30 Läufen, siehe PR-Bericht). Jede Anfrage ist unabhängig — ein hängender
Request kann keine Verbindung für andere blockieren, anders als beim geteilten Lock.

**Schwerer:** Pro Anfrage entsteht eine neue SQLite-Verbindung (Dateiöffnen, PRAGMAs setzen). Bei
der erwarteten Last (bis zu fünf Personen, wenige Buchungen pro Tag, A4) ist das nicht messbar
relevant; SQLite-Verbindungsaufbau auf einer lokalen Datei ist im niedrigen Millisekundenbereich.
Der Diff selbst ist groß (40 Aufrufstellen in 11 Dateien plus alle betroffenen Tests), weil er
mechanisch jede Stelle betrifft, die bisher `request.app.state.db` gelesen hat.

**Neu bewertet würde die Entscheidung**, wenn eine Verbindung je Anfrage auf dem Pi messbar
langsamer wird als die geteilte Variante — dafür gibt es aktuell keinen Hinweis, und die manuelle
Zwei-Geräte-Prüfung aus `ops/BETRIEB.md` (Phase 10) ist die Gelegenheit, das am echten Pi zu sehen.
