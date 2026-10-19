"""Requested heat is separate from actual physical operation."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import HeatEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(HeatBinary(coordinator, key) for key in ("heat_requested", "tempo_blocked", "solar_active", "fault")),
            *(HeatBinary(coordinator, "room_demand", room) for room in coordinator.config["rooms"]),
        ]
    )


class HeatBinary(HeatEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, room=None):
        super().__init__(coordinator, key, room)
        self.key = key
        if key == "fault":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif key in ("heat_requested", "room_demand"):
            self._attr_device_class = BinarySensorDeviceClass.HEAT

    @property
    def is_on(self):
        decision = self.coordinator.data
        if self.room:
            return self.result.demand
        return {
            "heat_requested": decision.pump_requested,
            "tempo_blocked": decision.tempo_blocked,
            "solar_active": decision.solar_active,
            "fault": bool(decision.faults or self.coordinator.controller.fault),
        }[self.key]
