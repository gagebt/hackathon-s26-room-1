from __future__ import annotations

import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from oleg_pipeline import room_engine


class RoomEngineTests(unittest.TestCase):
    def invoke(self, *args: object, returncode: int = 0) -> tuple[int, object]:
        argv = ["room_engine.py", *(str(arg) for arg in args)]
        completed = subprocess.CompletedProcess([], returncode)
        with patch.object(sys, "argv", argv), patch.object(
            room_engine.pathlib.Path, "exists", return_value=True
        ), patch.object(
            room_engine.subprocess, "run", return_value=completed
        ) as run:
            result = room_engine.main()
        return result, run

    def test_builds_cli_run_argv_with_default_today_and_root_cwd(self) -> None:
        root = pathlib.Path(room_engine.__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            input_dir = temp / "input"
            registry = temp / "output" / "reg.json"

            result, run = self.invoke("--input", input_dir, "--registry", registry)

            self.assertEqual(result, 0)
            run.assert_called_once_with(
                [
                    sys.executable,
                    str(root / "cli.py"),
                    "run",
                    "--input",
                    str(input_dir.resolve()),
                    "--today",
                    "2026-08-28",
                    "--registry",
                    str(registry.resolve()),
                    "--out",
                    str(registry.resolve().with_suffix(".md")),
                ],
                cwd=root,
            )

    def test_today_argument_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            _, run = self.invoke(
                "--input",
                temp / "input",
                "--registry",
                temp / "reg.json",
                "--today",
                "2031-04-05",
            )

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--today") + 1], "2031-04-05")

    def test_missing_cli_returns_2_with_one_line_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory).resolve()
            stderr = io.StringIO()
            argv = [
                "room_engine.py",
                "--input",
                str(root / "input"),
                "--registry",
                str(root / "reg.json"),
                "--room-root",
                str(root),
            ]
            with patch.object(sys, "argv", argv), patch.object(
                room_engine.subprocess, "run"
            ) as run, contextlib.redirect_stderr(stderr):
                result = room_engine.main()

            self.assertEqual(result, 2)
            self.assertEqual(
                stderr.getvalue(),
                f"room_engine: cli.py не найден в {root}; укажите --room-root\n",
            )
            run.assert_not_called()

    def test_creates_registry_parent_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            registry = temp / "new" / "nested" / "reg.json"

            def observe_parent(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
                self.assertTrue(registry.parent.is_dir())
                return subprocess.CompletedProcess([], 0)

            argv = [
                "room_engine.py",
                "--input",
                str(temp / "input"),
                "--registry",
                str(registry),
            ]
            with patch.object(sys, "argv", argv), patch.object(
                room_engine.pathlib.Path, "exists", return_value=True
            ), patch.object(
                room_engine.subprocess, "run", side_effect=observe_parent
            ):
                result = room_engine.main()

            self.assertEqual(result, 0)
            self.assertTrue(registry.parent.is_dir())

    def test_propagates_subprocess_return_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            result, _ = self.invoke(
                "--input",
                temp / "input",
                "--registry",
                temp / "reg.json",
                returncode=17,
            )

        self.assertEqual(result, 17)

    @unittest.expectedFailure
    def test_default_room_root_has_runnable_cli(self) -> None:
        """HIGH: documented default root has no cli.py, so normal use exits 2."""
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            argv = [
                "room_engine.py",
                "--input",
                str(temp / "input"),
                "--registry",
                str(temp / "reg.json"),
            ]
            completed = subprocess.CompletedProcess([], 0)
            with patch.object(sys, "argv", argv), patch.object(
                room_engine.subprocess, "run", return_value=completed
            ), contextlib.redirect_stderr(io.StringIO()):
                result = room_engine.main()

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
