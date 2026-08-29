"""Read-only HTTP contract tests for :mod:`oleg_web.server`."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from oleg_web import server


class ServerReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.registry = Path(self.temp_dir.name) / "registry.json"
        shutil.copyfile(server.SAMPLE_REGISTRY, self.registry)
        self.sample = json.loads(self.registry.read_text(encoding="utf-8"))
        self.default_registry = patch.object(server, "DEFAULT_REGISTRY", self.registry)
        self.default_registry.start()
        self.addCleanup(self.default_registry.stop)
        self.client = TestClient(server.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def test_registry_returns_every_sample_row_with_display_fields(self) -> None:
        response = self.client.get("/api/registry")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertTrue(payload["ok"])
        actual = payload["registry"]["obligations"]
        expected = self.sample["obligations"]
        self.assertEqual(len(expected), len(actual))
        fields = ("what", "owner", "due", "status", "sources")
        self.assertEqual(
            [{key: row[key] for key in fields} for row in expected],
            [{key: row[key] for key in fields} for row in actual],
        )

    def test_graph_registry_is_served_as_flat_room_cli_rows(self) -> None:
        graph = {
            "nodes": {
                "source": [{"id": "src-1", "kind": "email", "name": "письмо.txt"}],
                "chunk": [{
                    "id": "ch-1", "text": "Контекст", "quote": "точная цитата",
                    "source_id": "src-1",
                }],
                "commitment": [
                    {
                        "id": "c-1", "key": "send", "what": "Отправить ответ",
                        "owner": "Олег", "due": "2026-09-01", "due_raw": "до 1 сентября",
                        "deadline": {"raw": "до 1 сентября", "date": "2026-09-01"},
                        "kind": "task", "status": "open", "uncertainty": [],
                    },
                    {
                        "id": "c-2", "key": "meeting", "what": "Встреча команды",
                        "owner": None, "due": "2026-09-02", "deadline": {},
                        "kind": "event", "status": "done", "uncertainty": [],
                    },
                ],
            },
            "edges": [{"src": "c-1", "type": "EVIDENCED_BY", "dst": "ch-1"}],
            "events": [],
        }
        self.registry.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")

        response = self.client.get("/api/registry", params={"path": str(self.registry)})

        self.assertEqual(200, response.status_code)
        rows = response.json()["registry"]["obligations"]
        self.assertEqual(2, len(rows))
        self.assertEqual(
            ("Отправить ответ", "Олег", "2026-09-01", "open"),
            (rows[0]["what"], rows[0]["owner"], rows[0]["due"], rows[0]["status"]),
        )
        self.assertEqual(
            [{"path": "письмо.txt", "quote": "точная цитата", "source_kind": "email"}],
            rows[0]["sources"],
        )
        self.assertEqual([], rows[1]["sources"])
        self.assertTrue(all(row["imported_from"] == "room-cli" for row in rows))

    def test_unknown_registry_shape_returns_one_readable_error(self) -> None:
        self.registry.write_text('{"unexpected": true}', encoding="utf-8")

        response = self.client.get("/api/registry", params={"path": str(self.registry)})

        self.assertEqual(422, response.status_code)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(
            "Неподдерживаемая форма реестра: ожидается obligations[] или граф nodes/edges.",
            payload["error"],
        )

    def test_missing_registry_query_returns_json_error_without_traceback(self) -> None:
        """HIGH defect: ?registry is ignored, so the default data is returned."""
        missing = Path(self.temp_dir.name) / "missing.json"

        response = self.client.get("/api/registry", params={"registry": str(missing)})

        self.assertEqual(404, response.status_code)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)
        self.assertNotIn("traceback", response.text.lower())

    def test_index_serves_html_with_app_title(self) -> None:
        response = self.client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("<title>Реестр обязательств</title>", response.text)

    def test_config_lists_features_and_query_can_remove_timeline(self) -> None:
        with (
            patch.object(server, "engine_dir", return_value=None),
            patch.object(server, "pipeline_dir", return_value=None),
            patch.object(server, "cli_path", return_value=None),
            patch.object(server, "discover_examples", return_value=[]),
            patch.object(server, "examples_roots", return_value=[]),
            patch.object(server.shutil, "which", return_value=None),
        ):
            response = self.client.get("/api/config", params={"features": "all,-timeline"})

        self.assertEqual(200, response.status_code)
        features = response.json()["features"]
        self.assertEqual({"timeline", "edit", "run_examples"}, set(features))
        self.assertFalse(features["timeline"])
        self.assertTrue(features["edit"])
        self.assertTrue(features["run_examples"])

    def test_unknown_path_returns_404_without_stack_trace(self) -> None:
        response = self.client.get("/this-path-does-not-exist")

        self.assertEqual(404, response.status_code)
        self.assertIn(response.headers["content-type"].split(";")[0], {"application/json", "text/html"})
        self.assertNotIn("traceback", response.text.lower())


if __name__ == "__main__":
    unittest.main()
