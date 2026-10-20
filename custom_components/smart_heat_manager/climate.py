"""Native room climates driven by the external temperature sensor."""

from math import isfinite

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError

from .emitters import room_actuator_entities
from .entity import HeatEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(RoomClimate(entry.runtime_data, room) for room in entry.runtime_data.config["rooms"])


class RoomClimate(HeatEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_preset_modes = ["auto", "present", "absent", "night", "holiday", "manual"]
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.1
    _attr_name = None

    def __init__(self, coordinator, room):
        super().__init__(coordinator, "climate", room)

    @property
    def available(self):
        return super().available and self.result.temperature is not None

    @property
    def current_temperature(self):
        return self.result.temperature

    @property
    def target_temperature(self):
        return self.result.target

    @property
    def hvac_mode(self):
        enabled = self.coordinator.runtime.get("room_enabled", {}).get(self.room["id"], self.room["enabled"])
        return HVACMode.HEAT if enabled else HVACMode.OFF

    @property
    def hvac_action(self):
        # This reflects logical requests, never asserts physical compressor action.
        if (
            self.coordinator.data.state in ("fault", "paused")
            or not self.coordinator.armed
            or self.coordinator.controller.status not in ("running", "minimum_on")
        ):
            return HVACAction.IDLE
        return HVACAction.HEATING if self.result.demand else HVACAction.IDLE

    @property
    def preset_mode(self):
        return "manual" if self.coordinator.override(f"room_{self.room['id']}") is not None else "auto"

    @property
    def extra_state_attributes(self):
        item = self.coordinator.runtime["overrides"].get(f"room_{self.room['id']}", {})
        return {
            "demand": self.result.demand,
            "reason": self.result.reason,
            "opening_request": self.result.opening,
            "observation": not self.coordinator.armed,
            "override_until": item.get("until") if self.preset_mode == "manual" else None,
            "actuators": {
                e: (s.state if (s := self.coordinator.transport.state(e)) else "unavailable")
                for e in room_actuator_entities(self.room)
            },
        }

    async def async_set_temperature(self, **kwargs):
        value = float(kwargs["temperature"])
        if not isfinite(value) or not self.room["frost"] <= value <= 35:
            raise HomeAssistantError("Consigne hors limites de sécurité")
        await self.coordinator.set_override(f"room_{self.room['id']}", value)

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode not in self.hvac_modes:
            raise HomeAssistantError("Mode non pris en charge")
        await self.coordinator.set_preference("room_enabled", hvac_mode == HVACMode.HEAT, self.room["id"])

    async def async_turn_on(self):
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode not in self.preset_modes:
            raise HomeAssistantError("Préréglage inconnu")
        if preset_mode == "auto":
            await self.coordinator.clear_override(f"room_{self.room['id']}")
        else:
            await self.coordinator.set_override(f"room_{self.room['id']}", self.room[preset_mode])
