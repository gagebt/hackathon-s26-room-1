from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from .engine import SourceFile, _document_now, render_markdown, run_engine


class _FixedDate(date):
    @classmethod
    def today(cls) -> "_FixedDate":
        return cls(2026, 8, 29)


def _source(path: str, text: str) -> SourceFile:
    return SourceFile(path, Path(path), text, "sha-" + path, len(text.encode("utf-8")), "email" if path.endswith(".eml") else "chat")


def _item(
    what: str,
    *,
    owner: str | None = "Олег",
    due: str | None = "2026-08-30",
    kind: str = "task",
    status: str = "open",
    path: str = "chat.txt",
    quote: str | None = None,
) -> dict[str, object]:
    return {
        "what": what,
        "owner": owner,
        "due": due,
        "kind": kind,
        "status": status,
        "uncertainty": [],
        "sources": [{"path": path, "quote": quote or what}],
    }


class DatesAndMarkdownTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_default_now_is_latest_visible_input_date(self) -> None:
        """HIGH defect: ISO e-mail year is ignored, so the host year leaks into --now."""
        sources = [
            _source("chat-27.txt", "[27.08 09:00] Начало обсуждения\n"),
            _source("chat-28.txt", "[28.08 18:30] Последнее сообщение\n"),
            _source("mail.eml", "Date: Fri, 2026-08-28 20:15:00 +0400\nSubject: Итоги\n"),
        ]

        class WrongHostYear(date):
            @classmethod
            def today(cls) -> "WrongHostYear":
                return cls(2030, 8, 29)

        with patch("oleg_engine.engine.date", WrongHostYear):
            self.assertEqual(_document_now(sources, None), "2026-08-28")

    def test_explicit_now_wins_over_input_dates(self) -> None:
        sources = [_source("chat.txt", "[28.08 18:30] Последнее сообщение\n")]

        with patch("oleg_engine.engine.date", _FixedDate):
            self.assertEqual(_document_now(sources, "2026-09-03"), "2026-09-03")

    def test_open_row_uses_real_registry_format_and_allows_no_deadline(self) -> None:
        markdown = render_markdown([
            _item("Подать отчёт", quote="Олег, подай отчёт"),
            _item("Уточнить бюджет", owner=None, due=None, quote="Уточнить бюджет"),
        ])

        self.assertIn(
            "1. Подать отчёт · Олег · **до 30.08** · источник: chat.txt: «Олег, подай отчёт»",
            markdown,
        )
        self.assertIn(
            "2. Уточнить бюджет · не назначен · **без срока** · источник: chat.txt: «Уточнить бюджет»",
            markdown,
        )

    def test_closed_rows_move_to_second_section_and_kinds_are_distinct(self) -> None:
        markdown = render_markdown([
            _item("Еженедельный отчёт", kind="recurring"),
            _item("Встреча команды", kind="event"),
            _item("Готовая задача", status="done"),
            _item("Отменённая задача", status="cancelled"),
            _item("Заменённая задача", status="superseded"),
        ])
        open_section, closed_section = markdown.split("## Закрытые и отменённые", maxsplit=1)

        self.assertIn("Еженедельный отчёт · Олег · **до 30.08** · recurring", open_section)
        self.assertIn("Встреча команды · Олег · **30.08** · event", open_section)
        for what, status in (
            ("Готовая задача", "done"),
            ("Отменённая задача", "cancelled"),
            ("Заменённая задача", "superseded"),
        ):
            self.assertNotIn(what, open_section)
            self.assertIn(f"{what} · Олег · **до 30.08** · {status}", closed_section)

    def test_written_markdown_and_json_name_the_same_number_of_rows(self) -> None:
        source_text = "Первая задача\nСобытие команды\n"
        candidates = [
            {
                "what": "Первая задача", "owner": "Олег", "due": None, "due_text": "",
                "kind": "task", "recurrence": None, "status": "open",
                "derived_from_what": None, "uncertainty": [],
                "sources": [{"path": "input.txt", "quote": "Первая задача", "line_start": 1, "line_end": 1}],
            },
            {
                "what": "Событие команды", "owner": None, "due": "2026-09-01", "due_text": "1 сентября",
                "kind": "event", "recurrence": None, "status": "open",
                "derived_from_what": None, "uncertainty": [],
                "sources": [{"path": "input.txt", "quote": "Событие команды", "line_start": 2, "line_end": 2}],
            },
        ]

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "inputs"
            input_dir.mkdir()
            (input_dir / "input.txt").write_text(source_text, encoding="utf-8")
            registry_path = root / "registry.json"
            fake_result = ({"candidates": candidates}, "codex", "fake-model")
            with patch("oleg_engine.engine.call_model", return_value=fake_result):
                run_engine(input_dir, registry_path, "sequential", "codex", None, "2026-08-28", False, False)

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            markdown = registry_path.with_name("registry.md").read_text(encoding="utf-8")
            rendered_rows = re.findall(r"(?m)^\d+\. ", markdown)
            self.assertEqual(len(rendered_rows), len(registry["obligations"]))
            self.assertEqual(len(registry["obligations"]), 2)


if __name__ == "__main__":
    unittest.main()
