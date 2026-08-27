import unittest

from core.sheet_template import (
    ROW3_VALUES,
    ROW4_VALUES,
    find_next_data_row,
    header_repair_insertions,
    is_template_formatted,
    template_value_rows,
)


class SheetTemplateTests(unittest.TestCase):
    def test_canonical_header_needs_no_repair(self) -> None:
        values = template_value_rows("Test date")

        self.assertTrue(is_template_formatted(values))
        self.assertEqual(header_repair_insertions(values), [])

    def test_legacy_two_row_header_gets_leading_rows_only(self) -> None:
        values = [list(ROW3_VALUES), list(ROW4_VALUES), ["09:00", "Candidate"]]

        insertions = header_repair_insertions(values)

        self.assertEqual(len(insertions), 1)
        row_index, rows = insertions[0]
        self.assertEqual(row_index, 1)
        self.assertEqual(len(rows), 2)
        repaired = rows + values
        self.assertTrue(is_template_formatted(repaired))
        self.assertEqual(repaired[4][1], "Candidate")

    def test_missing_header_is_inserted_without_replacing_data(self) -> None:
        values = [["09:00", "Candidate"]]

        row_index, rows = header_repair_insertions(values)[0]

        self.assertEqual(row_index, 1)
        self.assertEqual(len(rows), 4)
        self.assertEqual((rows + values)[4], values[0])

    def test_next_data_row_stays_after_last_candidate(self) -> None:
        values = template_value_rows("Test date")
        values.extend([["09:00", "First"], [], ["10:00", "Second"]])

        self.assertEqual(find_next_data_row(values), 8)


if __name__ == "__main__":
    unittest.main()
