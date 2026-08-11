"""Verbindungsaufbau und Transaktions-Kontextmanager für SQLite.

Die PRAGMAs setzen die in docs/PLAN.md L1/M0 festgelegten Betriebsparameter für den Pi:
WAL-Journal, Fremdschlüssel an, `synchronous=NORMAL` als Kompromiss zwischen Haltbarkeit und
SD-Karten-Schreiblast, und ein Busy-Timeout gegen `database is locked` bei gleichzeitigen
Schreibzugriffen mehrerer Haushaltsmitglieder (R7).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


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
    """
    connection.execute("BEGIN")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
