"""Native time services persist schedule preferences without physical commands."""

from datetime import time
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.smart_heat_manager.const import DOMAIN


async def test_night_time_services_toggle_reload_and_observation(hass, installation, freezer):
    freezer.move_to("2026-10-21T23:00:00+00:00")
    hass.states.async_set(
        "climate.pump",
        "heat",
        {"hvac_modes": ["off", "heat"], "temperature": 19, "min_temp": 16, "max_temp": 30, "target_temp_step": 1},
    )
    assert await hass.config_entries.async_setup(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    c.transport.send = AsyncMock()
    registry = er.async_get(hass)
    for key, value in [("night_start", "21:30:00"), ("night_end", "08:15:00")]:
        entity = registry.async_get_entity_id("time", DOMAIN, f"{installation.entry_id}_{key}")
        assert entity
        await hass.services.async_call("time", "set_value", {"entity_id": entity, "time": value}, blocking=True)
        assert hass.states.get(entity).state == value
        assert c.settings[key] == value
    switch = registry.async_get_entity_id("switch", DOMAIN, f"{installation.entry_id}_night_schedule_enabled")
    assert hass.states.get(switch).state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert c.data.mode == "night"
    assert c.data.pump_target == 18
    assert c.data.rooms["living"].target == 18
    assert c.controller.status == "observation"
    c.transport.send.assert_not_awaited()
    await c.store.async_save(c.runtime)
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    assert c.settings["night_start"] == "21:30:00"
    assert c.settings["night_end"] == "08:15:00"
    assert c.runtime["night_schedule_enabled"] is True
    assert c.data.mode == "night"
    assert not c.armed
    assert c.controller.status == "observation"
    assert hass.states.get("climate.pump").attributes["temperature"] == 19
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert c.data.mode == "present"
    with pytest.raises(HomeAssistantError):
        await c.set_time("other", time(22))
    with pytest.raises(HomeAssistantError):
        await c.set_time("night_start", "invalid")


async def test_invalid_saved_times_do_not_discard_numeric_targets(hass, installation):
    assert await hass.config_entries.async_setup(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    c.runtime["times"] = {"night_start": "bad"}
    c.runtime["numbers"] = {"pump_normal_target": 23}
    await c.store.async_save(c.runtime)
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    assert c.settings["night_start"] == "22:00:00"
    assert c.settings["pump_normal_target"] == 23
    assert not c.armed
