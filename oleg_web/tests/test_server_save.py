"""Contract tests for the web registry save endpoint."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from oleg_web import server


class SaveEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.registry = Path(self.temp_dir.name) / "registry.json"
        shutil.copyfile(server.SAMPLE_REGISTRY, self.registry)
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def _sha256(self) -> str:
        return hashlib.sha256(self.registry.read_bytes()).hexdigest()

    def _save(self, edits: list[dict[str, object]], features: str = "edit"):
        return self.client.post(
            "/api/save",
            params={"features": features},
            json={"path": str(self.registry), "edits": edits},
        )

    def _row_from_disk(self, obligation_id: str) -> dict[str, object]:
        data = json.loads(self.registry.read_text(encoding="utf-8"))
        return next(row for row in data["obligations"] if row["id"] == obligation_id)

    def test_save_is_forbidden_and_file_unchanged_when_edit_is_disabled(self) -> None:
        before = self._sha256()

        response = self._save(
            [{"id": "ob_0001", "owner": "Новый владелец"}],
            features="-edit",
        )

        self.assertEqual(403, response.status_code)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(before, self._sha256())

    def test_enabled_save_persists_fields_history_and_fresh_get(self) -> None:
        response = self._save(
            [{
                "id": "ob_0001",
                "owner": "Анна",
                "due": "2026-10-01",
                "status": "done",
            }]
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.json()["changed"])
        row = self._row_from_disk("ob_0001")
        self.assertEqual("Анна", row["owner"])
        self.assertEqual("2026-10-01", row["due"])
        self.assertEqual("done", row["status"])
        self.assertIs(True, row["manual"])
        changes = [item for item in row["history"] if item.get("change") == "manual_edit"]
        self.assertEqual(
            [
                ("owner", "родитель", "Анна"),
                ("due", "2026-09-05", "2026-10-01"),
                ("status", "open", "done"),
            ],
            [(item["field"], item["from"], item["to"]) for item in changes],
        )

        fresh = self.client.get("/api/registry", params={"path": str(self.registry)})
        self.assertEqual(200, fresh.status_code)
        fresh_row = next(
            item for item in fresh.json()["registry"]["obligations"]
            if item["id"] == "ob_0001"
        )
        self.assertEqual(
            ("Анна", "2026-10-01", "done"),
            (fresh_row["owner"], fresh_row["due"], fresh_row["status"]),
        )

    @unittest.expectedFailure
    def test_malformed_json_returns_400_json(self) -> None:
        """HIGH defect: malformed save JSON returns 500 instead of client error 400."""
        response = self.client.post(
            "/api/save",
            params={"features": "edit"},
            content=b'{"path":',
            headers={"content-type": "application/json"},
        )

        self.assertEqual(400, response.status_code)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)

    @unittest.expectedFailure
    def test_unknown_id_returns_error_and_does_not_rewrite_file(self) -> None:
        """HIGH defect: an unknown ID returns success and rewrites the registry."""
        before = self._sha256()

        response = self._save([{"id": "ob_missing", "status": "done"}])

        self.assertGreaterEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(before, self._sha256())

    def test_two_saves_keep_both_edits(self) -> None:
        first = self._save([{"id": "ob_0001", "owner": "Анна"}])
        second = self._save([{"id": "ob_0002", "status": "done"}])

        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertEqual("Анна", self._row_from_disk("ob_0001")["owner"])
        self.assertEqual("done", self._row_from_disk("ob_0002")["status"])
        self.assertTrue(self._row_from_disk("ob_0001")["manual"])
        self.assertTrue(self._row_from_disk("ob_0002")["manual"])


if __name__ == "__main__":
    unittest.main()
