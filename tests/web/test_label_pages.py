"""Etikettenseiten und Einzel-QR über HTTP (docs/PLAN.md §7 M5, §11).

Der schärfste Test steht in `TestQrEndpoints.test_the_printed_url_actually_resolves_in_this_app`:
Er nimmt die URL, die im Code steckt, wirft die Basis weg und ruft den Rest gegen dieselbe App
auf. Damit ist bewiesen, dass ein geklebtes Etikett genau die Entnahmeseite seines Artikels
öffnet — die eine Eigenschaft, deren Fehlen erst am fertigen Bogen auffiele.
"""

from __future__ import annotations

import io
import re

import segno
from fastapi.testclient import TestClient

from app.config import Settings


def _create_item(client: TestClient, name: str) -> int:
    response = client.post(
        "/artikel",
        data={
            "name": name,
            "unit": "Packung",
            "stock": 4,
            "reorder_level": 1,
            "target_stock": 10,
            "pack_size": 2,
        },
    )
    assert response.status_code == 200, response.text
    return int(str(response.url).rstrip("/").rsplit("/", 1)[-1])


def _scan_token(client: TestClient, item_id: int) -> str:
    """Liest das Token aus dem kopierbaren Entnahme-Link der Detailseite."""
    page = client.get(f"/artikel/{item_id}").text
    match = re.search(r'class="scan-link__url" href="[^"]*/e/([A-Za-z0-9_-]+)"', page)
    assert match is not None, "Entnahme-Link fehlt auf der Detailseite"
    return match.group(1)


