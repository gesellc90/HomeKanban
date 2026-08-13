from __future__ import annotations

import json

from fastapi.testclient import TestClient


class TestPage:
    def test_returns_200_with_zero_counts_when_empty(self, client: TestClient) -> None:
        response = client.get("/stammdaten")

        assert response.status_code == 200
        assert "0 Artikel, 0 Kategorien, 0 Läden" in response.text


class TestExport:
    def test_json_export_has_attachment_headers_and_content(self, client: TestClient) -> None:
        client.post(
            "/artikel",
            data={
                "name": "Kaffee",
                "unit": "Packung",
                "stock": "2",
                "reorder_level": "1",
                "target_stock": "3",
                "pack_size": "1",
                "lead_days": "7",
            },
        )

        response = client.get("/stammdaten/export.json")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert "attachment" in response.headers["content-disposition"]
        payload = json.loads(response.text)
        assert payload["items"][0]["name"] == "Kaffee"
        assert payload["items"][0]["stock"] == 2

    def test_csv_export_has_attachment_headers_and_header_row(self, client: TestClient) -> None:
        response = client.get("/stammdaten/export.csv")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        assert response.text.splitlines()[0] == (
            "name,unit,note,stock,reorder_level,target_stock,pack_size,lead_days,category,store"
        )


class TestImportJson:
    def test_valid_file_into_empty_database_redirects_and_creates_items(
        self, client: TestClient
    ) -> None:
        payload = {
            "categories": ["Getränke"],
            "stores": [],
            "items": [
                {
                    "name": "Kaffee",
                    "unit": "Packung",
                    "note": None,
                    "stock": 2,
                    "reorder_level": 1,
                    "target_stock": 3,
                    "pack_size": 1,
                    "lead_days": 7,
                    "category": "Getränke",
                    "store": None,
                }
            ],
        }

        response = client.post(
            "/stammdaten/import",
            files={"file": ("stammdaten.json", json.dumps(payload), "application/json")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/stammdaten"

        page = client.get("/stammdaten")
        assert "1 Artikel, 1 Kategorien, 0 Läden" in page.text
        board = client.get("/")
        assert "Kaffee" in board.text

    def test_conflicting_item_name_is_rejected_and_nothing_changes(
        self, client: TestClient
    ) -> None:
        client.post(
            "/artikel",
            data={
                "name": "Kaffee",
                "unit": "Packung",
                "stock": "1",
                "reorder_level": "1",
                "target_stock": "2",
                "pack_size": "1",
                "lead_days": "7",
            },
        )
        payload = {
            "categories": [],
            "stores": [],
            "items": [
                {
                    "name": "Kaffee",
                    "unit": "Packung",
                    "note": None,
                    "stock": 1,
                    "reorder_level": 1,
                    "target_stock": 2,
                    "pack_size": 1,
                    "lead_days": 7,
                    "category": None,
                    "store": None,
                }
            ],
        }

        response = client.post(
            "/stammdaten/import",
            files={"file": ("stammdaten.json", json.dumps(payload), "application/json")},
        )

        assert response.status_code == 409
        assert "existiert bereits" in response.text
        page = client.get("/stammdaten")
        assert "1 Artikel, 0 Kategorien, 0 Läden" in page.text  # unverändert, nicht doppelt

    def test_broken_json_is_rejected_with_german_message_and_no_traceback(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/stammdaten/import",
            files={"file": ("stammdaten.json", "kein json{", "application/json")},
        )

        assert response.status_code == 422
        assert "kein gültiges JSON" in response.text
        assert "Traceback" not in response.text

    def test_unknown_top_level_field_is_rejected(self, client: TestClient) -> None:
        payload = '{"categories": [], "stores": [], "items": [], "movements": []}'

        response = client.post(
            "/stammdaten/import",
            files={"file": ("stammdaten.json", payload, "application/json")},
        )

        assert response.status_code == 422
        assert "Unbekannte Felder" in response.text


class TestImportCsv:
    def test_valid_csv_into_empty_database_redirects_and_creates_items(
        self, client: TestClient
    ) -> None:
        csv_text = (
            "name,unit,note,stock,reorder_level,target_stock,pack_size,lead_days,category,store\n"
            "Kaffee,Packung,,2,1,3,1,7,Getränke,\n"
        )

        response = client.post(
            "/stammdaten/import",
            files={"file": ("stammdaten.csv", csv_text, "text/csv")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        page = client.get("/stammdaten")
        assert "1 Artikel, 1 Kategorien, 0 Läden" in page.text

    def test_truncated_row_is_rejected_and_nothing_written(self, client: TestClient) -> None:
        csv_text = (
            "name,unit,note,stock,reorder_level,target_stock,pack_size,lead_days,category,store\n"
            "Kaffee,Packung\n"
        )

        response = client.post(
            "/stammdaten/import", files={"file": ("stammdaten.csv", csv_text, "text/csv")}
        )

        assert response.status_code == 422
        page = client.get("/stammdaten")
        assert "0 Artikel, 0 Kategorien, 0 Läden" in page.text


class TestImportMisc:
    def test_unknown_file_extension_is_rejected_with_german_message(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/stammdaten/import",
            files={"file": ("stammdaten.txt", "irrelevant", "text/plain")},
        )

        assert response.status_code == 422
        assert "Unbekanntes Dateiformat" in response.text

    def test_non_utf8_bytes_are_rejected_with_german_message(self, client: TestClient) -> None:
        response = client.post(
            "/stammdaten/import",
            files={"file": ("stammdaten.json", b"\xff\xfe\x00\x01", "application/json")},
        )

        assert response.status_code == 422
        assert "UTF-8" in response.text
