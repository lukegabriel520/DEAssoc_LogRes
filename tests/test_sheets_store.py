import unittest
from unittest.mock import Mock

import gspread

from core.config_loader import parse_config
from core.sheet_template import is_template_formatted
from core.sheets_store import SheetsStore


class FakeWorksheet:
    def __init__(self, values: list[list[str]] | None = None) -> None:
        self.id = 42
        self.title = "Data Engineering"
        self.values = [list(row) for row in (values or [])]
        self.append_calls: list[tuple[list[object], dict[str, object]]] = []

    def get_all_values(self) -> list[list[str]]:
        return [list(row) for row in self.values]

    def insert_rows(self, rows, *, row, **kwargs) -> None:
        del kwargs
        self.values[row - 1 : row - 1] = [list(item) for item in rows]

    def append_row(self, values, **kwargs) -> None:
        self.append_calls.append((list(values), kwargs))


def make_store() -> SheetsStore:
    store = SheetsStore.__new__(SheetsStore)
    store._headers_ok = set()
    store._ss = Mock()
    store._titles_cache = None
    store._features_table = None
    store._master_tab_name = "Sheet1"
    return store


def minimal_config():
    return parse_config(
        {
            "system_title": "SCHEMA",
            "department": "Display Department",
            "term": "Test",
            "model_parameters": {
                "beta_0": -2,
                "top_k_slots": 1,
                "pass_threshold_probability": 0.5,
            },
            "sections": [
                {
                    "section_id": "general",
                    "title": "General",
                    "allocated_time_minutes": 1,
                    "questions": [
                        {
                            "id": "q1",
                            "label": "Question",
                            "prompt": "Prompt",
                            "pass_criteria": "Pass",
                            "fail_criteria": "Fail",
                            "weight": 1,
                        }
                    ],
                }
            ],
        }
    )


class SheetsStoreTests(unittest.TestCase):
    def test_new_department_is_duplicated_from_master(self) -> None:
        store = make_store()
        master = Mock()
        new_ws = Mock()
        new_ws.id = 99
        master.duplicate.return_value = new_ws
        store._get_master_tab = Mock(return_value=master)
        store._ensure_department_headers = Mock()
        store.invalidate_titles_cache = Mock()

        result = store._duplicate_department_tab("Physical Tab")

        self.assertIs(result, new_ws)
        master.duplicate.assert_called_once_with(new_sheet_name="Physical Tab")
        new_ws.update.assert_called_once()
        self.assertIn("department-header:99", store._headers_ok)

    def test_missing_header_is_inserted_and_formatted(self) -> None:
        ws = FakeWorksheet([["09:00", "Existing Candidate"]])
        store = make_store()

        store._ensure_department_headers(ws)

        self.assertTrue(is_template_formatted(ws.values))
        self.assertEqual(ws.values[4][1], "Existing Candidate")
        store._ss.batch_update.assert_called_once()

    def test_department_append_is_anchored_and_insert_only(self) -> None:
        ws = FakeWorksheet()
        store = make_store()
        row = ["time", "name", "first", "second", "link", "notes", "Pending"]

        store._append_department_row(ws, row)

        values, options = ws.append_calls[0]
        self.assertEqual(values, row)
        self.assertEqual(options["table_range"], "A4:G")
        self.assertEqual(options["insert_data_option"], "INSERT_ROWS")

    def test_stale_title_cache_recovers_by_duplicating(self) -> None:
        store = make_store()
        replacement = FakeWorksheet()
        store._sheet_titles = Mock(return_value=["Data Engineering"])
        store._ss.worksheet.side_effect = gspread.WorksheetNotFound("deleted")
        store.invalidate_titles_cache = Mock()
        store._duplicate_department_tab = Mock(return_value=replacement)

        result = store.ensure_department_tab("Data Engineering")

        self.assertIs(result, replacement)
        store.invalidate_titles_cache.assert_called_once()
        store._duplicate_department_tab.assert_called_once_with("Data Engineering")

    def test_submit_routes_by_sheet_name_but_records_display_name(self) -> None:
        store = make_store()
        dept_ws = FakeWorksheet()
        features_ws = Mock()
        store.ensure_department_tab = Mock(return_value=dept_ws)
        store.ensure_features_tab = Mock(return_value=features_ws)
        store._append_department_row = Mock()
        store.invalidate_caches = Mock()
        store._load_features_table = Mock(return_value=[["header"]])
        store.recalculate_ranks = Mock(return_value={})

        store.submit_candidate(
            department_display="Display Department",
            department_sheet_name="Physical Tab",
            name="Candidate",
            first_choice="First",
            second_choice="Second",
            meeting_link="N/A",
            qualitative_notes="",
            features={"q1": 1},
            config=minimal_config(),
            notes_text="Notes",
            score_logit=1.0,
            score_probability=0.75,
        )

        store.ensure_department_tab.assert_called_once_with("Physical Tab")
        feature_values = features_ws.append_row.call_args.args[0]
        self.assertEqual(feature_values[0], "Display Department")
        self.assertEqual(
            store.recalculate_ranks.call_args.kwargs["department_sheet_name"],
            "Physical Tab",
        )


if __name__ == "__main__":
    unittest.main()
