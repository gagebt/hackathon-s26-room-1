from __future__ import annotations

import io
import json
import re
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from oleg_engine.__main__ import main
from oleg_engine.backend import BackendError


class CliTests(unittest.TestCase):
    def _invoke(
        self,
        input_dir: Path,
        registry_path: Path,
        *extra: str,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            "run",
            "--input",
            str(input_dir),
            "--registry",
            str(registry_path),
            "--now",
            "2026-08-29",
            *extra,
        ]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(argv)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def _fake_model(prompts: list[str] | None = None):
        lock = threading.Lock()

        def fake(
            prompt: str,
            schema: dict,
            backend: str,
            model: str | None,
            effort: str,
        ):
            if effort != "medium":
                raise AssertionError(f"unexpected default effort: {effort}")
            path = re.search(r"(?m)^SOURCE PATH: (.+)$", prompt).group(1)
            text = re.search(r"(?s)TEXT:\n(.*)\Z", prompt).group(1).rstrip("\n")
            with lock:
                if prompts is not None:
                    prompts.append(prompt)
            return (
                {
                    "candidates": [
                        {
                            "what": text,
                            "owner": None,
                            "due": None,
                            "due_text": "",
                            "kind": "task",
                            "recurrence": None,
                            "status": "open",
                            "derived_from_what": None,
                            "uncertainty": [],
                            "sources": [
                                {
                                    "path": path,
                                    "quote": text,
                                    "line_start": 1,
                                    "line_end": 1,
                                }
                            ],
                        }
                    ]
                },
                "fake",
                "fake-model",
            )

        return fake

    def test_missing_input_reports_one_line_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            code, stdout, stderr = self._invoke(
                root / "missing", root / "registry.json", "--json"
            )

        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertEqual(1, len(stderr.splitlines()))
        self.assertIn("input directory does not exist", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_run_writes_json_and_markdown_registries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "one.txt").write_text("Send report", encoding="utf-8")
            registry_path = root / "registry.json"
            with patch("oleg_engine.engine.call_model", self._fake_model()):
                code, _, stderr = self._invoke(
                    input_dir, registry_path, "--no-adjudicate"
                )

            self.assertEqual(0, code, stderr)
            self.assertTrue(registry_path.is_file())
            self.assertTrue((root / "registry.md").is_file())
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual("Send report", registry["obligations"][0]["what"])
            self.assertEqual("medium", registry["runs"][-1]["effort"])
            self.assertIn("Send report", (root / "registry.md").read_text(encoding="utf-8"))

    def test_json_flag_prints_machine_readable_counts_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "one.txt").write_text("Send report", encoding="utf-8")
            with patch("oleg_engine.engine.call_model", self._fake_model()):
                code, stdout, stderr = self._invoke(
                    input_dir,
                    root / "registry.json",
                    "--json",
                    "--no-adjudicate",
                )

        self.assertEqual(0, code, stderr)
        summary = json.loads(stdout)
        self.assertEqual(
            {"created": 1, "updated": 0, "closed": 0, "total_open": 1},
            {key: summary[key] for key in ("created", "updated", "closed", "total_open")},
        )
        self.assertEqual(1, len(stdout.splitlines()))

    def test_auto_uses_parallel_for_two_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "a.txt").write_text("Task A", encoding="utf-8")
            (input_dir / "b.txt").write_text("Task B", encoding="utf-8")
            registry_path = root / "registry.json"
            prompts: list[str] = []
            with patch("oleg_engine.engine.call_model", self._fake_model(prompts)):
                code, _, stderr = self._invoke(
                    input_dir, registry_path, "--mode", "auto", "--no-adjudicate"
                )

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(0, code, stderr)
            self.assertEqual(2, len(prompts))
            self.assertEqual("parallel", registry["runs"][-1]["mode"])

    def test_auto_uses_sequential_for_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "only.txt").write_text("Only task", encoding="utf-8")
            registry_path = root / "registry.json"
            prompts: list[str] = []
            with patch("oleg_engine.engine.call_model", self._fake_model(prompts)):
                code, _, stderr = self._invoke(
                    input_dir, registry_path, "--mode", "auto", "--no-adjudicate"
                )

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(0, code, stderr)
            self.assertEqual(1, len(prompts))
            self.assertEqual("sequential", registry["runs"][-1]["mode"])

    @unittest.expectedFailure
    def test_sequential_second_file_sees_registry_so_far(self) -> None:
        """MEDIUM defect: sequential extraction does not pass prior results forward."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "a.txt").write_text("Task from first", encoding="utf-8")
            (input_dir / "b.txt").write_text("Task from second", encoding="utf-8")
            prompts: list[str] = []
            with patch("oleg_engine.engine.call_model", self._fake_model(prompts)):
                code, _, stderr = self._invoke(
                    input_dir,
                    root / "registry.json",
                    "--mode",
                    "sequential",
                    "--no-adjudicate",
                )

        self.assertEqual(0, code, stderr)
        self.assertEqual(2, len(prompts))
        self.assertIn("Task from first", prompts[1])

    def test_backend_error_is_reported_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "one.txt").write_text("Send report", encoding="utf-8")
            with patch(
                "oleg_engine.engine.call_model",
                side_effect=BackendError("fake backend unavailable"),
            ):
                code, stdout, stderr = self._invoke(
                    input_dir, root / "registry.json", "--json", "--no-adjudicate"
                )

        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertEqual(["engine error: fake backend unavailable"], stderr.splitlines())
        self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    unittest.main()
