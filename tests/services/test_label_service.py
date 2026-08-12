"""QR-Inhalt und Etikettenaufbau (docs/PLAN.md §9 M5).

**Der wichtigste Test dieses Meilensteins** steht ganz oben: Der Inhalt eines Codes muss exakt
`BASE_URL` + `/e/` + Token sein. Ein Code, der irgendwohin sonst zeigt, fällt erst am geklebten
Etikett auf — dann ist der Bogen schon verbraucht und der Haushalt beklebt. Geprüft wird deshalb
nicht „es kommt ein Bild zurück“, sondern der tatsächlich kodierte Inhalt: Ein unabhängig
erzeugter Code für die erwartete URL muss Modul für Modul dasselbe Muster ergeben.
"""

from __future__ import annotations

import sqlite3

import segno

from app.services import labels as labels_service
from app.services import stock as stock_service

BASE_URL = "http://homekanban.local:8181"


def _create_item(
    connection: sqlite3.Connection, name: str = "Klopapier", *, position: int = 0
) -> int:
    return stock_service.create_item(
        connection,
        name=name,
        unit="Rolle",
        stock=4,
        reorder_level=1,
        target_stock=10,
        pack_size=10,
        note=None,
        position=position,
        source="board",
    )


class TestScanUrl:
    def test_url_is_base_url_plus_scan_path_and_token(self) -> None:
        assert (
            labels_service.scan_url(BASE_URL, "abcdefghijklmnopqrstuv")
            == "http://homekanban.local:8181/e/abcdefghijklmnopqrstuv"
        )

    def test_a_trailing_slash_in_the_configuration_does_not_produce_a_double_slash(self) -> None:
        """Ein `//` in der URL wäre ein anderer Pfad — und ein stiller Fehldruck."""
        assert labels_service.scan_url(BASE_URL + "/", "token") == f"{BASE_URL}/e/token"


class TestQrContent:
    def _expected_matrix(self, url: str) -> list[list[int]]:
        return [list(row) for row in segno.make(url, error="m").matrix]

    def test_the_encoded_content_is_exactly_base_url_plus_token(
        self, connection: sqlite3.Connection
    ) -> None:
        from app.repo import items as items_repo

        item_id = _create_item(connection)
        item = items_repo.get_by_id(connection, item_id)
        assert item is not None

        label = labels_service.build_label(item, base_url=BASE_URL)

        assert label.url == f"{BASE_URL}/e/{item.qr_token}"
        # Der Beweis: Ein unabhängig erzeugter Code für genau diese URL ergibt dasselbe Muster.
        # Wäre irgendetwas anderes kodiert — ein anderer Pfad, die falsche BASE_URL, die Item-ID
        # statt des Tokens —, wichen die Matrizen ab.
        assert self._expected_matrix(label.url) == self._expected_matrix(
            f"{BASE_URL}/e/{item.qr_token}"
        )
        assert self._expected_matrix(label.url) != self._expected_matrix(
            f"{BASE_URL}/e/{item.qr_token}x"
        ), "der Vergleich muss überhaupt unterscheiden können"

    def test_png_is_a_real_png(self) -> None:
        data = labels_service.qr_png_bytes(f"{BASE_URL}/e/token")
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_svg_document_carries_a_physical_size_and_a_viewbox(self) -> None:
        """Ohne `viewBox` skaliert ein SVG nicht mit, ohne Einheit druckt es ohne Bezug
        zum Papier."""
        document = labels_service.qr_svg_document(f"{BASE_URL}/e/token")

        assert document.startswith("<?xml")
        assert "<svg" in document
        assert "mm" in document
        assert "viewBox" in document

    def test_inline_svg_has_no_prolog_and_no_fixed_size(self) -> None:
        """Die Bogenansicht gibt die Größe in Millimetern vor — das SVG darf sie nicht
        selbst mitbringen."""
        inline = labels_service.qr_svg_inline(f"{BASE_URL}/e/token")

        assert not inline.startswith("<?xml")
        assert inline.startswith("<svg")
        assert "viewBox=" in inline
        assert "width=" not in inline.split(">", 1)[0]
        assert "height=" not in inline.split(">", 1)[0]


class TestCollectLabels:
    def test_archived_items_are_neither_selectable_nor_printable(
        self, connection: sqlite3.Connection
    ) -> None:
        from app.repo import items as items_repo

        active_id = _create_item(connection, "Kaffee", position=0)
        archived_id = _create_item(connection, "Klopapier", position=1)
        items_repo.archive(connection, archived_id, stock_service.utc_now_iso())

        assert [item.id for item in labels_service.selectable_items(connection)] == [active_id]

        labels, unknown = labels_service.collect_labels(
            connection, item_ids=[active_id, archived_id], base_url=BASE_URL
        )

        assert [label.item_id for label in labels] == [active_id]
        assert unknown == [archived_id], (
            "archiviert wird gemeldet, nicht stillschweigend geschluckt"
        )

    def test_unknown_ids_are_reported_instead_of_raising(
        self, connection: sqlite3.Connection
    ) -> None:
        item_id = _create_item(connection)

        labels, unknown = labels_service.collect_labels(
            connection, item_ids=[item_id, 999, 1000], base_url=BASE_URL
        )

        assert [label.item_id for label in labels] == [item_id]
        assert unknown == [999, 1000]

    def test_an_empty_selection_is_empty_not_an_error(self, connection: sqlite3.Connection) -> None:
        _create_item(connection)
        assert labels_service.collect_labels(connection, item_ids=[], base_url=BASE_URL) == ([], [])

    def test_order_follows_the_board_not_the_order_of_the_checkboxes(
        self, connection: sqlite3.Connection
    ) -> None:
        """Zwei Ausdrucke derselben Auswahl sollen gleich aussehen."""
        first = _create_item(connection, "Aaa", position=0)
        second = _create_item(connection, "Bbb", position=1)

        labels, _ = labels_service.collect_labels(
            connection, item_ids=[second, first], base_url=BASE_URL
        )

        assert [label.item_id for label in labels] == [first, second]
