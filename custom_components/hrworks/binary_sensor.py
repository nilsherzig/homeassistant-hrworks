"""Presence and absence status for automations."""

from datetime import date, timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import CONF_SICKNESS
from .entity import HrworksEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    keys = ["clocked_in", "on_leave"]
    if entry.options.get(CONF_SICKNESS, True):
        keys.append("on_sick_leave")
    async_add_entities(HrworksBinarySensor(entry.runtime_data, key) for key in keys)
    async_add_entities([HrworksUpdateProblem(entry.runtime_data)])


def event_attributes(event: dict, prefix: str = "") -> dict:
    """Describe an all-day event with an inclusive last day, as the portal shows it."""
    start = date.fromisoformat(event["start"])
    last = date.fromisoformat(event["end"]) - timedelta(days=1)
    attrs = {"start": start.isoformat(), "end": last.isoformat(), "summary": event["summary"]}
    if not prefix:
        attrs.update(
            {
                "days": (last - start).days + 1,
                "status": event.get("status") or None,
                "half_day": event.get("half_day", False),
            }
        )
    return {f"{prefix}{key}": value for key, value in attrs.items()}


class HrworksBinarySensor(HrworksEntity, BinarySensorEntity):
    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self.key = key
        self._attr_icon = {
            "clocked_in": "mdi:briefcase-check-outline",
            "on_leave": "mdi:beach",
            "on_sick_leave": "mdi:medical-bag",
        }[key]

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        return super().available and (
            data.get("clocked_in") is not None
            if self.key == "clocked_in"
            else data.get("events") is not None
        )

    def _events(self) -> tuple[list[dict], list[dict]]:
        """Current and upcoming approved events of this sensor's kind."""
        data = self.coordinator.data or {}
        today = data.get("today", {}).get("date")
        if not today:
            return [], []
        kind = "sickness" if self.key == "on_sick_leave" else "leave"
        events = sorted(
            (
                e
                for e in data.get("events", [])
                if e["kind"] == kind and e.get("approved", False) and e["end"] > today
            ),
            key=lambda e: (e["start"], e["uid"]),
        )
        return [e for e in events if e["start"] <= today], [e for e in events if e["start"] > today]

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        if self.key == "clocked_in":
            return data.get("clocked_in")
        if not data.get("today", {}).get("date"):
            return None
        return bool(self._events()[0])

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        if self.key == "clocked_in":
            intervals = data.get("today_entries")
            if intervals is None:
                return {}
            open_interval = next((e for e in intervals if not e.get("end")), None)
            return {
                "since": open_interval.get("start") if open_interval else None,
                "intervals": intervals,
            }
        current, upcoming = self._events()
        attrs = event_attributes(current[0]) if current else {}
        if upcoming:
            attrs.update(event_attributes(upcoming[0], "next_"))
        return attrs


class HrworksUpdateProblem(HrworksEntity, BinarySensorEntity):
    """On while the last refresh failed; the error and counters are on the sensors."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "update_problem")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return not self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "error": self.coordinator.last_error,
            "consecutive_failures": self.coordinator.consecutive_failures,
        }
