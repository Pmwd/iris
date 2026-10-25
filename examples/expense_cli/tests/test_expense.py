from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import expense


class ExpenseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "expenses.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_add_and_load_roundtrip(self) -> None:
        expenses = expense.load_expenses(self.data)
        expense.add_expense(expenses, 12.5, "coffee", "2026-10-20", "beans")
        expense.save_expenses(expenses, self.data)

        loaded = expense.load_expenses(self.data)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["category"], "coffee")
        self.assertEqual(loaded[0]["amount"], 12.5)
        self.assertEqual(loaded[0]["date"], "2026-10-20")
        self.assertEqual(loaded[0]["note"], "beans")

    def test_format_expenses(self) -> None:
        text = expense.format_expenses(
            [
                {"amount": 3.0, "category": "tea", "date": "2026-10-21", "note": ""},
                {"amount": 9.25, "category": "lunch", "date": "2026-10-21", "note": "noodles"},
            ]
        )
        self.assertIn("tea", text)
        self.assertIn("noodles", text)
        self.assertIn("9.25", text)

    def test_default_file_is_json_array(self) -> None:
        expense.save_expenses([], self.data)
        self.assertEqual(json.loads(self.data.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
