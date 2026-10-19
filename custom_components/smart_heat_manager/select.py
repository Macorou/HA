"""Global operating mode; every non-auto selection has a fixed expiry."""

from homeassistant.components.select import SelectEntity

from .const import MODES
from .entity import HeatEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([HeatMode(entry.runtime_data)])


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
            "expires_at": self.coordinator.runtime["overrides"].get("mode", {}).get("until")
            if self.current_option != "auto"
            else None,
        }

    async def async_select_option(self, option):
        await self.coordinator.set_mode(option)
