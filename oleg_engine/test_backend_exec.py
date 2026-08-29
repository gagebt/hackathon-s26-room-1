from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from oleg_engine import backend


class ExecutableResolutionTests(unittest.TestCase):
    def _write_cmd(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        command = directory / "codex.cmd"
        command.write_text("@exit /b 0\r\n", encoding="utf-8")
        return command

    def test_executable_finds_codex_cmd_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            command = self._write_cmd(Path(temp))
            with patch.dict(backend.os.environ, {"PATH": temp}, clear=True):
                resolved, use_shell = backend._executable("codex")

        self.assertEqual(os.path.normcase(resolved), os.path.normcase(str(command)))
        self.assertFalse(use_shell)

    def test_executable_finds_codex_cmd_in_each_fallback_directory(self) -> None:
        fallback_names = (("bin",), (".local", "bin"), ("npm",))
        for fallback_name in fallback_names:
            with self.subTest(fallback=os.path.join(*fallback_name)):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    home = root / "home"
                    appdata = root / "appdata"
                    directory = appdata.joinpath(*fallback_name) if fallback_name == ("npm",) else home.joinpath(*fallback_name)
                    command = self._write_cmd(directory)
                    environment = {
                        "PATH": "",
                        "USERPROFILE": str(home),
                        "HOME": str(home),
                        "APPDATA": str(appdata),
                    }
                    with patch.dict(backend.os.environ, environment, clear=True):
                        resolved, use_shell = backend._executable("codex")

                self.assertEqual(os.path.normcase(resolved), os.path.normcase(str(command)))
                self.assertFalse(use_shell)

    @unittest.expectedFailure
    def test_missing_executable_error_names_searched_locations(self) -> None:
        """MEDIUM defect: a missing executable does not raise with searched locations."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            appdata = root / "appdata"
            environment = {
                "PATH": "",
                "USERPROFILE": str(home),
                "HOME": str(home),
                "APPDATA": str(appdata),
            }
            with patch.dict(backend.os.environ, environment, clear=True):
                with self.assertRaises(backend.BackendError) as raised:
                    backend._executable("codex")

        message = str(raised.exception)
        self.assertIn(str(home / "bin"), message)
        self.assertIn(str(home / ".local" / "bin"), message)
        self.assertIn(str(appdata / "npm"), message)


class ChildEnvironmentTests(unittest.TestCase):
    @staticmethod
    def _completed_process() -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    def test_subprocess_environment_fills_missing_windows_variables(self) -> None:
        home = Path(r"C:\Users\backend-test")
        with (
            patch.dict(backend.os.environ, {}, clear=True),
            patch.object(backend.Path, "home", return_value=home),
            patch.object(backend, "_executable", return_value=("claude.cmd", False)),
            patch.object(backend.subprocess, "run", return_value=self._completed_process()) as run,
        ):
            result = backend._run_claude("prompt", "opus", {"type": "object"})

        child_env = run.call_args.kwargs["env"]
        expected = {
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "TEMP": str(home / "AppData" / "Local" / "Temp"),
            "TMP": str(home / "AppData" / "Local" / "Temp"),
            "HOME": str(home),
            "SYSTEMROOT": r"C:\Windows",
            "COMSPEC": r"C:\Windows\System32\cmd.exe",
        }
        self.assertEqual(result, {"ok": True})
        self.assertEqual({name: child_env[name] for name in expected}, expected)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")

    def test_subprocess_environment_preserves_existing_windows_variables(self) -> None:
        existing = {
            "APPDATA": r"D:\profile\roaming",
            "LOCALAPPDATA": r"D:\profile\local",
            "TEMP": r"D:\scratch\temp",
            "TMP": r"D:\scratch\tmp",
            "HOME": r"D:\home",
            "SYSTEMROOT": r"D:\Windows",
            "COMSPEC": r"D:\Windows\System32\cmd.exe",
            "PATH": r"D:\tools",
        }
        with (
            patch.dict(backend.os.environ, existing, clear=True),
            patch.object(backend, "_executable", return_value=("claude.cmd", False)),
            patch.object(backend.subprocess, "run", return_value=self._completed_process()) as run,
        ):
            backend._run_claude("prompt", "opus", {"type": "object"})

        child_env = run.call_args.kwargs["env"]
        self.assertEqual({name: child_env[name] for name in existing if name != "PATH"}, {name: value for name, value in existing.items() if name != "PATH"})


if __name__ == "__main__":
    unittest.main()
