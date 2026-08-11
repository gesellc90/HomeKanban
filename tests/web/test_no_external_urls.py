"""Automatisierbarer Teil der Definition of Done "kein Netzwerkzugriff nach außen" (M2):
kein Template darf auf eine externe URL verweisen — alle Assets liegen im Repo (CLAUDE.md §4).
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "app" / "templates"
STATIC_CSS = Path(__file__).resolve().parent.parent.parent / "app" / "static" / "app.css"

_EXTERNAL_URL = re.compile(r"""(https?:)?//[^"'\s)]+""")

# Absolute, aber lokale Pfade wie "/static/app.css" oder "/artikel/neu" sind kein Netzwerkzugriff
# nach außen — nur echte Fremd-Hosts (mit "//") zählen.


def test_no_template_references_an_external_host() -> None:
    offenders = []
    for path in TEMPLATES_DIR.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        for match in _EXTERNAL_URL.finditer(text):
            offenders.append(f"{path.name}: {match.group(0)}")

    assert offenders == [], f"Externe URLs in Templates gefunden: {offenders}"


def test_stylesheet_references_no_external_host() -> None:
    text = STATIC_CSS.read_text(encoding="utf-8")
    matches = _EXTERNAL_URL.findall(text)
    assert matches == [], f"Externe URLs in app.css gefunden: {matches}"
