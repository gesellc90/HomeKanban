"""FastAPI-Dependencies. Siehe ADR 0008 (docs/adr/0008-verbindung-je-anfrage.md).

Bis M6 hielt die App eine einzige, geteilte `sqlite3.Connection` in `app.state.db` (ADR 0005).
`get_db` ersetzt das durch eine Verbindung je Anfrage: SQLite regelt Gleichzeitigkeit zwischen
getrennten Verbindungen selbst über WAL, `busy_timeout` und `BEGIN IMMEDIATE`
(`app/db.py::transaction`), ohne einen zusätzlichen Python-Lock.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from app.db import connect


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """Öffnet eine Verbindung für die Dauer dieser Anfrage und schließt sie danach wieder."""
    connection = connect(request.app.state.settings.db_path)
    try:
        yield connection
    finally:
        connection.close()


# Annotated-Form statt `connection: DbConnection` an jeder Route: ruffs
# B008 (kein Funktionsaufruf im Parameter-Default) kennt FastAPIs eigene Ausnahme dafür nicht, und
# ein Lint-Unterdrücken an 20 Stellen wäre schlimmer als dieser eine Alias.
DbConnection = Annotated[sqlite3.Connection, Depends(get_db)]
