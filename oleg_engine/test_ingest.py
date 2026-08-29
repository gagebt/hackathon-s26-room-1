from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import engine


class IngestTests(unittest.TestCase):
    @staticmethod
    def _write_three_sources(input_dir: Path) -> dict[str, bytes]:
        files = {
            "chat.txt": "[27.08 14:02] Имя: текст\n[27.08 14:03] Друг: ответ\n".encode(),
            "mail.eml": b"From: sender@example.com\nSubject: Status\nDate: Thu, 27 Aug 2026 14:02:00 +0000\n\nBody\n",
            "note.txt": "Простая заметка\nВторая строка\n".encode(),
        }
        input_dir.mkdir()
        for name, data in files.items():
            (input_dir / name).write_bytes(data)
        return files

    def test_reads_every_file_with_exact_text_and_byte_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            input_dir = Path(temp) / "input"
            files = self._write_three_sources(input_dir)

            sources = {source.path: source for source in engine.read_sources(input_dir)}

            self.assertEqual(set(sources), set(files))
            for name, data in files.items():
                self.assertEqual(sources[name].text, data.decode("utf-8-sig"))
                self.assertEqual(sources[name].sha256, hashlib.sha256(data).hexdigest())

    def test_chunks_are_deterministic_and_cover_every_line_exactly_once(self) -> None:
        text = "".join(f"line {number}\n" for number in range(1, 126))
        source = engine.SourceFile(
            "long.txt",
            Path("long.txt"),
            text,
            hashlib.sha256(text.encode()).hexdigest(),
            len(text.encode()),
            "other",
        )

        first_all, first_sent = engine._chunks(source, prefilter=False)
        second_all, second_sent = engine._chunks(source, prefilter=False)

        self.assertEqual((first_all, first_sent), (second_all, second_sent))
        self.assertEqual(first_all, first_sent)
        self.assertEqual("".join(chunk["text"] for chunk in first_all), text)
        covered_lines = [
            line
            for chunk in first_all
            for line in range(chunk["line_start"], chunk["line_end"] + 1)
        ]
        self.assertEqual(covered_lines, list(range(1, 126)))

    def test_coverage_records_all_files_and_sends_all_chunks_without_prefilter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            files = self._write_three_sources(input_dir)
            registry_path = root / "registry.json"

            with patch.object(
                engine,
                "call_model",
                return_value=({"candidates": []}, "fake", "fake-model"),
            ):
                engine.run_engine(
                    input_dir,
                    registry_path,
                    mode="sequential",
                    backend="fake",
                    model="fake-model",
                    now_arg="2026-08-29",
                    prefilter=False,
                    adjudicate=False,
                )

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual({item["path"] for item in registry["sources"]}, set(files))
            coverage = registry["runs"][-1]["coverage"]
            self.assertEqual(set(coverage), set(files))
            for record in coverage.values():
                self.assertEqual(record["chunks_sent"], record["chunks_total"])

    def test_non_utf8_byte_is_replaced_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            input_dir = Path(temp)
            raw = b"valid\ninvalid: \xff\n"
            (input_dir / "broken.txt").write_bytes(raw)

            sources = engine.read_sources(input_dir)

            self.assertEqual(len(sources), 1)
            self.assertIn("\ufffd", sources[0].text)
            self.assertEqual(sources[0].sha256, hashlib.sha256(raw).hexdigest())

    def test_empty_folder_yields_zero_files_without_model_call_or_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()

            self.assertEqual(engine.read_sources(input_dir), [])
            with patch.object(engine, "call_model") as call_model:
                result = engine.run_engine(
                    input_dir,
                    root / "registry.json",
                    mode="sequential",
                    backend="fake",
                    model="fake-model",
                    now_arg="2026-08-29",
                    prefilter=False,
                    adjudicate=False,
                )

            call_model.assert_not_called()
            self.assertEqual(result["created"], 0)
            self.assertEqual(result["updated"], 0)
            self.assertEqual(result["closed"], 0)


if __name__ == "__main__":
    unittest.main()
