from __future__ import annotations

import unittest

from .engine import _merge_final


RUN_ID = "run_test"
TIMESTAMP = "2026-08-29T12:00:00+04:00"


def source(path: str, quote: str) -> dict[str, object]:
    return {
        "sha256": f"sha-{path}",
        "path": path,
        "quote": quote,
        "line_start": 1,
        "line_end": 1,
    }


def existing_row(
    item_id: str,
    what: str,
    *,
    status: str = "open",
    derived_from: str | None = None,
) -> dict[str, object]:
    return {
        "id": item_id,
        "what": what,
        "owner": "Олег",
        "due": "2026-09-01",
        "due_text": "до 1 сентября",
        "kind": "task",
        "recurrence": None,
        "status": status,
        "derived_from": derived_from,
        "uncertainty": [],
        "sources": [source("opened.txt", f"Открыто: {what}")],
        "history": [{
            "run_id": "run_opened",
            "ts": "2026-08-28T12:00:00+04:00",
            "change": "created",
            "from": None,
            "to": status,
            "source_path": "opened.txt",
        }],
        "manual": False,
    }


def final_row(
    what: str,
    status: str,
    path: str,
    *,
    match_id: str | None,
    derived_from_what: str | None = None,
) -> dict[str, object]:
    return {
        "match_id": match_id,
        "what": what,
        "owner": "Олег",
        "due": "2026-09-01",
        "due_text": "до 1 сентября",
        "kind": "task",
        "recurrence": None,
        "status": status,
        "derived_from_what": derived_from_what,
        "uncertainty": [],
        "sources": [source(path, f"Состояние: {status}")],
    }


class MergeTransitionTests(unittest.TestCase):
    def merge(
        self,
        existing: list[dict[str, object]],
        final: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], int, int, int]:
        return _merge_final(existing, final, RUN_ID, TIMESTAMP)

    def test_done_evidence_closes_open_row_and_records_closing_source(self) -> None:
        rows, created, updated, closed = self.merge(
            [existing_row("ob_0001", "Отправить отчёт")],
            [final_row("Отправить отчёт", "done", "done.txt", match_id="ob_0001")],
        )

        self.assertEqual((created, updated, closed), (0, 1, 1))
        self.assertEqual(rows[0]["status"], "done")
        self.assertEqual(rows[0]["sources"][-1]["path"], "done.txt")
        self.assertEqual(
            rows[0]["history"][-1],
            {
                "run_id": RUN_ID,
                "ts": TIMESTAMP,
                "change": "done",
                "from": "open",
                "to": "done",
                "source_path": "done.txt",
            },
        )

    def test_cancelled_evidence_cancels_open_row(self) -> None:
        rows, _created, _updated, closed = self.merge(
            [existing_row("ob_0001", "Забронировать комнату")],
            [final_row("Забронировать комнату", "cancelled", "cancelled.txt", match_id="ob_0001")],
        )

        self.assertEqual(rows[0]["status"], "cancelled")
        self.assertEqual(rows[0]["history"][-1]["change"], "cancelled")
        self.assertEqual(rows[0]["history"][-1]["source_path"], "cancelled.txt")
        self.assertEqual(closed, 1)

    @unittest.expectedFailure
    def test_cancelled_parent_cascades_with_history_naming_parent(self) -> None:
        """MEDIUM defect: cascade history does not identify the cancelled parent row."""
        parent_what = "Провести демонстрацию"
        child_what = "Напомнить о демонстрации"
        rows, _created, _updated, closed = self.merge(
            [
                existing_row("ob_0001", parent_what),
                existing_row("ob_0002", child_what, derived_from="ob_0001"),
            ],
            [
                final_row(parent_what, "cancelled", "event-cancelled.txt", match_id="ob_0001"),
                final_row(
                    child_what,
                    "open",
                    "reminder.txt",
                    match_id="ob_0002",
                    derived_from_what=parent_what,
                ),
            ],
        )

        by_id = {row["id"]: row for row in rows}
        child = by_id["ob_0002"]
        self.assertEqual(child["status"], "cancelled")
        self.assertEqual(child["history"][-1]["change"], "cancelled")
        self.assertEqual(child["history"][-1]["parent_id"], "ob_0001")
        self.assertEqual(closed, 2)

    @unittest.expectedFailure
    def test_superseded_old_row_links_to_new_row(self) -> None:
        """MEDIUM defect: a superseded row has no explicit replacement link."""
        old_what = "Подготовить старую версию"
        new_what = "Подготовить новую версию"
        rows, created, _updated, closed = self.merge(
            [existing_row("ob_0001", old_what)],
            [
                final_row(
                    old_what,
                    "superseded",
                    "replacement.txt",
                    match_id="ob_0001",
                    derived_from_what=new_what,
                ),
                final_row(new_what, "open", "replacement.txt", match_id=None),
            ],
        )

        by_id = {row["id"]: row for row in rows}
        old = by_id["ob_0001"]
        new = next(row for row in rows if row["what"] == new_what)
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["superseded_by"], new["id"])
        self.assertEqual(old["history"][-1]["change"], "superseded")
        self.assertEqual((created, closed), (1, 1))

    @unittest.expectedFailure
    def test_done_row_is_not_reopened_by_plain_repeat_mention(self) -> None:
        """HIGH defect: a plain open repeat currently reopens a completed row."""
        rows, _created, updated, closed = self.merge(
            [existing_row("ob_0001", "Отправить отчёт", status="done")],
            [final_row("Отправить отчёт", "open", "repeat.txt", match_id="ob_0001")],
        )

        self.assertEqual(rows[0]["status"], "done")
        self.assertEqual(updated, 0)
        self.assertEqual(closed, 0)


if __name__ == "__main__":
    unittest.main()
