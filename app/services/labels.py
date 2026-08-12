"""Etiketten: QR-Erzeugung und Verbindung von Artikeln zu Etiketten (docs/PLAN.md §9, M5).

Der Inhalt eines Codes ist **ausschließlich** `{BASE_URL}/e/{qr_token}` — exakt die URL, die
`app/web/scan.py` bedient. Das ist der Punkt, an dem dieser Meilenstein steht oder fällt: Ein Code,
der irgendwohin sonst zeigt, fällt erst am geklebten Etikett auf, und dann ist der Bogen schon
verbraucht. Deshalb gibt es genau eine Stelle, die diese URL baut (`scan_url`), und einen Test, der
den an `segno` übergebenen Inhalt gegen `BASE_URL` + Token prüft.

**Fehlerkorrektur „M“** (15 %) statt einer höheren Stufe: Auf einem 25-mm-Etikett ist nicht die
Fehlertoleranz die knappe Größe, sondern die Modulkantenlänge — Stufe „Q“ hebt die URL von
Version 4 (33×33 Module) auf Version 5 (37×37) und macht damit jedes Modul rund 10 % kleiner,
also schlechter lesbar, um eine Robustheit zu gewinnen, die im Vorratsschrank kaum gebraucht wird.

**Ruhezone:** Die Spezifikation verlangt vier Module Weißraum um den Code. Der Einzeldownload
liefert sie vollständig mit (`_STANDALONE_BORDER`). Auf dem Bogen wird sie auf zwei Module
verkürzt (`_SHEET_BORDER`) und der Rest kommt aus dem Innenabstand der Etikettenzelle — sonst
fräße die Ruhezone auf kleinen Etiketten den Code selbst zusammen. Der weiße Rand des Etiketts
setzt sie ohnehin fort.
"""

from __future__ import annotations

import io
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

import segno

from app.repo import items as items_repo

# Ruhezone in Modulen, siehe Modulkommentar.
_STANDALONE_BORDER = 4
_SHEET_BORDER = 2

# Fehlerkorrekturstufe für alle Codes dieses Projekts, siehe Modulkommentar.
_ERROR_CORRECTION = "m"

# Kantenlänge eines Moduls im PNG. 33 Module plus zweimal vier Module Ruhezone × 10 px = 410 px;
# auf einem 25-mm-Etikett sind das rund 400 dpi, also mehr als jeder Haushaltsdrucker auflöst —
# und trotzdem nur ein paar hundert Byte.
_PNG_SCALE = 10


def scan_url(base_url: str, qr_token: str) -> str:
    """Die einzige Stelle, an der die Etiketten-URL entsteht (§5). Siehe Modulkommentar."""
    return f"{base_url.rstrip('/')}/e/{qr_token}"


def _encode(url: str) -> segno.QRCode:
    # `border` ist bei segno bewusst keine Eigenschaft des Codes, sondern der Ausgabe — die
    # Ruhezone wird deshalb erst beim Serialisieren gesetzt.
    return segno.make(url, error=_ERROR_CORRECTION)


def qr_svg_document(url: str) -> str:
    """Vollständiges SVG-Dokument samt XML-Prolog — für `GET /artikel/{id}/qr.svg`.

    `unit="mm"` mit `scale=0.5` gibt dem Dokument eine **physische** Größe (0,5 mm je Modul, also
    rund 20 mm Kantenlänge samt Ruhezone) und dazu eine `viewBox`. Beides zusammen ist der
    Unterschied zwischen „lässt sich irgendwo einfügen und druckt scannbar“ und „druckt in
    Briefmarkengröße oder wird beschnitten“: Ohne `viewBox` skaliert ein SVG nicht mit, ohne
    Einheit ist seine Größe eine Pixelangabe ohne Bezug zum Papier.
    """
    buffer = io.BytesIO()
    _encode(url).save(
        buffer, kind="svg", scale=0.5, unit="mm", border=_STANDALONE_BORDER, xmldecl=True
    )
    return buffer.getvalue().decode("utf-8")


def qr_png_bytes(url: str) -> bytes:
    """PNG für den Einzeldownload. `segno` schreibt PNG in reinem Python, ohne Pillow (L7)."""
    buffer = io.BytesIO()
    _encode(url).save(buffer, kind="png", scale=_PNG_SCALE, border=_STANDALONE_BORDER)
    return buffer.getvalue()


def qr_svg_inline(url: str, *, border: int = _SHEET_BORDER) -> str:
    """SVG-Fragment ohne XML-Prolog und **ohne** feste Größe, zum Einbetten in HTML.

    `omitsize=True` ist hier der Kern: Ohne `width`/`height` skaliert der Browser den Code über
    die `viewBox` auf die Millimetermaße, die das Druck-CSS der Zelle vorgibt. Eine feste
    Pixelgröße würde genau das verhindern — und maßhaltiger Druck ist der Zweck der Übung.
    """
    return _encode(url).svg_inline(omitsize=True, border=border, svgclass="qr", lineclass="qr__m")


@dataclass(frozen=True)
class Label:
    """Ein druckfertiges Etikett.

    Auf dem Papier landen nur QR-Code und Name — mit dem Nutzer so entschieden (M5, Fragerunde 1):
    kein abtippbarer URL-Text, keine Einheit. Der Klartextname bleibt, weil ein Etikett ohne ihn im
    Schrank nicht zuzuordnen ist, wenn es sich löst (R9); die URL bliebe auf kleinen Rastern nur
    auf Kosten der QR-Fläche stehen und würde damit genau den Fall verschlimmern, den sie retten
    soll. `url` steht hier trotzdem: Es ist der Inhalt des Codes und die Größe, gegen die geprüft
    wird.
    """

    item_id: int
    name: str
    url: str
    qr_svg: str


def build_label(item: items_repo.ItemRow, *, base_url: str) -> Label:
    url = scan_url(base_url, item.qr_token)
    return Label(item_id=item.id, name=item.name, url=url, qr_svg=qr_svg_inline(url))


def selectable_items(connection: sqlite3.Connection) -> list[items_repo.ItemRow]:
    """Artikel, die ein Etikett bekommen können — nur nicht archivierte (§4 Regel 4, §9 M5)."""
    return items_repo.list_active(connection)


def collect_labels(
    connection: sqlite3.Connection, *, item_ids: Sequence[int], base_url: str
) -> tuple[list[Label], list[int]]:
    """Baut Etiketten für die gewählten Artikel-IDs.

    Liefert `(labels, unknown_ids)`. „Unbekannt“ ist dabei alles, was nicht als **aktiver** Artikel
    auffindbar ist — nicht vergebene IDs genauso wie archivierte. Die Web-Schicht macht daraus eine
    deutsche Meldung mit Nicht-500-Status, statt hier eine Ausnahme zu werfen.

    Die Reihenfolge folgt der Board-Reihenfolge (`items.position`), nicht der Reihenfolge der
    angehakten Kästchen — so liegt ein zweiter Ausdruck derselben Auswahl gleich.
    """
    wanted = set(item_ids)
    active = {item.id: item for item in selectable_items(connection)}

    labels = [build_label(item, base_url=base_url) for item in active.values() if item.id in wanted]
    unknown = sorted(wanted - active.keys())
    return labels, unknown
