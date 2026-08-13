from __future__ import annotations

from app.domain.validation import ItemInput, ItemValidationError, require_valid_item, validate_item

_VALID = ItemInput(
    name="Kaffee",
    unit="Packung",
    reorder_level=1,
    target_stock=3,
    pack_size=1,
    lead_days=7,
    stock=2,
    note=None,
)


def _replace(**changes: object) -> ItemInput:
    from dataclasses import replace

    return replace(_VALID, **changes)


class TestValidateItem:
    def test_valid_input_has_no_errors(self) -> None:
        assert validate_item(_VALID) == []

    def test_empty_name_is_rejected(self) -> None:
        errors = validate_item(_replace(name=""))
        assert any("Name" in error for error in errors)

    def test_blank_name_is_rejected(self) -> None:
        errors = validate_item(_replace(name="   "))
        assert any("Name" in error for error in errors)

    def test_empty_unit_is_rejected(self) -> None:
        errors = validate_item(_replace(unit=""))
        assert any("Einheit" in error for error in errors)

    def test_negative_stock_is_rejected(self) -> None:
        errors = validate_item(_replace(stock=-1))
        assert any("Bestand" in error for error in errors)

    def test_stock_none_is_not_checked(self) -> None:
        # stock=None bedeutet: hier nicht geprüft (z. B. beim Ändern der Stammdaten, wo der
        # Bestand nicht Teil des Formulars ist).
        assert validate_item(_replace(stock=None)) == []

    def test_negative_reorder_level_is_rejected(self) -> None:
        errors = validate_item(_replace(reorder_level=-1, target_stock=1))
        assert any("Mindestbestand" in error for error in errors)

    def test_pack_size_below_one_is_rejected(self) -> None:
        errors = validate_item(_replace(pack_size=0))
        assert any("Kaufeinheit" in error for error in errors)

    def test_lead_days_below_one_is_rejected(self) -> None:
        errors = validate_item(_replace(lead_days=0))
        assert any("Vorlaufzeit" in error for error in errors)

    def test_target_stock_equal_to_reorder_level_is_rejected(self) -> None:
        errors = validate_item(_replace(reorder_level=3, target_stock=3))
        assert any("Sollbestand" in error for error in errors)

    def test_target_stock_below_reorder_level_is_rejected(self) -> None:
        errors = validate_item(_replace(reorder_level=3, target_stock=2))
        assert any("Sollbestand" in error for error in errors)

    def test_multiple_violations_are_all_reported(self) -> None:
        errors = validate_item(_replace(name="", unit="", pack_size=0))
        assert len(errors) >= 3


class TestRequireValidItem:
    def test_valid_input_does_not_raise(self) -> None:
        require_valid_item(_VALID)

    def test_invalid_input_raises_with_errors(self) -> None:
        try:
            require_valid_item(_replace(name=""))
        except ItemValidationError as error:
            assert error.errors
        else:
            raise AssertionError("ItemValidationError wurde nicht ausgelöst")
