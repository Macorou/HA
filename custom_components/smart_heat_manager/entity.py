"""Shared entity identity and device grouping."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION


class HeatEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, room=None):
        super().__init__(coordinator)
        self.room = room
        entry_id = coordinator.entry.entry_id
        suffix = f"room_{room['id']}_{key}" if room else key
        self._attr_unique_id = f"{entry_id}_{suffix}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{room['id']}" if room else entry_id)},
            name=room["name"] if room else "Smart Heat Manager",
            manufacturer="Smart Heat Manager",
            model="Room controller" if room else "Heating manager",
            sw_version=VERSION,
        )
        if room:
            self._attr_device_info["via_device"] = (DOMAIN, entry_id)

    @property
    def result(self):
        return self.coordinator.data.rooms[self.room["id"]] if self.room else self.coordinator.data
