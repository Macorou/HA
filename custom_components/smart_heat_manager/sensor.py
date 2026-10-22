"""Concise global decision sensors (room climate already exposes temperatures)."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfPower, UnitOfTemperature

from .entity import HeatEntity

PARALLEL_UPDATES = 0
SENSORS = [
    "decision",
    "reason",
    "controller",
    "surplus",
    "solar_budget",
    "pump_power",
    "tempo",
    "demand_count",
    "pump_target",
]
ENUMS = {
    "decision": ["fault", "paused", "frost", "tempo_blocked", "heating", "solar_heating", "idle"],
    "controller": [
        "observation",
        "command_fault",
        "emitter_fault",
        "suspended",
        "minimum_on",
        "minimum_off",
        "running",
        "starting",
        "stopping",
        "idle",
        "opening_emitters",
        "draining",
        "pump_off",
        "adjusting_setpoint",
        "tempo_stopping",
        "tempo_stopped",
        "tempo_resuming",
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
        if key == "pump_target":
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_device_class = SensorDeviceClass.TEMPERATURE

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
            "pump_target": decision.pump_target,
        }[self.key]

    @property
    def extra_state_attributes(self):
        if self.key == "controller":
            controller = self.coordinator.controller
            return {
                "fault_scope": "emitters"
                if controller.emitter_fault(self.coordinator.config)
                else ("global" if controller.fault else None),
                "emitter_commands_suspended": controller.emitter_fault(self.coordinator.config),
                "command_fault": controller.fault,
            }
        if self.key == "pump_target":
            return {
                "effective_profile": self.coordinator.data.mode,
                "pump_control_policy": "setpoints_with_tempo_stop",
                "tempo_shutdown_requested": self.coordinator.data.pump_tempo_stop,
                "tempo_shutdown_until": self.coordinator.data.pump_tempo_until,
                "observation": not self.coordinator.armed,
            }
        if self.key == "decision":
            return {
                "mode": self.coordinator.data.mode,
                "armed": self.coordinator.armed,
                "faults": self.coordinator.data.faults,
                "pump_observed_on": self.coordinator.snapshot.pump_on,
                "pump_control_policy": "setpoints_with_tempo_stop",
                "tempo_shutdown_requested": self.coordinator.data.pump_tempo_stop,
                "pump_requested_temperature": self.coordinator.data.pump_target,
            }
        return None
