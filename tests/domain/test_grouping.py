"""Sortierung und Gruppierung als reine Entscheidung — tabellengetrieben, ohne Datenbank
(docs/PLAN.md §7, §9 M7)."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.grouping import MISC_LABEL, group_and_sort


@dataclass(frozen=True)
class _Entry:
    key: str
    store_name: str | None = None
    store_position: int | None = None
    category_name: str | None = None
    category_position: int | None = None
    sort_position: int = 0


def _keys(groups: tuple) -> list[list[str]]:  # type: ignore[type-arg]
    return [[entry.key for entry in group.entries] for group in groups]


def test_no_entries_yields_no_groups() -> None:
    assert group_and_sort([]) == ()


def test_single_store_produces_a_single_group_with_its_name() -> None:
    entries = [
        _Entry("a", store_name="REWE", store_position=0, sort_position=0),
        _Entry("b", store_name="REWE", store_position=0, sort_position=1),
    ]

    groups = group_and_sort(entries)

    assert len(groups) == 1
    assert groups[0].label == "REWE"
    assert _keys(groups) == [["a", "b"]]


def test_groups_are_ordered_by_store_position() -> None:
    entries = [
        _Entry("aldi-item", store_name="Aldi", store_position=1, sort_position=0),
        _Entry("rewe-item", store_name="REWE", store_position=0, sort_position=0),
    ]

    groups = group_and_sort(entries)

    assert [group.label for group in groups] == ["REWE", "Aldi"]


def test_entries_without_store_land_in_sonstiges_and_are_not_lost() -> None:
    """Definition of Done, §9 M7: Artikel ohne Zuordnung landen in "Sonstiges" und verschwinden
    nicht."""
    entries = [
        _Entry("unassigned", store_name=None, store_position=None, sort_position=0),
        _Entry("rewe-item", store_name="REWE", store_position=0, sort_position=0),
    ]

    groups = group_and_sort(entries)

    assert [group.label for group in groups] == ["REWE", MISC_LABEL]
    assert _keys(groups) == [["rewe-item"], ["unassigned"]]


def test_no_store_configured_at_all_yields_a_single_sonstiges_group() -> None:
    entries = [_Entry("a", sort_position=0), _Entry("b", sort_position=1)]

    groups = group_and_sort(entries)

    assert len(groups) == 1
    assert groups[0].label == MISC_LABEL
    assert _keys(groups) == [["a", "b"]]


def test_within_a_store_entries_are_ordered_by_category_position() -> None:
    entries = [
        _Entry(
            "dessert",
            store_name="REWE",
            store_position=0,
            category_name="Süßes",
            category_position=1,
            sort_position=0,
        ),
        _Entry(
            "milk",
            store_name="REWE",
            store_position=0,
            category_name="Kühlregal",
            category_position=0,
            sort_position=1,
        ),
    ]

    groups = group_and_sort(entries)

    assert _keys(groups) == [["milk", "dessert"]]


def test_entries_without_category_come_after_categorized_ones_within_a_store() -> None:
    entries = [
        _Entry("no-category", store_name="REWE", store_position=0, sort_position=0),
        _Entry(
            "with-category",
            store_name="REWE",
            store_position=0,
            category_name="Kühlregal",
            category_position=0,
            sort_position=1,
        ),
    ]

    groups = group_and_sort(entries)

    assert _keys(groups) == [["with-category", "no-category"]]


def test_stable_order_for_identical_store_and_category_position() -> None:
    """Sortierstabilität ist Pflicht (§9 M7 Testfokus): gleiche Laden- und Kategorieposition
    darf nicht von der Eingabereihenfolge abhängen, sondern folgt `sort_position`."""
    entries = [
        _Entry("second", store_name="REWE", store_position=0, sort_position=2),
        _Entry("first", store_name="REWE", store_position=0, sort_position=1),
    ]

    groups = group_and_sort(entries)

    assert _keys(groups) == [["first", "second"]]


def test_two_stores_with_equal_position_are_ordered_by_name() -> None:
    """Randfall aus der M7-Fragerunde: zwei Läden mit gleicher `position` dürfen die Reihenfolge
    nicht dem Zufall überlassen."""
    entries = [
        _Entry("z-item", store_name="Zooplus", store_position=0, sort_position=0),
        _Entry("a-item", store_name="Aldi", store_position=0, sort_position=0),
    ]

    groups = group_and_sort(entries)

    assert [group.label for group in groups] == ["Aldi", "Zooplus"]


def test_category_without_any_entry_simply_never_appears() -> None:
    """Eine Kategorie ohne Artikel braucht keine Sonderbehandlung — sie taucht schlicht nicht
    in den Eingabedaten auf."""
    entries = [
        _Entry(
            "only-entry",
            store_name="REWE",
            store_position=0,
            category_name="Kühlregal",
            category_position=0,
            sort_position=0,
        )
    ]

    groups = group_and_sort(entries)

    assert _keys(groups) == [["only-entry"]]
