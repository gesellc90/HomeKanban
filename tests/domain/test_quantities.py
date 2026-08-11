from __future__ import annotations

import pytest

from app.domain.quantities import reorder_quantity


@pytest.mark.parametrize(
    ("stock", "target_stock", "pack_size", "expected", "reason"),
    [
        (0, 4, 6, 6, "eine Kaufeinheit deckt mehr als den Bedarf — trotzdem kauft man 6"),
        (3, 4, 1, 1, "glatter Fall"),
        (1, 10, 4, 12, "9 Bedarf → drei Vierer-Packs"),
        (2, 2, 1, 1, "Schwelle erreicht, Bedarf rechnerisch 0 → Minimum greift"),
    ],
)
def test_reorder_quantity_examples_from_plan(
    stock: int, target_stock: int, pack_size: int, expected: int, reason: str
) -> None:
    result = reorder_quantity(stock=stock, target_stock=target_stock, pack_size=pack_size)
    assert result == expected, reason


def test_reorder_quantity_never_below_pack_size_even_above_target() -> None:
    assert reorder_quantity(stock=5, target_stock=4, pack_size=2) == 2


def test_reorder_quantity_exact_multiple_of_pack_size() -> None:
    assert reorder_quantity(stock=0, target_stock=8, pack_size=4) == 8


def test_reorder_quantity_pack_size_of_one_matches_arithmetic_difference() -> None:
    assert reorder_quantity(stock=2, target_stock=9, pack_size=1) == 7
