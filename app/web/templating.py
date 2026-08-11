"""Gemeinsame Jinja2-Einrichtung für die Web-Router (`app/web/board.py`, `app/web/items.py`)."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.web.formatting import format_local, movement_kind_label, status_label

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["local_time"] = format_local
templates.env.filters["movement_kind_label"] = movement_kind_label
templates.env.filters["status_label"] = status_label
