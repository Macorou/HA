"""Smart Heat Manager custom integration."""

from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .coordinator import HeatCoordinator


async def async_setup_entry(hass, entry):
    coordinator = entry.runtime_data = HeatCoordinator(hass, entry)
    # Remove entities of deleted rooms, preserving renamed rooms' stable IDs.
    registry = er.async_get(hass)
    room_ids = {r["id"] for r in coordinator.config["rooms"]}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        suffix = entity.unique_id.removeprefix(f"{entry.entry_id}_room_")
        if entity.unique_id.startswith(f"{entry.entry_id}_room_") and suffix.split("_", 1)[0] not in room_ids:
            registry.async_remove(entity.entity_id)
    devices = dr.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        obsolete = any(
            domain == DOMAIN and identifier.startswith(prefix) and identifier.removeprefix(prefix) not in room_ids
            for domain, identifier in device.identifiers
        )
        if obsolete and device.config_entries == {entry.entry_id}:
            devices.async_remove_device(device.id)
    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, [Platform(p) for p in PLATFORMS])
    entry.async_on_unload(entry.add_update_listener(async_reload))
    return True


async def async_reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    coordinator = entry.runtime_data
    coordinator.armed = False
    async with coordinator.lock:
        coordinator.closed = True
        await coordinator.store.async_save(coordinator.runtime)
    return await hass.config_entries.async_unload_platforms(entry, [Platform(p) for p in PLATFORMS])


async def async_remove_entry(hass, entry):
    from homeassistant.helpers.storage import Store

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
