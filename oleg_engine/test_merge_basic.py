from __future__ import annotations

import unittest

from .engine import _merge_final


def _adjudicated_item(
    *,
    due: str = "2026-09-10",
    match_id: str | None = None,
    source_path: str = "requests/team.txt",
    quote: str = "Send the signed report by 10 September.",
) -> dict[str, object]:
    return {
        "match_id": match_id,
        "what": "Send the signed report",
        "owner": "Oleg",
        "due": due,
        "due_text": "by 10 September",
        "kind": "task",
        "recurrence": None,
        "status": "open",
        "derived_from_what": None,
        "uncertainty": [],
        "sources": [{
            "sha256": "a" * 64,
            "path": source_path,
            "quote": quote,
            "line_start": 7,
            "line_end": 7,
        }],
    }


class MergeFinalBasicTests(unittest.TestCase):
    def test_new_obligation_has_created_history_and_complete_source(self) -> None:
        obligations, created, updated, closed = _merge_final(
            [], [_adjudicated_item()], "run-create", "2026-08-29T12:00:00Z"
        )

        self.assertEqual((created, updated, closed), (1, 0, 0))
        self.assertEqual(len(obligations), 1)
        obligation = obligations[0]
        self.assertEqual(obligation["history"], [{
            "run_id": "run-create",
            "ts": "2026-08-29T12:00:00Z",
            "change": "created",
            "from": None,
            "to": "open",
            "source_path": "requests/team.txt",
        }])
        self.assertEqual(obligation["sources"], [{
            "sha256": "a" * 64,
            "path": "requests/team.txt",
            "quote": "Send the signed report by 10 September.",
            "line_start": 7,
            "line_end": 7,
        }])

    def test_new_deadline_updates_one_row_and_records_due_change(self) -> None:
        first, _, _, _ = _merge_final(
            [], [_adjudicated_item()], "run-create", "2026-08-29T12:00:00Z"
        )
        changed = _adjudicated_item(
            due="2026-09-12",
            match_id=first[0]["id"],
            source_path="requests/update.txt",
            quote="The new deadline is 12 September.",
        )

        obligations, created, updated, closed = _merge_final(
            first, [changed], "run-update", "2026-08-30T09:00:00Z"
        )

        self.assertEqual((created, updated, closed), (0, 1, 0))
        self.assertEqual(len(obligations), 1)
        self.assertEqual(obligations[0]["due"], "2026-09-12")
        self.assertEqual(obligations[0]["history"][-1], {
            "run_id": "run-update",
            "ts": "2026-08-30T09:00:00Z",
            "change": "due_changed",
            "from": "2026-09-10",
            "to": "2026-09-12",
            "source_path": "requests/update.txt",
        })

    def test_identical_second_merge_is_a_no_op(self) -> None:
        first, _, _, _ = _merge_final(
            [], [_adjudicated_item()], "run-create", "2026-08-29T12:00:00Z"
        )
        repeated = _adjudicated_item(match_id=first[0]["id"])

        second, created, updated, closed = _merge_final(
            first, [repeated], "run-repeat", "2026-08-30T09:00:00Z"
        )

        self.assertEqual((created, updated, closed), (0, 0, 0))
        self.assertEqual(second, first)
        self.assertEqual(len(second[0]["history"]), 1)

    def test_id_is_stable_when_existing_obligation_is_merged(self) -> None:
        first, _, _, _ = _merge_final(
            [], [_adjudicated_item()], "run-create", "2026-08-29T12:00:00Z"
        )
        original_id = first[0]["id"]
        changed = _adjudicated_item(due="2026-09-12", match_id=original_id)

        second, _, _, _ = _merge_final(
            first, [changed], "run-update", "2026-08-30T09:00:00Z"
        )

        self.assertEqual(second[0]["id"], original_id)


if __name__ == "__main__":
    unittest.main()
