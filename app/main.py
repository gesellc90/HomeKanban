"""App-Factory: Router-Registrierung und Lifespan (Migrationen, DB-Verbindung).

Ab M2 mit der Web-Schicht (Board, Artikelpflege), ab M3 mit dem QR-Entnahme-Flow, ab M4 mit
Einkaufsliste und Export-Schnittstelle, ab M5 mit den Etiketten — siehe docs/PLAN.md §9.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.export import router as export_router
from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.db import connect
from app.migrate import migrate
from app.web.board import router as board_router
from app.web.items import router as items_router
from app.web.labels import router as labels_router
from app.web.scan import router as scan_router
from app.web.shopping import router as shopping_router
from app.web.taxonomy import router as taxonomy_router

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
STATIC_DIR = Path(__file__).resolve().parent / "static"


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
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(health_router)
    app.include_router(export_router)
    app.include_router(board_router)
    app.include_router(items_router)
    app.include_router(labels_router)
    app.include_router(scan_router)
    app.include_router(shopping_router)
    app.include_router(taxonomy_router)

    return app


app = create_app()
