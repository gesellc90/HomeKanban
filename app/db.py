"""Verbindungsaufbau und Transaktions-Kontextmanager für SQLite.

Die PRAGMAs setzen die in docs/PLAN.md L1/M0 festgelegten Betriebsparameter für den Pi:
WAL-Journal, Fremdschlüssel an, `synchronous=NORMAL` als Kompromiss zwischen Haltbarkeit und
SD-Karten-Schreiblast, und ein Busy-Timeout gegen `database is locked` bei gleichzeitigen
Schreibzugriffen mehrerer Haushaltsmitglieder (R7).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Serialisiert Transaktionen auf derselben Verbindung (R7, docs/PLAN.md §5/M3): FastAPI führt
# synchrone Endpoints in einem Threadpool aus, mehrere Haushaltsmitglieder können also gleichzeitig
# buchen — aber ein einzelnes sqlite3.Connection-Objekt lässt pro Prozess nur eine offene
# Transaktion zu. Ohne diesen Lock würde ein zweiter Thread, der während der ersten Transaktion
# startet, mit "OperationalError: cannot start a transaction within a transaction" abbrechen,
# statt korrekt auf den (kurzen) ersten Schreibzugriff zu warten. Jede Transaktion ist kurz
# (eine Buchung), daher bleibt die Wartezeit unter dem Lock gering.
_write_lock = threading.Lock()


def connect(db_path: Path | str) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: FastAPI führt synchrone Endpoints in einem Threadpool aus, während
    # die Verbindung beim App-Start in einem anderen (Lifespan-)Thread erzeugt wird. sqlite3 ist im
    # Standard-Build serialisiert threadsicher; kurze Transaktionen und busy_timeout federn
    # gleichzeitige Zugriffe mehrerer Haushaltsmitglieder ab (docs/PLAN.md R7).
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
    with _write_lock:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
