"""Per-weekday overview: worked hours from day reads, absences from calendar events."""

from __future__ import annotations

from datetime import date, timedelta

WINDOW_DAYS = 30
# Past days are read a few at a time; the portal needs several seconds per day.
READS_PER_UPDATE = 3
# Re-read a day until this many days after it, so late corrections still land.
SETTLE_DAYS = 3


def weekdays(today: date, window: int = WINDOW_DAYS) -> list[date]:
    """Mon-Fri of the last ``window`` calendar days, oldest first, including today."""
    days = (today - timedelta(days=offset) for offset in range(window - 1, -1, -1))
    return [day for day in days if day.weekday() < 5]


def absence(day: date, events: list[dict]) -> dict | None:
    """The approved leave or sickness covering ``day``; sickness wins."""
    iso = day.isoformat()
    covering = [e for e in events if e.get("approved", False) and e["start"] <= iso < e["end"]]
    return next((e for e in covering if e["kind"] == "sickness"), None) or next(
        iter(covering), None
    )


def days_to_read(today: date, cache: dict, events: list[dict]) -> list[date]:
    """Past weekdays still missing or unsettled, newest first, capped per update."""
    pending = []
    for day in reversed([d for d in weekdays(today) if d < today]):
        event = absence(day, events)
        if event and not event.get("half_day"):
            continue
        entry = cache.get(day.isoformat())
        if entry and date.fromisoformat(entry["fetched"]) >= day + timedelta(days=SETTLE_DAYS):
            continue
        if entry and entry["fetched"] == today.isoformat():
            continue
        pending.append(day)
    return pending[:READS_PER_UPDATE]


def prune(today: date, cache: dict) -> dict:
    oldest = (today - timedelta(days=WINDOW_DAYS + 7)).isoformat()
    return {day: entry for day, entry in cache.items() if day >= oldest}


def overview(today: date, cache: dict, events: list[dict], metrics: dict) -> list[dict]:
    """One row per weekday: status worked/leave/sick/holiday/absent/unknown, hours."""
    rows = []
    for day in weekdays(today):
        iso = day.isoformat()
        if day == today:
            entry = {
                "worked": metrics.get("today_worked"),
                "target": metrics.get("today_target"),
            }
        else:
            entry = cache.get(iso) or {}
        worked, target = entry.get("worked"), entry.get("target")
        event = absence(day, events)
        if event:
            status = "sick" if event["kind"] == "sickness" else "leave"
        elif worked:
            status = "worked"
        elif worked is None and target is None:
            status = "unknown" if day != today else "today"
        elif not target:
            status = "holiday"
        else:
            status = "absent" if day != today else "today"
        rows.append(
            {
                "date": iso,
                "status": status,
                "worked": round(worked / 60, 2) if worked is not None else None,
                "target": round(target / 60, 2) if target is not None else None,
                **({"summary": event["summary"]} if event else {}),
            }
        )
    return rows
