"""Focused tests for scenario discovery, selection, and engine template filling."""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oleg_pipeline import cli


def _make_scenario(examples: Path, name: str, expected: str) -> None:
    root = examples / name
    (root / "input").mkdir(parents=True)
    (root / "input" / "source.txt").write_text(name, encoding="utf-8")
    (root / "expected.md").write_text(expected, encoding="utf-8")


def _make_examples(base: Path) -> Path:
    examples = base / "examples"
    _make_scenario(examples, "03-c", "# Третий пример\n")
    _make_scenario(
        examples,
        "02-b",
        "# Второй пример\n\nОпорное время: 2026-09-01\n\n"
        "Он выполняется поверх реестра из примера 01.\n",
    )
    _make_scenario(examples, "01-a", "# Первый пример\n")
    (examples / "README.txt").write_text("не сценарий", encoding="utf-8")
    return examples


def _args(examples: Path, out: Path, only: str) -> argparse.Namespace:
    return argparse.Namespace(
        examples=str(examples),
        out=str(out),
        only=only,
        engine="engine {input} {registry} {now}",
        judge="none",
        jobs=1,
    )


class ScenarioDiscoveryTests(unittest.TestCase):
    def test_scenarios_are_sorted_and_stray_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenarios = cli.discover_scenarios(_make_examples(Path(tmp)))

        self.assertEqual([scenario.name for scenario in scenarios], ["01-a", "02-b", "03-c"])

    def test_reference_date_uses_exact_marker_and_absence_uses_default(self) -> None:
        class FixedDate(dt.date):
            @classmethod
            def today(cls) -> "FixedDate":
                return cls(2040, 1, 2)

        with tempfile.TemporaryDirectory() as tmp, patch.object(cli.dt, "date", FixedDate):
            scenarios = {item.name: item for item in cli.discover_scenarios(_make_examples(Path(tmp)))}

        self.assertEqual(scenarios["02-b"].now, "2026-09-01")
        self.assertEqual(scenarios["03-c"].now, "2040-01-02")


class ScenarioSelectionTests(unittest.TestCase):
    def _run_with_fake_engine(self, only: str) -> tuple[int, list[tuple[str, str | None, bool]], str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        examples = _make_examples(base)
        out = base / "out"
        observed: list[tuple[str, str | None, bool]] = []

        def fake_run(
            scenario: cli.Scenario,
            engine_template: str,
            out_dir: Path,
            requested_judge: str,
            parent: cli.Result | None,
            should_judge: bool,
        ) -> cli.Result:
            observed.append((scenario.name, parent.scenario.name if parent else None, should_judge))
            scenario_out = out_dir / scenario.name
            scenario_out.mkdir(parents=True, exist_ok=True)
            registry = scenario_out / "registry.json"
            registry_md = scenario_out / "registry.md"
            registry.write_text("{}", encoding="utf-8")
            registry_md.write_text("# registry\n", encoding="utf-8")
            return cli.Result(scenario, True, "ok", [], registry, registry_md, True, 0.0, "none")

        with patch.object(cli, "run_scenario", side_effect=fake_run):
            code = cli.run_pipeline(_args(examples, out, only))
        return code, observed, (out / "report.md").read_text(encoding="utf-8")

    def test_only_03_runs_only_03(self) -> None:
        code, observed, report = self._run_with_fake_engine("03")

        self.assertEqual(code, 0)
        self.assertEqual([item[0] for item in observed], ["03-c"])
        self.assertIn("`03-c`", report)
        self.assertNotIn("`01-a`", report)
        self.assertNotIn("`02-b`", report)

    def test_only_02_auto_includes_parent_01_but_reports_selection(self) -> None:
        code, observed, report = self._run_with_fake_engine("02")

        self.assertEqual(code, 0)
        self.assertEqual(observed, [("01-a", None, False), ("02-b", "01-a", True)])
        self.assertIn("`02-b`", report)
        self.assertNotIn("`01-a`", report)


class TemplateFillingTests(unittest.TestCase):
    def test_input_registry_and_now_are_substituted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            scenario = cli.discover_scenarios(_make_examples(base))[1]
            registry = (base / "output dir" / "registry.json").resolve()
            command = cli.render_engine_command(
                "engine --input {input} --registry {registry} --now {now}", scenario, registry
            )

        self.assertIn(str(scenario.input_dir.resolve()), command)
        self.assertIn(str(registry), command)
        self.assertIn("2026-09-01", command)
        self.assertNotIn("{input}", command)
        self.assertNotIn("{registry}", command)
        self.assertNotIn("{now}", command)

    def test_template_without_registry_is_rejected_before_process_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            scenario = cli.discover_scenarios(_make_examples(base))[0]
            with patch.object(cli, "_run_process") as run_process:
                result = cli.run_scenario(
                    scenario,
                    "engine {input}",
                    base / "out",
                    "none",
                    None,
                    True,
                )

        self.assertFalse(result.passed)
        self.assertIn("обязательные placeholders", result.reason)
        self.assertIn("{registry}", result.reason)
        run_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
