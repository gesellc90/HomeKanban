"""App-Factory: Router-Registrierung und Lifespan (Migrationen, DB-Verbindung).

Noch ohne Fachlogik (siehe docs/PLAN.md §9, M0) — die Domänen-Router kommen ab M2/M3.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.db import connect
from app.migrate import migrate

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        connection = connect(settings.db_path)
        migrate(connection, MIGRATIONS_DIR)
        app.state.db = connection
        try:
            yield
        finally:
            connection.close()

    app = FastAPI(title="HomeKanban", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health_router)

    return app


app = create_app()
