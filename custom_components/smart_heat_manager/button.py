"""Explicit fault acknowledgement and immediate evaluation."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import HeatEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([HeatButton(entry.runtime_data, "reset_fault"), HeatButton(entry.runtime_data, "evaluate")])


class HeatButton(HeatEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self.key = key

    async def async_press(self):
        if self.key == "reset_fault":
            await self.coordinator.reset_fault()
        else:
            await self.coordinator.async_evaluate()
