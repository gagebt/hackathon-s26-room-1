from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .backend import _coerce_response, _decode_json
from .__main__ import build_parser
from .engine import SourceFile, _chunks, _display_due, _document_now, _merge_final, _normalize_items


class EngineBoundaryTests(unittest.TestCase):
    def test_codex_effort_defaults_to_medium_and_accepts_explicit_value(self) -> None:
        base = ["run", "--input", "in", "--registry", "registry.json"]
        self.assertEqual(build_parser().parse_args(base).effort, "medium")
        self.assertEqual(build_parser().parse_args([*base, "--effort", "low"]).effort, "low")

    def test_display_due_preserves_source_time_expression(self) -> None:
        self.assertEqual(_display_due({"due_text": "завтра утром", "due": "2026-08-28", "kind": "task"}), "**завтра утром (28.08)**")
        self.assertEqual(_display_due({"due_text": "12 сентября в 18:30", "due": "2026-09-12", "kind": "event"}), "**12 сентября в 18:30**")
        self.assertEqual(_display_due({"due_text": "до пятницы", "due": "2026-08-29", "kind": "task"}), "**до пятницы (29.08)**")
        self.assertEqual(_display_due({"due_text": "к понедельнику 31.08 до обеда", "due": "2026-08-31", "kind": "task"}), "**к понедельнику 31.08 до обеда**")

    def test_completion_report_does_not_reassign_existing_owner(self) -> None:
        source = {"path": "chat.txt", "quote": "Игорь: уже отправил, закрыто", "sha256": "new"}
        old = {
            "id": "ob_0001", "what": "Цифры", "owner": "Павел", "due": "2026-08-29",
            "due_text": "до пятницы", "kind": "task", "recurrence": None, "status": "open",
            "derived_from": None, "uncertainty": [], "sources": [], "history": [], "manual": False,
        }
        final = {
            "match_id": "ob_0001", "what": "Цифры", "owner": "Игорь", "due": "2026-08-29",
            "due_text": "до пятницы", "kind": "task", "recurrence": None, "status": "done",
            "derived_from_what": None,
            "uncertainty": [{"field": "owner", "note": "Кто закрыл", "strength": "low", "alternatives": ["Павел", "Игорь"]}],
            "sources": [source],
        }
        merged, _created, _updated, closed = _merge_final([old], [final], "run_test", "2026-08-29T00:00:00+04:00")
        self.assertEqual(merged[0]["owner"], "Павел")
        self.assertFalse(any(entry["field"] == "owner" for entry in merged[0]["uncertainty"]))
        self.assertEqual(closed, 1)

    def test_claude_json_envelope_with_fenced_result_is_decoded(self) -> None:
        outer = '{"result":"Here is the result:\\n```json\\n{\\"candidates\\":[]}\\n```"}'
        self.assertEqual(_decode_json(outer), {"candidates": []})

    def test_single_schema_array_can_be_normalized(self) -> None:
        schema = {"properties": {"obligations": {"type": "array"}}}
        self.assertEqual(_coerce_response([], schema), {"obligations": []})

    def test_chat_timestamp_controls_reference_date_not_future_deadline(self) -> None:
        source = SourceFile("chat.txt", Path("chat.txt"), "[27.08 14:02] deadline 25.09\n", "abc", 35, "chat")
        self.assertEqual(_document_now([source], None)[5:], "08-27")

    def test_small_file_prefilter_still_sends_all_chunks(self) -> None:
        source = SourceFile("quiet.txt", Path("quiet.txt"), "ordinary context\n" * 70, "abc", 100, "other")
        all_chunks, sent = _chunks(source, True)
        self.assertEqual(len(all_chunks), len(sent))

    def test_invalid_quote_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.txt"
            path.write_text("exact source sentence\n", encoding="utf-8")
            source = SourceFile("source.txt", path, path.read_text(encoding="utf-8"), "abc", path.stat().st_size, "other")
            raw = [{
                "what": "invented", "owner": None, "due": None, "due_text": "",
                "kind": "task", "recurrence": None, "status": "open",
                "derived_from_what": None,
                "sources": [{"path": "source.txt", "quote": "not present", "line_start": 1, "line_end": 1}],
            }]
            self.assertEqual(_normalize_items(raw, {"source.txt": source}), [])

    def test_legacy_crlf_trusted_quote_survives_incremental_run(self) -> None:
        raw = [{
            "match_id": "ob_0001", "what": "Событие", "owner": None, "due": "2026-09-12",
            "due_text": "12 сентября в 18:30", "kind": "event", "recurrence": None,
            "status": "open", "derived_from_what": None, "uncertainty": [],
            "sources": [{"path": "old.txt", "quote": "первая\nвторая", "line_start": 1, "line_end": 2}],
        }]
        trusted = [{"path": "old.txt", "quote": "первая\r\nвторая", "sha256": "old", "line_start": 1, "line_end": 2}]
        normalized = _normalize_items(raw, {}, trusted)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["sources"][0]["quote"], "первая\nвторая")


if __name__ == "__main__":
    unittest.main()
