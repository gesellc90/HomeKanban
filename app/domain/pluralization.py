"""Deutsche Pluralform für Mengeneinheiten, siehe docs/PLAN.md §6.

Gespeichert wird `items.unit` im Singular („Rolle“, „Packung“). Das Textformat des Exports zeigt
aber die Menge davor — „10 Rolle“ liest sich im Laden falsch. Statt einer zweiten Spalte am
Artikel (Schemaänderung für Kosmetik) steht hier eine kleine, rein deutsche Regel: eine
Ausnahmetabelle für die Einheiten, die im Haushalt vorkommen, davor ein paar verlässliche
Endungsregeln, und als Rückfall die unveränderte Form.

Der Rückfall ist bewusst „unverändert“ und nicht „geraten“: Eine unbekannte Einheit ergibt dann
höchstens eine schiefe Zahlenangabe („10 Karton“), nie ein erfundenes Wort. Neue Einheiten
gehören in `_EXCEPTIONS` — das ist das im Prompt gemeinte Feld für Ausnahmen.

Reine Logik: kein SQL, kein I/O.
"""

from __future__ import annotations

# Einheiten, die die Endungsregeln unten nicht oder falsch treffen. Schlüssel kleingeschrieben;
# die Groß-/Kleinschreibung der Eingabe wird beim Zusammenbauen wiederhergestellt.
_EXCEPTIONS: dict[str, str] = {
    "blatt": "blatt",
    "bund": "bund",
    "glas": "gläser",
    "karton": "kartons",
    "kasten": "kästen",
    "netz": "netze",
    "paar": "paar",
    "paket": "pakete",
    "sack": "säcke",
    "schachtel": "schachteln",
    "set": "sets",
    "spray": "sprays",
    "stift": "stifte",
    "stück": "stück",
    "tafel": "tafeln",
    "tropfen": "tropfen",
    "tube": "tuben",
}

# Endungen, die im Deutschen zuverlässig ein „-en“ anhängen (Packung → Packungen).
_SUFFIXES_PLUS_EN = ("ung", "ion", "heit", "keit", "schaft")

# Endungen, die den Plural unverändert lassen (Beutel, Becher, Kanister, Päckchen).
_SUFFIXES_UNCHANGED = ("chen", "lein", "el", "er", "en")


def plural_unit(unit: str) -> str:
    """Pluralform einer Mengeneinheit. Unbekanntes bleibt unverändert (siehe Modul-Docstring)."""
    stripped = unit.strip()
    if not stripped:
        return stripped

    # .lower() statt .casefold(): casefold macht aus „ß“ zwei Zeichen und würde die
    # zeichenweise Ausrichtung in `_restore_case` verschieben.
    lowered = stripped.lower()
    plural = _EXCEPTIONS.get(lowered) or _apply_suffix_rules(lowered)
    return _restore_case(stripped, plural)


def format_quantity(*, quantity: int, unit: str) -> str:
    """Menge mit passender Einheit: `1 Packung`, `2 Packungen`, `10 Rollen`."""
    return f"{quantity} {unit.strip() if quantity == 1 else plural_unit(unit)}"


def _apply_suffix_rules(lowered: str) -> str:
    if lowered.endswith(_SUFFIXES_PLUS_EN):
        return lowered + "en"
    if lowered.endswith("in"):
        return lowered + "nen"
    if lowered.endswith(_SUFFIXES_UNCHANGED):
        return lowered
    if lowered.endswith("e"):
        return lowered + "n"
    return lowered


def _restore_case(original: str, plural: str) -> str:
    """Setzt die Schreibweise der Eingabe wieder ein.

    Die Regeln arbeiten auf der kleingeschriebenen Form; hier wird der übereinstimmende Anfang
    aus dem Original übernommen. Das trägt auch zusammengesetzte Einheiten wie „500-g-Paket“,
    bei denen ein blindes `.capitalize()` die Binnengroßschreibung zerstören würde.
    """
    lowered = original.lower()
    keep = 0
    while keep < len(plural) and keep < len(original) and plural[keep] == lowered[keep]:
        keep += 1
    return original[:keep] + plural[keep:]
