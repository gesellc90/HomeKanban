from __future__ import annotations

from app.domain.status import ItemStatus, derive_status


def test_stock_above_reorder_level_is_ok() -> None:
    assert derive_status(stock=2, reorder_level=1, has_open_list_line=False) is ItemStatus.OK


def test_stock_exactly_at_reorder_level_is_reorder() -> None:
    result = derive_status(stock=1, reorder_level=1, has_open_list_line=False)
    assert result is ItemStatus.REORDER


def test_stock_below_reorder_level_is_reorder() -> None:
    result = derive_status(stock=0, reorder_level=1, has_open_list_line=False)
    assert result is ItemStatus.REORDER


def test_open_unchecked_line_forces_on_list_even_with_sufficient_stock() -> None:
    result = derive_status(stock=10, reorder_level=1, has_open_list_line=True)
    assert result is ItemStatus.ON_LIST


def test_open_unchecked_line_forces_on_list_even_with_low_stock() -> None:
    result = derive_status(stock=0, reorder_level=1, has_open_list_line=True)
    assert result is ItemStatus.ON_LIST


def test_transition_ok_to_reorder_crossing_threshold_downward() -> None:
    above = derive_status(stock=2, reorder_level=1, has_open_list_line=False)
    at_threshold = derive_status(stock=1, reorder_level=1, has_open_list_line=False)

    assert above is ItemStatus.OK
    assert at_threshold is ItemStatus.REORDER


def test_transition_reorder_to_ok_crossing_threshold_upward() -> None:
    at_threshold = derive_status(stock=1, reorder_level=1, has_open_list_line=False)
    above = derive_status(stock=2, reorder_level=1, has_open_list_line=False)

    assert at_threshold is ItemStatus.REORDER
    assert above is ItemStatus.OK


def test_reorder_level_zero_only_empty_stock_triggers_reorder() -> None:
    assert derive_status(stock=0, reorder_level=0, has_open_list_line=False) is ItemStatus.REORDER
    assert derive_status(stock=1, reorder_level=0, has_open_list_line=False) is ItemStatus.OK
