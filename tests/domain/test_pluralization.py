from __future__ import annotations

import pytest

from app.domain.pluralization import format_quantity, plural_unit


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        # Endungsregel "-ung" → "-en"
        ("Packung", "Packungen"),
        ("Portion", "Portionen"),
        # Endungsregel "-e" → "-n"
        ("Rolle", "Rollen"),
        ("Flasche", "Flaschen"),
        ("Dose", "Dosen"),
        ("Kiste", "Kisten"),
        ("Tüte", "Tüten"),
        # Endungsregeln ohne Änderung
        ("Beutel", "Beutel"),
        ("Becher", "Becher"),
        ("Kanister", "Kanister"),
        ("Päckchen", "Päckchen"),
        # Ausnahmetabelle
        ("Stück", "Stück"),
        ("Glas", "Gläser"),
        ("Sack", "Säcke"),
        ("Kasten", "Kästen"),
        ("Karton", "Kartons"),
        ("Tafel", "Tafeln"),
        ("Schachtel", "Schachteln"),
        ("Paket", "Pakete"),
        ("Tube", "Tuben"),
        ("Blatt", "Blatt"),
        ("Paar", "Paar"),
        ("Bund", "Bund"),
    ],
)
def test_plural_forms(unit: str, expected: str) -> None:
    assert plural_unit(unit) == expected


def test_unknown_unit_stays_unchanged() -> None:
    """Der Rückfall rät nicht: lieber eine schiefe Zahlenangabe als ein erfundenes Wort."""
    assert plural_unit("Zwölferträger") == "Zwölferträger"


def test_capitalization_is_preserved() -> None:
    assert plural_unit("rolle") == "rollen"
    assert plural_unit("Rolle") == "Rollen"


def test_compound_unit_keeps_its_inner_capitals() -> None:
    """Ein blindes `.capitalize()` würde hier „500-g-paket“ daraus machen."""
    assert plural_unit("500-g-Paket") == "500-g-Paket"


def test_whitespace_is_trimmed() -> None:
    assert plural_unit("  Rolle  ") == "Rollen"
    assert plural_unit("   ") == ""


@pytest.mark.parametrize(
    ("quantity", "unit", "expected"),
    [
        (1, "Packung", "1 Packung"),
        (2, "Packung", "2 Packungen"),
        (10, "Rolle", "10 Rollen"),
        (0, "Rolle", "0 Rollen"),
        (1, "Stück", "1 Stück"),
        (3, "Stück", "3 Stück"),
    ],
)
def test_format_quantity(quantity: int, unit: str, expected: str) -> None:
    """Bei genau 1 bleibt der Singular stehen — „1 Rollen“ wäre schlimmer als „10 Rolle“."""
    assert format_quantity(quantity=quantity, unit=unit) == expected
