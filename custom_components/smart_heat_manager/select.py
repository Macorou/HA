"""Global operating mode; every non-auto selection has a fixed expiry."""

from homeassistant.components.select import SelectEntity

from .const import MODES
from .entity import HeatEntity
from .night import night_active

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([HeatMode(entry.runtime_data), PumpMode(entry.runtime_data)])


class PumpMode(HeatEntity, SelectEntity):
    """Independent PAC hold; auto here does not clear any room override."""

    _attr_options = ["auto", "manual"]

    def __init__(self, coordinator):
        super().__init__(coordinator, "pump_override")

    @property
    def current_option(self):
        return "manual" if self.coordinator.pump_manual_target is not None else "auto"

    @property
    def extra_state_attributes(self):
        item = self.coordinator.runtime["overrides"].get("pump_target", {})
        return {
            "target_temperature": self.coordinator.pump_manual_target,
            "expires_at": item.get("until") if self.current_option == "manual" else None,
            "automatic_profile": self.coordinator.data.mode,
        }

    async def async_select_option(self, option):
        if option == "auto":
            await self.coordinator.clear_override("pump_target")
        elif option == "manual":
            state = self.coordinator.transport.state(self.coordinator.settings["pump_entity"])
            await self.coordinator.set_pump_manual(state.attributes.get("temperature") if state else None)


class HeatMode(HeatEntity, SelectEntity):
    _attr_options = MODES

    def __init__(self, coordinator):
        super().__init__(coordinator, "mode")

    @property
    def current_option(self):
        return self.coordinator.override("mode") or "auto"

    @property
    def extra_state_attributes(self):
        return {
            "effective_mode": self.coordinator.data.mode,
            "night_schedule_enabled": self.coordinator.runtime.get(
                "night_schedule_enabled", self.coordinator.settings["night_schedule_enabled"]
            ),
            "night_window_active": night_active(
                self.coordinator.settings, self.coordinator.runtime, self.coordinator.snapshot.now
            ),
            "expires_at": self.coordinator.runtime["overrides"].get("mode", {}).get("until")
            if self.current_option != "auto"
            else None,
        }

    async def async_select_option(self, option):
        await self.coordinator.set_mode(option)
