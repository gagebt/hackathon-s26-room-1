"""Tests for report rendering and the ``--judge none`` CLI mode."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from oleg_pipeline import cli


def _make_scenario(examples: Path, name: str) -> None:
    root = examples / name
    (root / "input").mkdir(parents=True)
    (root / "input" / "source.txt").write_text(f"source for {name}\n", encoding="utf-8")
    (root / "expected.md").write_text("# Expected\n", encoding="utf-8")


class ReportCliTests(unittest.TestCase):
    def _run(
        self,
        base: Path,
        verdicts: dict[str, dict[str, object]],
        *,
        judge: str = "codex",
    ) -> tuple[int, str, str]:
        examples = base / "examples"
        out = base / "out"
        for name in verdicts:
            _make_scenario(examples, name)

        def fake_engine(command: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            rendered = str(command)
            name = next(name for name in verdicts if name in rendered)
            scenario_out = out / name
            scenario_out.mkdir(parents=True, exist_ok=True)
            (scenario_out / "registry.json").write_text(json.dumps({"scenario": name}), encoding="utf-8")
            (scenario_out / "registry.md").write_text(f"# Registry {name}\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="engine ok", stderr="")

        def fake_judge(
            scenario: cli.Scenario,
            _registry_md: str,
            _requested: str,
            _work_dir: Path,
        ) -> tuple[dict[str, object], str]:
            return verdicts[scenario.name], "fake"

        stdout = io.StringIO()
        with (
            patch.object(cli, "_run_process", side_effect=fake_engine),
            patch.object(cli, "judge", side_effect=fake_judge) as judge_mock,
            contextlib.redirect_stdout(stdout),
        ):
            code = cli.main(
                [
                    "run",
                    "--examples",
                    str(examples),
                    "--engine",
                    "fake-engine {input} {registry}",
                    "--judge",
                    judge,
                    "--out",
                    str(out),
                    "--jobs",
                    "1",
                ]
            )
        if judge == "none":
            judge_mock.assert_not_called()
        report = (out / "report.md").read_text(encoding="utf-8")
        return code, stdout.getvalue(), report

    def test_report_has_summary_rows_reasons_facts_and_matching_final_line(self) -> None:
        verdicts = {
            "01-pass": {
                "pass": True,
                "reason": "all required facts are present",
                "facts": [{"fact": "owner is recorded", "ok": True}],
            },
            "02-fail": {
                "pass": False,
                "reason": "deadline is absent",
                "facts": [
                    {"fact": "task is recorded", "ok": True},
                    {"fact": "deadline is recorded", "ok": False},
                ],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, report = self._run(Path(tmp), verdicts)

        self.assertEqual(code, 1)
        summary = "прошло 1 из 2"
        self.assertIn(f"- Итог: **{summary}**", report)
        self.assertIn("| `01-pass` | PASS | all required facts are present |", report)
        self.assertIn("| `02-fail` | FAIL | deadline is absent |", report)
        self.assertEqual(report.count("| `01-pass` |"), 1)
        self.assertEqual(report.count("| `02-fail` |"), 1)
        self.assertIn("  - OK: owner is recorded", report)
        self.assertIn("  - OK: task is recorded", report)
        self.assertIn("  - FAIL: deadline is recorded", report)
        self.assertEqual(stdout.rstrip().splitlines()[-1], summary)

    def test_all_semantic_scenarios_pass_with_exit_code_zero(self) -> None:
        verdicts = {
            "01-pass": {
                "pass": True,
                "reason": "accepted",
                "facts": [{"fact": "required fact", "ok": True}],
            },
            "02-pass": {
                "pass": True,
                "reason": "accepted too",
                "facts": [{"fact": "second required fact", "ok": True}],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, report = self._run(Path(tmp), verdicts)

        self.assertEqual(code, 0)
        self.assertIn("- Итог: **прошло 2 из 2**", report)
        self.assertEqual(stdout.rstrip().splitlines()[-1], "прошло 2 из 2")

    def test_judge_none_reports_engine_counts_without_semantic_pass(self) -> None:
        engine_cases = {
            "01-engine": {"pass": False, "reason": "must not be used", "facts": []},
            "02-engine": {"pass": False, "reason": "must not be used", "facts": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, report = self._run(Path(tmp), engine_cases, judge="none")

        self.assertEqual(code, 0)
        self.assertIn("движок успешно 2 из 2", stdout)
        self.assertNotIn("PASS", stdout)
        self.assertIn("- Движок: **успешно 2 из 2**", report)
        self.assertIn("| `01-engine` | ENGINE OK |", report)
        self.assertIn("| `02-engine` | ENGINE OK |", report)


if __name__ == "__main__":
    unittest.main()
