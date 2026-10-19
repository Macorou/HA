"""Concise global decision sensors (room climate already exposes temperatures)."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfPower

from .entity import HeatEntity

PARALLEL_UPDATES = 0
SENSORS = ["decision", "reason", "controller", "surplus", "solar_budget", "pump_power", "tempo", "demand_count"]
ENUMS = {
    "decision": ["fault", "paused", "frost", "tempo_blocked", "heating", "solar_heating", "idle"],
    "controller": [
        "observation",
        "command_fault",
        "suspended",
        "minimum_on",
        "minimum_off",
        "running",
        "starting",
        "stopping",
        "idle",
        "opening_emitters",
        "draining",
    ],
    "tempo": ["red", "white", "blue", "unknown"],
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(HeatSensor(entry.runtime_data, key) for key in SENSORS)


class HeatSensor(HeatEntity, SensorEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self.key = key
        if key in ENUMS:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ENUMS[key]
        if key in ("surplus", "solar_budget", "pump_power"):
            self._attr_native_unit_of_measurement = UnitOfPower.WATT
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        decision = self.coordinator.data
        return {
            "decision": decision.state,
            "reason": self.coordinator.controller.fault or decision.reason,
            "controller": self.coordinator.controller.status,
            "surplus": decision.surplus,
            "solar_budget": decision.solar_budget,
            "pump_power": self.coordinator.snapshot.pump_power,
            "tempo": decision.tempo,
            "demand_count": sum(room.demand for room in decision.rooms.values()),
        }[self.key]

    @property
    def extra_state_attributes(self):
        if self.key == "decision":
            return {
                "mode": self.coordinator.data.mode,
                "armed": self.coordinator.armed,
                "faults": self.coordinator.data.faults,
                "pump_observed_on": self.coordinator.snapshot.pump_on,
            }
        return None
