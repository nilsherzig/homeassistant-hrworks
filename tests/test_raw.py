import unittest

from hrworks.browser_daemon import assist_row
from hrworks.errors import WorkerError
from hrworks.models import raw_request

TABLE = """DATE START END TIME TOTAL COMMENT
2026-11-02  08:09:53  12:19:54  4:10:01
2026-11-02  13:22:35  17:42:36  4:20:01  8:30:02  doc apptment
2026-11-03  9:00:00  N/A
"""


class RawRequestTests(unittest.TestCase):
    def test_rows_stay_separate_and_unfinished_rows_are_dropped(self):
        request = raw_request(TABLE)
        self.assertEqual(
            [(r["date"], r["start"], r["end"], r["type"]) for r in request["rows"]],
            [
                ("2026-11-02", "08:09", "12:19", "working_time"),
                ("2026-11-02", "13:22", "17:42", "doctors_appointment"),
            ],
        )
        self.assertEqual(request["rows"][1]["comment"], "doc apptment")
        self.assertNotIn("2026-11-03", request["prompt"])
        self.assertIn("2026-11-02  13:22  17:42  doc apptment", request["prompt"])

    def test_free_text_is_sent_unchanged_without_expectations(self):
        request = raw_request("I worked from 4 p.m. to 5 p.m. today.\n")
        self.assertEqual(request, {"prompt": "I worked from 4 p.m. to 5 p.m. today.", "rows": []})

    def test_empty_input_is_invalid(self):
        with self.assertRaises(ValueError):
            raw_request("  \n")

    def test_expected_rows_are_validated(self):
        row = {"date": "2026-11-02", "start": "08:09", "end": "12:19", "type": "working_time"}
        self.assertEqual(assist_row(row)["labels"], ["Working time", "Arbeitszeit"])
        with self.assertRaises(WorkerError):
            assist_row({**row, "start": "8am"})
        with self.assertRaises(WorkerError):
            assist_row({**row, "type": "holiday"})


if __name__ == "__main__":
    unittest.main()
