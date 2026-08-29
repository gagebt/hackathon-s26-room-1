"""Focused tests for the web server run and download endpoints."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx  # noqa: F401 - verifies the supported in-process client is available
from fastapi.testclient import TestClient

from oleg_web import server


class _FinishedProcess:
    def __init__(self, output: str = "engine completed\n", returncode: int = 0) -> None:
        self.stdout = io.StringIO(output)
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode


class ServerRunDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        server.RUNS.clear()
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)

    def _finished_run(self, run_id: str) -> dict:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            response = self.client.get(f"/api/run/{run_id}")
            self.assertEqual(200, response.status_code)
            status = response.json()
            if status["done"]:
                return status
            time.sleep(0.005)
        self.fail(f"run {run_id} did not finish")

    def test_download_markdown_returns_exact_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.md"
            expected = "# Registry\n\n- café\n".encode("utf-8")
            path.write_bytes(expected)

            response = self.client.get("/api/download", params={"kind": "md", "path": str(path)})

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
        self.assertEqual(expected, response.content)

    def test_download_json_returns_exact_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            expected = b'{"obligations":[{"id":"row-1"}]}\n'
            path.write_bytes(expected)

            response = self.client.get("/api/download", params={"kind": "json", "path": str(path)})

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        self.assertEqual(expected, response.content)

    def test_download_missing_file_returns_one_line_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.md"
            response = self.client.get("/api/download", params={"kind": "md", "path": str(missing)})

        self.assertEqual(404, response.status_code)
        self.assertEqual(f"Файл не найден: {missing}", response.text)
        self.assertEqual(1, len(response.text.splitlines()))

    def test_download_rejects_unsupported_kind(self) -> None:
        """MEDIUM defect: unsupported download kinds fall through to Markdown."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.md"
            path.write_text("secret markdown", encoding="utf-8")
            response = self.client.get("/api/download", params={"kind": "exe", "path": str(path)})

        self.assertEqual(400, response.status_code)
        self.assertIn("kind", response.text.lower())

    def test_run_spawn_failure_reports_readable_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "input"
            input_dir.mkdir()
            registry = Path(tmp) / "registry.json"
            with patch.object(server.subprocess, "Popen", side_effect=FileNotFoundError("nonexistent-binary-xyz")):
                response = self.client.post(
                    "/api/run",
                    json={
                        "input": str(input_dir),
                        "registry": str(registry),
                        "engine_cmd": "nonexistent-binary-xyz {input} {registry}",
                    },
                )
                self.assertEqual(200, response.status_code)
                status = self._finished_run(response.json()["run"])

        self.assertEqual(-1, status["exit"])
        self.assertIn("nonexistent-binary-xyz", status["error"])
        rendered = "\n".join(status["lines"] + [status["error"]])
        self.assertNotIn("Traceback", rendered)
        self.assertEqual(1, len(status["error"].splitlines()))

    def test_failed_fresh_run_restores_existing_registry_and_markdown(self) -> None:
        """HIGH audit regression: a failed fresh run must not erase the current result."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            input_dir.mkdir()
            registry = root / "registry.json"
            report = root / "registry.md"
            old_json = b'{"obligations":[{"id":"keep-me"}]}'
            old_md = b"# keep me\n"
            registry.write_bytes(old_json)
            report.write_bytes(old_md)
            with patch.object(server.subprocess, "Popen", side_effect=FileNotFoundError("broken-fresh")):
                response = self.client.post(
                    "/api/run",
                    json={
                        "input": str(input_dir),
                        "registry": str(registry),
                        "engine_cmd": "broken-fresh {input} {registry}",
                        "fresh": True,
                    },
                )
                status = self._finished_run(response.json()["run"])

            self.assertEqual(-1, status["exit"])
            self.assertEqual(old_json, registry.read_bytes())
            self.assertEqual(old_md, report.read_bytes())
            self.assertEqual([], list(root.glob("*.bak")))

    def test_fake_engine_run_substitutes_all_placeholders_and_updates_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            input_dir.mkdir()
            registry = root / "registry.json"
            report = root / "registry.md"
            fake_script = root / "fake.py"
            fake_script.write_text(
                "# Test fixture: the patched Popen boundary simulates this engine.\n",
                encoding="utf-8",
            )
            expected_registry = {"obligations": [{"id": "new-row", "what": "from fake engine"}]}
            captured: list[list[str]] = []

            def fake_popen(cmd, **kwargs):
                captured.append(list(cmd))
                Path(cmd[3]).write_text(json.dumps(expected_registry), encoding="utf-8")
                Path(cmd[4]).write_text("# generated\n", encoding="utf-8")
                return _FinishedProcess('{"written": 1}\n')

            template = f'"{sys.executable}" "{fake_script}" {{input}} {{registry}} {{out}} {{now}}'
            with patch.object(server.subprocess, "Popen", side_effect=fake_popen):
                response = self.client.post(
                    "/api/run",
                    json={
                        "input": str(input_dir),
                        "registry": str(registry),
                        "engine_cmd": template,
                        "now": "2031-02-03",
                    },
                )
                self.assertEqual(200, response.status_code)
                status = self._finished_run(response.json()["run"])
                registry_response = self.client.get("/api/registry", params={"path": str(registry)})

        self.assertTrue(status["done"])
        self.assertEqual(0, status["exit"])
        self.assertIsNone(status["error"])
        self.assertEqual(
            [sys.executable, str(fake_script), str(input_dir), str(registry), str(report), "2031-02-03"],
            captured[0],
        )
        self.assertEqual(200, registry_response.status_code)
        self.assertTrue(registry_response.json()["ok"])
        self.assertEqual(expected_registry["obligations"], registry_response.json()["registry"]["obligations"])


if __name__ == "__main__":
    unittest.main()
