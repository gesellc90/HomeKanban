from __future__ import annotations

import pytest

from app.domain.stammdaten import (
    StammdatenExport,
    StammdatenFormatError,
    StammdatenItem,
    from_csv,
    from_json,
    to_csv,
    to_json,
)

_SAMPLE = StammdatenExport(
    categories=["Getränke", "Süßes"],
    stores=["REWE", "Aldi"],
    items=[
        StammdatenItem(
            name="Kaffee",
            unit="Packung",
            note="Marke egal",
            stock=2,
            reorder_level=1,
            target_stock=3,
            pack_size=1,
            lead_days=7,
            category="Getränke",
            store="REWE",
        ),
        StammdatenItem(
            name="Gummibärchen",
            unit="Tüte",
            note=None,
            stock=0,
            reorder_level=0,
            target_stock=1,
            pack_size=1,
            lead_days=7,
            category=None,
            store=None,
        ),
    ],
)


class TestJsonRoundtrip:
    def test_to_json_then_from_json_reproduces_the_input(self) -> None:
        assert from_json(to_json(_SAMPLE)) == _SAMPLE

    def test_empty_export_roundtrips(self) -> None:
        empty = StammdatenExport(categories=[], stores=[], items=[])
        assert from_json(to_json(empty)) == empty


class TestFromJsonRejectsBrokenInput:
    def test_not_json_at_all(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json("das ist kein json{")

    def test_truncated_json(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json('{"categories": ["A"], "stores": [], "items": [')

    def test_top_level_not_an_object(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json("[1, 2, 3]")

    def test_missing_top_level_field(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json('{"categories": [], "items": []}')

    def test_unknown_top_level_field(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json('{"categories": [], "stores": [], "items": [], "movements": []}')

    def test_categories_not_a_list_of_strings(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json('{"categories": [1, 2], "stores": [], "items": []}')

    def test_items_not_a_list(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json('{"categories": [], "stores": [], "items": "nope"}')

    def test_item_missing_field(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json(
                '{"categories": [], "stores": [], "items": [{"name": "Kaffee", "unit": "Packung"}]}'
            )

    def test_item_unknown_field(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json(to_json(_SAMPLE).replace('"note"', '"qr_token": "x", "note"'))

    def test_item_wrong_type_for_int_field(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json(to_json(_SAMPLE).replace('"stock": 2', '"stock": "zwei"'))

    def test_item_bool_is_not_accepted_as_int(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json(to_json(_SAMPLE).replace('"stock": 2', '"stock": true'))

    def test_item_wrong_type_for_string_field(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_json(to_json(_SAMPLE).replace('"name": "Kaffee"', '"name": 123'))


class TestCsvRoundtrip:
    def test_to_csv_then_from_csv_reproduces_the_items(self) -> None:
        result = from_csv(to_csv(_SAMPLE))

        assert result.items == _SAMPLE.items
        # Kategorien/Läden ohne Artikel gehen im CSV-Format verloren (Moduldoc) — hier haben
        # beide Beispieldaten mindestens einen Artikel, also bleibt die Menge gleich.
        assert set(result.categories) == {"Getränke"}
        assert set(result.stores) == {"REWE"}

    def test_categories_and_stores_without_items_are_lost_in_csv(self) -> None:
        data = StammdatenExport(categories=["Leer"], stores=[], items=[])
        result = from_csv(to_csv(data))
        assert result.categories == []

    def test_empty_items_roundtrips_to_header_only(self) -> None:
        empty = StammdatenExport(categories=[], stores=[], items=[])
        result = from_csv(to_csv(empty))
        assert result == empty


class TestFromCsvRejectsBrokenInput:
    def test_empty_file(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_csv("")

    def test_wrong_header(self) -> None:
        with pytest.raises(StammdatenFormatError):
            from_csv("foo,bar\n1,2\n")

    def test_missing_column(self) -> None:
        header = "name,unit,note,stock,reorder_level,target_stock,pack_size,category,store"
        with pytest.raises(StammdatenFormatError):
            from_csv(header + "\nKaffee,Packung,,2,1,3,1,,\n")

    def test_truncated_row_missing_trailing_columns(self) -> None:
        header = to_csv(StammdatenExport([], [], [])).splitlines()[0]
        with pytest.raises(StammdatenFormatError):
            from_csv(header + "\nKaffee,Packung\n")

    def test_row_with_too_many_columns(self) -> None:
        header = to_csv(StammdatenExport([], [], [])).splitlines()[0]
        with pytest.raises(StammdatenFormatError):
            from_csv(header + "\nKaffee,Packung,,2,1,3,1,7,,,extra\n")

    def test_non_integer_stock(self) -> None:
        header = to_csv(StammdatenExport([], [], [])).splitlines()[0]
        with pytest.raises(StammdatenFormatError):
            from_csv(header + "\nKaffee,Packung,,zwei,1,3,1,7,,\n")

    def test_blank_name(self) -> None:
        header = to_csv(StammdatenExport([], [], [])).splitlines()[0]
        with pytest.raises(StammdatenFormatError):
            from_csv(header + "\n ,Packung,,2,1,3,1,7,,\n")
