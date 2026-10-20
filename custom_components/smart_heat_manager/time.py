"""Persistent native time pickers for the daily night schedule."""

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory

from .entity import HeatEntity
from .night import clock_time

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(HeatTime(entry.runtime_data, key) for key in ("night_start", "night_end"))


class HeatTime(HeatEntity, TimeEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self.key = key

    @property
    def native_value(self):
        return clock_time(self.coordinator.settings[self.key])

    async def async_set_value(self, value):
        await self.coordinator.set_time(self.key, value)
