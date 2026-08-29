from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from oleg_engine import backend


SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def completed(args: list[str], *, stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


class BackendJsonTests(unittest.TestCase):
    def test_codex_reads_valid_json_from_output_file(self) -> None:
        expected = {"answer": "from codex"}

        def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            self.assertIn("model_reasoning_effort=medium", args)
            output_path = args[args.index("-o") + 1]
            with open(output_path, "w", encoding="utf-8") as output:
                json.dump(expected, output)
            return completed(args, stdout="progress that is not the answer")

        with patch("oleg_engine.backend.subprocess.run", side_effect=fake_run):
            result = backend._run_codex("prompt", SCHEMA, "test-model", "medium")

        self.assertEqual(expected, result)

    def test_claude_json_envelope_result_string_is_decoded(self) -> None:
        expected = {"answer": "from claude"}
        envelope = json.dumps({"result": json.dumps(expected)})

        with patch(
            "oleg_engine.backend.subprocess.run",
            return_value=completed(["claude"], stdout=envelope),
        ):
            result = backend._run_claude("prompt", "opus", SCHEMA)

        self.assertEqual(expected, result)

    @unittest.expectedFailure
    def test_claude_single_element_array_wrapping_object_is_unwrapped(self) -> None:
        """MEDIUM defect: a valid Claude result wrapped in a one-item array is rejected."""
        expected = {"answer": "wrapped"}
        envelope = json.dumps({"result": json.dumps([expected])})

        with patch(
            "oleg_engine.backend.subprocess.run",
            return_value=completed(["claude"], stdout=envelope),
        ):
            result = backend._run_claude("prompt", "opus", SCHEMA)

        self.assertEqual(expected, result)

    @unittest.expectedFailure
    def test_invalid_codex_json_retries_once_and_reports_rejected_prefix(self) -> None:
        """MEDIUM defect: Codex parse errors omit the rejected output prefix."""
        rejected = "not-json-output-from-codex"

        with patch(
            "oleg_engine.backend.subprocess.run",
            return_value=completed(["codex"], stdout=rejected),
        ) as run:
            with self.assertRaises(backend.BackendError) as raised:
                backend._run_codex("prompt", SCHEMA, "test-model", "medium")

        self.assertEqual(2, run.call_count)
        self.assertIn(rejected[:12], str(raised.exception))

    def test_failed_codex_and_claude_produce_combined_named_error(self) -> None:
        responses = [
            completed(["codex"], returncode=1, stderr="codex first failure"),
            completed(["codex"], returncode=1, stderr="codex second failure"),
            completed(["claude"], returncode=1, stderr="claude failure"),
        ]

        with patch("oleg_engine.backend.subprocess.run", side_effect=responses) as run:
            with self.assertRaises(backend.BackendError) as raised:
                backend.call_model("prompt", SCHEMA, "codex", "test-model")

        message = str(raised.exception)
        self.assertEqual(3, run.call_count)
        self.assertIn("codex failed twice", message)
        self.assertIn("claude failed", message)

    @unittest.expectedFailure
    def test_missing_required_schema_key_is_rejected(self) -> None:
        """HIGH defect: object responses are accepted without required schema keys."""
        envelope = json.dumps({"result": json.dumps({"different": "value"})})

        with patch(
            "oleg_engine.backend.subprocess.run",
            return_value=completed(["claude"], stdout=envelope),
        ):
            with self.assertRaises(backend.BackendError):
                backend._run_claude("prompt", "opus", SCHEMA)


if __name__ == "__main__":
    unittest.main()
