"""Verbindungsaufbau und Transaktions-Kontextmanager für SQLite.

Die PRAGMAs setzen die in docs/PLAN.md L1/M0 festgelegten Betriebsparameter für den Pi:
WAL-Journal, Fremdschlüssel an, `synchronous=NORMAL` als Kompromiss zwischen Haltbarkeit und
SD-Karten-Schreiblast, und ein Busy-Timeout gegen `database is locked` bei gleichzeitigen
Schreibzugriffen mehrerer Haushaltsmitglieder (R7).

Seit ADR 0008 (M6) hält die App keine geteilte Verbindung mehr in `app.state.db` (ADR 0005) —
`app.deps.get_db` öffnet über `connect()` eine eigene Verbindung je Anfrage und schließt sie
danach. Gleichzeitige Schreibzugriffe mehrerer Verbindungen regelt SQLite selbst über WAL,
`busy_timeout` und `BEGIN IMMEDIATE`; ein zusätzlicher Python-Lock ist dafür nicht mehr nötig.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def connect(db_path: Path | str) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: FastAPIs Dependency-Generatoren (app/deps.py::get_db) laufen über
    # anyios Threadpool, der Erzeugen, Nutzen und Schließen derselben Verbindung nicht an einen
    # einzelnen OS-Thread bindet — auch nicht bei einer Verbindung je Anfrage (ADR 0008). sqlite3
    # ist im Standard-Build serialisiert threadsicher.
    connection = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Rahmt mehrere `execute()`-Aufrufe in einer Transaktion.

    Nicht für `executescript()` geeignet — siehe app/migrate.py, das dafür eine eigene,
    in sich abgeschlossene Transaktionsführung braucht.

    `BEGIN IMMEDIATE` statt `BEGIN` (deferred) nimmt die Schreibsperre sofort, statt sie erst bei
    der ersten schreibenden Anweisung anzufordern. Ohne das hat sich `busy_timeout` bei zwei
    tatsächlich gleichzeitigen Verbindungen (siehe tests/services/test_stock.py, Idempotenz-Test
    mit zwei Threads) nicht wie dokumentiert verhalten: statt auf die kurze erste Transaktion zu
    warten, kam sofort ein "database is locked".
    """
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
