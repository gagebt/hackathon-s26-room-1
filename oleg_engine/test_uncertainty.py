from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .engine import SourceFile, _merge_final, _normalize_items, render_markdown, run_engine


class UncertaintyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_uncertainty = [{
            "field": "due",
            "note": "Неясно, включена ли пятница",
            "strength": "high",
            "alternatives": ["2026-08-28", "2026-08-29"],
        }]
        self.new_uncertainty = [{
            "field": "owner",
            "note": "Два участника с именем Павел",
            "strength": "medium",
            "alternatives": ["Павел Орлов", "Павел Сидоров"],
        }]

    @staticmethod
    def _raw_item(
        quote: str,
        uncertainty: list[dict[str, object]],
        *,
        path: str = "source.txt",
        match_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "match_id": match_id,
            "what": "Отправить отчёт",
            "owner": "Павел",
            "due": "2026-08-29",
            "due_text": "до пятницы",
            "kind": "task",
            "recurrence": None,
            "status": "open",
            "derived_from_what": None,
            "uncertainty": uncertainty,
            "sources": [{"path": path, "quote": quote, "line_start": 1, "line_end": 1}],
        }

    @staticmethod
    def _render_item(uncertainty: list[dict[str, object]]) -> dict[str, object]:
        return {
            "id": "ob_0001",
            "what": "Отправить отчёт",
            "owner": "Павел",
            "due": "2026-08-29",
            "due_text": "до пятницы",
            "kind": "task",
            "recurrence": None,
            "status": "open",
            "derived_from": None,
            "uncertainty": uncertainty,
            "sources": [{"path": "source.txt", "quote": "Отправить отчёт", "line_start": 1, "line_end": 1}],
            "history": [],
            "manual": False,
        }

    def test_obligation_uncertainty_passes_through_normalization_and_merge_unchanged(self) -> None:
        quote = "Отправить отчёт до пятницы"
        source = SourceFile("source.txt", Path("source.txt"), quote, "sha-old", len(quote), "other")
        normalized = _normalize_items(
            [self._raw_item(quote, self.old_uncertainty)],
            {"source.txt": source},
        )

        merged, created, updated, closed = _merge_final(normalized[:0], normalized, "run_1", "2026-08-29T10:00:00+04:00")

        self.assertEqual(merged[0]["uncertainty"], self.old_uncertainty)
        self.assertEqual(set(merged[0]["uncertainty"][0]), {"field", "note", "strength", "alternatives"})
        self.assertEqual((created, updated, closed), (1, 0, 0))

    def test_registry_markdown_appends_warning_note_after_the_row(self) -> None:
        markdown = render_markdown([self._render_item(self.old_uncertainty)])

        self.assertIn(
            "1. Отправить отчёт · Павел · **до пятницы (29.08)** · источник: source.txt: «Отправить отчёт»"
            " · ⚠ Неясно, включена ли пятница\n",
            markdown,
        )

    def test_registry_markdown_has_no_warning_for_certain_row(self) -> None:
        markdown = render_markdown([self._render_item([])])

        row = next(line for line in markdown.splitlines() if line.startswith("1. "))
        self.assertNotIn("⚠", row)

    def test_rerun_replaces_old_uncertainty_and_persists_new_list_in_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()
            registry_path = root / "registry.json"
            old_quote = "Отправить отчёт до пятницы"
            new_quote = "Отчёт отправляет Павел"
            (input_dir / "old.txt").write_text(old_quote, encoding="utf-8")

            old_candidate = self._raw_item(old_quote, self.old_uncertainty, path="old.txt")
            old_final = self._raw_item(old_quote, self.old_uncertainty, path="old.txt", match_id=None)
            with patch("oleg_engine.engine.call_model", side_effect=[
                ({"candidates": [old_candidate]}, "fake", "fake-model"),
                ({"obligations": [old_final]}, "fake", "fake-model"),
            ]):
                run_engine(input_dir, registry_path, "sequential", "codex", None, "2026-08-29", False, True)

            first_registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(first_registry["obligations"][0]["uncertainty"], self.old_uncertainty)

            (input_dir / "new.txt").write_text(new_quote, encoding="utf-8")
            new_candidate = self._raw_item(new_quote, self.new_uncertainty, path="new.txt")
            new_final = self._raw_item(new_quote, self.new_uncertainty, path="new.txt", match_id="ob_0001")
            with patch("oleg_engine.engine.call_model", side_effect=[
                ({"candidates": [new_candidate]}, "fake", "fake-model"),
                ({"obligations": [new_final]}, "fake", "fake-model"),
            ]):
                run_engine(input_dir, registry_path, "sequential", "codex", None, "2026-08-29", False, True)

            persisted = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted["obligations"]), 1)
            self.assertEqual(persisted["obligations"][0]["uncertainty"], self.new_uncertainty)
            self.assertNotEqual(persisted["obligations"][0]["uncertainty"], self.old_uncertainty)


if __name__ == "__main__":
    unittest.main()
