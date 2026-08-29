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

    @unittest.expectedFailure
    def test_missing_registry_query_returns_json_error_without_traceback(self) -> None:
        """HIGH defect: ?registry is ignored, so the default data is returned."""
        missing = Path(self.temp_dir.name) / "missing.json"

        response = self.client.get("/api/registry", params={"registry": str(missing)})

        self.assertEqual(200, response.status_code)
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