class TestQrEndpoints:
    def test_svg_has_the_right_content_type_and_really_is_an_svg(self, client: TestClient) -> None:
        item_id = _create_item(client, "Klopapier")

        response = client.get(f"/artikel/{item_id}/qr.svg")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.text.lstrip().startswith("<?xml")
        assert "<svg" in response.text

    def test_png_has_the_right_content_type_and_really_is_a_png(self, client: TestClient) -> None:
        item_id = _create_item(client, "Klopapier")

        response = client.get(f"/artikel/{item_id}/qr.png")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_both_formats_are_cacheable_but_not_frozen(self, client: TestClient) -> None:
        """Stabil je Token, aber `BASE_URL` kann sich in der Einrichtung noch ändern."""
        item_id = _create_item(client, "Klopapier")

        for suffix in ("svg", "png"):
            cache_control = client.get(f"/artikel/{item_id}/qr.{suffix}").headers["cache-control"]
            assert "max-age" in cache_control
            assert "immutable" not in cache_control

    def test_the_encoded_content_is_base_url_plus_token(
        self, client: TestClient, settings: Settings
    ) -> None:
        item_id = _create_item(client, "Klopapier")
        token = _scan_token(client, item_id)

        response = client.get(f"/artikel/{item_id}/qr.png")
        expected = segno.make(f"{settings.base_url}/e/{token}", error="m")

        # Byte-für-Byte gegen einen unabhängig erzeugten Code für die erwartete URL. Der
        # Endpunkt benutzt dieselben Ausgabeoptionen (Skalierung 10, Ruhezone 4).
        buffer = io.BytesIO()
        expected.save(buffer, kind="png", scale=10, border=4)
        assert response.content == buffer.getvalue()

    def test_the_printed_url_actually_resolves_in_this_app(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Das eigentliche Versprechen des Etiketts: Der Code öffnet die richtige Seite."""
        item_id = _create_item(client, "Klopapier")
        token = _scan_token(client, item_id)

        printed_url = f"{settings.base_url}/e/{token}"
        assert printed_url.startswith(settings.base_url)
        path = printed_url[len(settings.base_url) :]

        scan_page = client.get(path)
        assert scan_page.status_code == 200
        assert "Klopapier" in scan_page.text

    def test_unknown_item_is_a_friendly_404_not_a_stacktrace(self, client: TestClient) -> None:
        for suffix in ("svg", "png"):
            response = client.get(f"/artikel/4711/qr.{suffix}")
            assert response.status_code == 404
            assert "nicht gefunden" in response.text

    def test_archived_item_gets_no_label(self, client: TestClient) -> None:
        """Ein Etikett für einen archivierten Artikel wäre von vornherein ein totes Etikett."""
        item_id = _create_item(client, "Klopapier")
        client.post(f"/artikel/{item_id}/archivieren")

        for suffix in ("svg", "png"):
            response = client.get(f"/artikel/{item_id}/qr.{suffix}")
            assert response.status_code == 410
            assert "archiviert" in response.text

    def test_the_detail_page_embeds_the_qr_and_keeps_the_copyable_link(
        self, client: TestClient
    ) -> None:
        """Der Platzhaltersatz aus M3 ist eingelöst — der Link bleibt als Rückweg (R9)."""
        item_id = _create_item(client, "Klopapier")

        page = client.get(f"/artikel/{item_id}").text

        assert f"/artikel/{item_id}/qr.svg" in page
        assert f"/artikel/{item_id}/qr.png" in page
        assert "der Einzel-QR-Code kommt erst in M5" not in page
        assert 'class="scan-link__input"' in page, "der kopierbare Link muss stehen bleiben"


class TestSelectionPage:
    def test_it_lists_active_items(self, client: TestClient) -> None:
        _create_item(client, "Klopapier")
        _create_item(client, "Kaffee")

        response = client.get("/etiketten")

        assert response.status_code == 200
        assert "Klopapier" in response.text
        assert "Kaffee" in response.text

    def test_archived_items_do_not_appear(self, client: TestClient) -> None:
        keep = _create_item(client, "Kaffee")
        drop = _create_item(client, "Klopapier")
        client.post(f"/artikel/{drop}/archivieren")

        response = client.get("/etiketten")

        assert f'value="{keep}"' in response.text
        assert f'value="{drop}"' not in response.text
        assert "Klopapier" not in response.text

    def test_without_any_item_it_says_so_instead_of_showing_an_empty_form(
        self, client: TestClient
    ) -> None:
        response = client.get("/etiketten")

        assert response.status_code == 200
        assert "noch keine Artikel" in response.text

    def test_a_preselected_item_arrives_checked(self, client: TestClient) -> None:
        """Der Weg „Detailseite → Auf Bogen drucken“ soll den Artikel schon angehakt haben."""
        item_id = _create_item(client, "Klopapier")

        response = client.get(f"/etiketten?item_id={item_id}")

        checkbox = re.search(rf'<input[^>]*value="{item_id}"[^>]*>', response.text, flags=re.DOTALL)
        assert checkbox is not None, "Kästchen des Artikels fehlt"
        assert "checked" in checkbox.group(0)

    def test_a_nonsense_grid_is_reported_on_the_form(self, client: TestClient) -> None:
        _create_item(client, "Klopapier")

        response = client.get("/etiketten?grid_key=frei&columns=0")

        assert response.status_code == 200
        assert "mindestens eine Spalte" in response.text


class TestSheetPage:
    def test_every_selected_item_gets_exactly_one_label(self, client: TestClient) -> None:
        ids = [_create_item(client, name) for name in ("Klopapier", "Kaffee", "Tabs")]
        query = "&".join(f"item_id={item_id}" for item_id in ids)

        response = client.get(f"/etiketten/druck?{query}")

        assert response.status_code == 200
        assert response.text.count('class="label"') == len(ids)
        assert response.text.count("<svg") == len(ids)
        for name in ("Klopapier", "Kaffee", "Tabs"):
            assert response.text.count(f">{name}<") == 1

    def test_it_breaks_onto_several_sheets(self, client: TestClient) -> None:
        ids = [_create_item(client, f"Artikel {n}") for n in range(5)]
        query = "&".join(f"item_id={item_id}" for item_id in ids)
        # Freies Raster mit zwei Zellen je Bogen: fünf Etiketten ergeben drei Bögen.
        grid = "grid_key=frei&columns=1&rows=2&label_width=70&label_height=37"

        response = client.get(f"/etiketten/druck?{query}&{grid}")

        assert response.status_code == 200
        assert response.text.count('class="sheet"') == 3
        assert response.text.count('class="label"') == 5

    def test_it_carries_no_navigation_into_the_print(self, client: TestClient) -> None:
        """Reine Druckansicht: kein Kopf, keine Board-Navigation (§9 M5)."""
        item_id = _create_item(client, "Klopapier")

        response = client.get(f"/etiketten/druck?item_id={item_id}")

        assert "app-header" not in response.text
        assert "/static/labels-print.css" in response.text

    def test_an_empty_selection_is_caught(self, client: TestClient) -> None:
        _create_item(client, "Klopapier")

        response = client.get("/etiketten/druck")

        assert response.status_code == 422
        assert "kein Artikel ausgewählt" in response.text

    def test_an_unknown_item_id_is_reported(self, client: TestClient) -> None:
        response = client.get("/etiketten/druck?item_id=4711")

        assert response.status_code == 404
        assert "4711" in response.text

    def test_an_archived_item_in_the_selection_is_refused(self, client: TestClient) -> None:
        item_id = _create_item(client, "Klopapier")
        client.post(f"/artikel/{item_id}/archivieren")

        response = client.get(f"/etiketten/druck?item_id={item_id}")

        assert response.status_code == 404
        assert "archiviert" in response.text

    def test_nonsense_grid_values_never_produce_a_stacktrace(self, client: TestClient) -> None:
        item_id = _create_item(client, "Klopapier")
        base = f"/etiketten/druck?item_id={item_id}&grid_key=frei"

        for query in (
            "columns=0",
            "rows=0",
            "columns=-3",
            "label_width=0",
            "label_height=-5",
            "label_width=300",  # breiter als A4
            "label_height=400",  # höher als A4
            "margin_left=-10",
            "row_gap=-1",
        ):
            response = client.get(f"{base}&{query}")
            assert response.status_code == 422, query
            assert "Raster nicht druckbar" in response.text, query


class TestCalibrationPage:
    def test_it_serves_the_100_mm_reference(self, client: TestClient) -> None:
        response = client.get("/etiketten/kalibrierung")

        assert response.status_code == 200
        assert "100 mm" in response.text
        assert 'class="calibration__ruler"' in response.text

        # Die Referenzstrecke ist nur so viel wert wie die Millimeterangabe im Stylesheet.
        stylesheet = client.get("/static/labels-print.css").text
        ruler = stylesheet.split(".calibration__ruler {", 1)[1].split("}", 1)[0]
        assert "width: 100mm" in ruler

    def test_it_explains_what_to_do_when_the_length_is_off(self, client: TestClient) -> None:
        response = client.get("/etiketten/kalibrierung")

        assert "100 %" in response.text
        assert "An Seite anpassen" in response.text


class TestPrintStylesheet:
    """Das Druck-CSS trägt die Maßhaltigkeit — hier stehen die Regeln, ohne die der Bogen kippt."""

    def _stylesheet(self, client: TestClient) -> str:
        response = client.get("/static/labels-print.css")
        assert response.status_code == 200
        return response.text

    def test_it_resets_box_sizing(self, client: TestClient) -> None:
        """Regression: Ohne `border-box` addiert der Innenabstand von `.label` auf die Zellgröße.

        Gefunden beim echten Rendern in M5: Aus 70 × 37 mm wurden 72,8 × 39,8 mm, weil dieses
        Stylesheet ohne `app.css` läuft und dessen Reset damit nicht greift. Jede Zeile des
        Bogens wäre über die Stanzung gelaufen — im Browser sichtbar, in einem HTML-Test nicht.
        """
        assert "box-sizing: border-box" in self._stylesheet(client)

    def test_it_sets_a4_without_extra_page_margin(self, client: TestClient) -> None:
        """Die Ränder stehen im Raster — der Druckdialog darf sie nicht ein zweites Mal addieren."""
        stylesheet = self._stylesheet(client)
        page_rule = stylesheet.split("@page {", 1)[1].split("}", 1)[0]

        assert "size: A4" in page_rule
        assert "margin: 0" in page_rule

    def test_a_sheet_is_exactly_one_a4_page_that_breaks_after(self, client: TestClient) -> None:
        stylesheet = self._stylesheet(client)
        sheet_rule = stylesheet.split(".sheet {", 1)[1].split("}", 1)[0]

        assert "width: 210mm" in sheet_rule
        assert "height: 297mm" in sheet_rule
        assert "break-after: page" in sheet_rule

    def test_the_toolbar_does_not_reach_the_paper(self, client: TestClient) -> None:
        """„Keine Buttons im Ausdruck“ (§9 M5)."""
        stylesheet = self._stylesheet(client)
        print_block = stylesheet.split("@media print {", 1)[1]
        toolbar_rule = print_block.split(".toolbar {", 1)[1].split("}", 1)[0]

        assert "display: none" in toolbar_rule
