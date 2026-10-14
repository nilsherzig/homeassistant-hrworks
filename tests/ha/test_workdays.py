"""Per-day overview from fake day reads and events, never real HR records."""

import unittest
from datetime import date

from custom_components.hrworks.workdays import days_to_read, overview, weekdays

TODAY = date(2026, 10, 14)  # a Wednesday
SICK = {
    "kind": "sickness",
    "summary": "Sickness",
    "start": "2026-10-12",
    "end": "2026-10-15",
    "approved": True,
}
LEAVE = {
    "kind": "leave",
    "summary": "Annual vacation",
    "start": "2026-09-30",
    "end": "2026-10-02",
    "approved": True,
}


class WorkdayTests(unittest.TestCase):
    def test_window_skips_weekends(self):
        days = weekdays(TODAY)
        self.assertEqual(days[-1], TODAY)
        self.assertTrue(all(day.weekday() < 5 for day in days))
        self.assertEqual(len(days), 22)

    def test_reads_newest_unsettled_days_without_full_absences(self):
        cache = {"2026-10-09": {"worked": 480, "target": 480, "fetched": "2026-10-11"}}
        # 12th-14th are sick; the 9th was read too soon after the day to be settled.
        self.assertEqual(
            days_to_read(TODAY, cache, [SICK]),
            [date(2026, 10, 9), date(2026, 10, 8), date(2026, 10, 7)],
        )
        cache["2026-10-09"]["fetched"] = "2026-10-12"
        self.assertEqual(days_to_read(TODAY, cache, [SICK])[0], date(2026, 10, 8))

    def test_weekend_still_reads_friday(self):
        self.assertEqual(days_to_read(date(2026, 10, 17), {}, [])[0], date(2026, 10, 16))

    def test_status_per_day(self):
        cache = {
            "2026-10-07": {"worked": 498, "target": 480, "fetched": "2026-10-14"},
            "2026-10-08": {"worked": 0, "target": 480, "fetched": "2026-10-14"},
            "2026-10-05": {"worked": 0, "target": 0, "fetched": "2026-10-14"},
        }
        rows = {row["date"]: row for row in overview(TODAY, cache, [SICK, LEAVE], {})}
        self.assertEqual(rows["2026-10-07"]["status"], "worked")
        self.assertEqual(rows["2026-10-07"]["worked"], 8.3)
        self.assertEqual(rows["2026-10-08"]["status"], "absent")
        self.assertEqual(rows["2026-10-05"]["status"], "holiday")
        self.assertEqual(rows["2026-10-01"]["status"], "leave")
        self.assertEqual(rows["2026-10-14"]["status"], "sick")
        self.assertEqual(rows["2026-10-06"]["status"], "unknown")


class CoordinatorDayReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_day_read_keeps_earlier_days_and_never_raises(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from custom_components.hrworks.api import WorkerError
        from custom_components.hrworks.coordinator import HrworksCoordinator

        coordinator = object.__new__(HrworksCoordinator)
        coordinator._days = None
        coordinator._days_store = SimpleNamespace(
            async_load=AsyncMock(return_value=None), async_save=AsyncMock()
        )
        coordinator.client = SimpleNamespace(
            day=AsyncMock(
                side_effect=[
                    {"metrics": {"today_worked": 450, "today_target": 480}},
                    WorkerError("cannot_connect"),
                ]
            )
        )
        rows = await coordinator._work_days(
            {"today": {"date": "2026-10-14"}, "events": [SICK], "metrics": {}}
        )
        by_date = {row["date"]: row for row in rows}
        self.assertEqual(by_date["2026-10-09"]["status"], "worked")
        self.assertEqual(by_date["2026-10-09"]["worked"], 7.5)
        self.assertEqual(by_date["2026-10-08"]["status"], "unknown")
        self.assertEqual(coordinator.client.day.await_count, 2)
        coordinator._days_store.async_save.assert_awaited_once()
