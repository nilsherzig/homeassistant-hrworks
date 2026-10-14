"""Numeric working-time and vacation values with explicit reporting periods."""

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime

from .entity import HrworksEntity
from .workdays import WINDOW_DAYS

TIME_SENSORS = {
    "monthly_worked": "mdi:briefcase-clock-outline",
    "monthly_target": "mdi:clock-check-outline",
    "monthly_balance": "mdi:clock-plus-outline",
    "carryover": "mdi:calendar-arrow-right",
    "total_balance": "mdi:timer-sand",
    "absence_deduction": "mdi:calendar-minus",
    "time_credit": "mdi:clock-edit-outline",
    "today_worked": "mdi:briefcase-clock",
    "today_target": "mdi:clock-check-outline",
    "today_balance": "mdi:clock-plus-outline",
}
DESCRIPTIONS = tuple(
    SensorEntityDescription(
        key=key,
        translation_key=key,
        icon=icon,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=key not in {"absence_deduction", "time_credit"},
    )
    for key, icon in TIME_SENSORS.items()
) + (
    SensorEntityDescription(
        key="vacation_remaining",
        translation_key="vacation_remaining",
        icon="mdi:beach",
        native_unit_of_measurement="d",
    ),
    SensorEntityDescription(
        key="vacation_approved",
        translation_key="vacation_approved",
        icon="mdi:calendar-check",
        native_unit_of_measurement="d",
    ),
    SensorEntityDescription(
        key="last_updated",
        translation_key="last_updated",
        icon="mdi:cloud-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(
        [
            *(HrworksSensor(entry.runtime_data, description) for description in DESCRIPTIONS),
            HrworksWorkDaysSensor(entry.runtime_data),
        ]
    )


class HrworksWorkDaysSensor(HrworksEntity, SensorEntity):
    """Worked weekdays of the last 30 days; the per-day rows feed dashboard heatmaps."""

    _attr_icon = "mdi:calendar-month-outline"
    _attr_native_unit_of_measurement = "d"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # The day list changes every update and is not useful history.
    _unrecorded_attributes = frozenset({"days"})

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "work_days")

    @property
    def _rows(self) -> list[dict] | None:
        return (self.coordinator.data or {}).get("work_days")

    @property
    def available(self) -> bool:
        return super().available and self._rows is not None

    @property
    def native_value(self) -> int | None:
        rows = self._rows
        return None if rows is None else sum(row["status"] == "worked" for row in rows)

    @property
    def extra_state_attributes(self) -> dict:
        rows = self._rows or []
        return {
            "window_days": WINDOW_DAYS,
            "worked_hours": round(sum(row["worked"] or 0 for row in rows), 2),
            "days": rows,
        }


class HrworksSensor(HrworksEntity, SensorEntity):
    def __init__(self, coordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "last_updated":
            value = data.get("fetched_at")
            return datetime.fromisoformat(value) if value else None
        value = data.get("metrics", {}).get(key)
        if value is None:
            return None
        return round(value / 60, 4) if key in TIME_SENSORS else value

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        attrs = {"source": "HR WORKS employee portal"}
        if key in TIME_SENSORS:
            minutes = data.get("metrics", {}).get(key)
            if minutes is not None:
                sign = "-" if minutes < 0 else ""
                hours, remainder = divmod(abs(round(minutes)), 60)
                attrs.update({"minutes": minutes, "formatted": f"{sign}{hours}:{remainder:02d}"})
            attrs.update(data.get("today" if key.startswith("today_") else "account", {}))
        elif key.startswith("vacation_"):
            attrs["year"] = data.get("vacation_year")
        return attrs
