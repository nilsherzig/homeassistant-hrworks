"""Entity state and attributes from a fake snapshot, never real HR records."""

import unittest
from types import SimpleNamespace

from custom_components.hrworks.binary_sensor import HrworksBinarySensor
from custom_components.hrworks.calendar import HrworksCalendar


def event(kind, uid, start, end, **extra):
    return {
        "uid": f"hrworks-{kind}-{uid}",
        "kind": kind,
        "summary": f"{kind} {uid}",
        "start": start,
        "end": end,
        "approved": True,
        "status": "",
        "half_day": False,
        **extra,
    }


SNAPSHOT = {
    "today": {"date": "2026-10-14"},
    "clocked_in": True,
    "today_entries": [
        {"start": "08:00", "end": "12:00", "type": "Work"},
        {"start": "12:30", "type": "Work"},
    ],
    "events": [
        event("sickness", 1, "2026-10-12", "2026-10-15", status="eAU is available"),
        event("leave", 2, "2026-10-20", "2026-10-23"),
        event("leave", 3, "2026-11-02", "2026-11-03", approved=False),
        event("sickness", 4, "2026-03-24", "2026-03-27"),
    ],
}


def entity(cls, *args):
    coordinator = SimpleNamespace(
        data=SNAPSHOT,
        entry=SimpleNamespace(data={"profile_id": "a" * 64}, title="HR WORKS"),
        last_update_success=True,
    )
    return cls(coordinator, *args)


class EntityTests(unittest.TestCase):
    def test_sick_leave_reports_current_absence_inclusively(self):
        sensor = entity(HrworksBinarySensor, "on_sick_leave")
        self.assertTrue(sensor.is_on)
        self.assertEqual(
            sensor.extra_state_attributes,
            {
                "start": "2026-10-12",
                "end": "2026-10-14",
                "summary": "sickness 1",
                "days": 3,
                "status": "eAU is available",
                "half_day": False,
            },
        )

    def test_leave_reports_next_approved_absence(self):
        sensor = entity(HrworksBinarySensor, "on_leave")
        self.assertFalse(sensor.is_on)
        self.assertEqual(
            sensor.extra_state_attributes,
            {"next_start": "2026-10-20", "next_end": "2026-10-22", "next_summary": "leave 2"},
        )

    def test_clocked_in_reports_open_interval(self):
        attrs = entity(HrworksBinarySensor, "clocked_in").extra_state_attributes
        self.assertEqual(attrs["since"], "12:30")
        self.assertEqual(len(attrs["intervals"]), 2)

    def test_single_calendar_shows_every_kind(self):
        calendar = entity(HrworksCalendar)
        self.assertEqual(calendar.event.summary, "sickness 1")
        self.assertIsNone(calendar.name)
