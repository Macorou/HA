"""Frequently adjusted power thresholds and per-room solar ceilings."""

from math import isfinite

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import PUMP_TARGET_KEYS
from .entity import HeatEntity

PARALLEL_UPDATES = 0
RANGES = {
    **{key: (5, 35, 0.1, "°C") for key in PUMP_TARGET_KEYS},
    "solar_start": (0, 20000, 50, "W"),
    "solar_hold": (0, 20000, 50, "W"),
    "solar_margin": (0, 5000, 50, "W"),
    "override_minutes": (1, 1440, 1, "min"),
    "solar_target": (5, 35, 0.1, "°C"),
}


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities(
        [
            *(HeatNumber(c, key) for key in RANGES if key != "solar_target"),
            *(HeatNumber(c, "solar_target", room) for room in c.config["rooms"]),
        ]
    )


class HeatNumber(HeatEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key, room=None):
        super().__init__(coordinator, key, room)
        self.key = key
        (
            self._attr_native_min_value,
            self._attr_native_max_value,
            self._attr_native_step,
            self._attr_native_unit_of_measurement,
        ) = RANGES[key]

    @property
    def native_min_value(self):
        return self.pump_bound("min_temp", self._attr_native_min_value)

    @property
    def native_max_value(self):
        return self.pump_bound("max_temp", self._attr_native_max_value)

    @property
    def native_step(self):
        return self.pump_bound("target_temp_step", self._attr_native_step)

    def pump_bound(self, attribute, fallback):
        if self.key.startswith("pump_"):
            state = self.coordinator.transport.state(self.coordinator.settings["pump_entity"])
            if state is not None:
                return state.attributes.get(attribute) or fallback
        return fallback

    @property
    def native_value(self):
        if self.room:
            return self.coordinator.runtime.get("room_solar_target", {}).get(self.room["id"], self.room["solar"])
        return self.coordinator.settings[self.key]

    async def async_set_native_value(self, value):
        if not isfinite(value) or not self.native_min_value <= value <= self.native_max_value:
            raise HomeAssistantError("Valeur hors limites")
        await self.coordinator.set_number(self.key, value, self.room["id"] if self.room else None)
