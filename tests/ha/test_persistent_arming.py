"""Only an explicit operator choice changes persisted arming, not HA lifecycle."""

from unittest.mock import AsyncMock, patch

import pytest


async def setup(hass, installation):
    hass.states.async_set(
        "climate.pump",
        "heat",
        {"hvac_modes": ["off", "heat"], "temperature": 20, "min_temp": 16, "max_temp": 30, "target_temp_step": 1},
    )
    hass.states.async_set("sensor.living", "25", {"unit_of_measurement": "°C"})
    settings = installation.data["settings"] | {
        "control_enabled": True,
        "hydraulic_confirmed": True,
        "exclusive_confirmed": True,
        "capabilities_confirmed": True,
    }
    hass.config_entries.async_update_entry(installation, data=installation.data | {"settings": settings})
    assert await hass.config_entries.async_setup(installation.entry_id)
    await hass.async_block_till_done()
    return installation.runtime_data


async def test_arm_survives_reload_and_manual_disarm_persists(hass, installation):
    await hass.async_start()
    c = await setup(hass, installation)
    assert not c.armed
    await c.arm(True)
    assert c.runtime["armed_requested"] is True
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    assert c.armed
    assert c.controller.status == "running"
    await c.arm(False)
    assert c.runtime["armed_requested"] is False
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    assert not installation.runtime_data.armed
    assert installation.runtime_data.controller.status == "observation"


async def test_restored_arming_waits_for_ha_start_and_valid_sources(hass, installation):
    c = await setup(hass, installation)
    await c.arm(True)
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    c.transport.send = AsyncMock()
    assert c.armed and c.startup_pending
    assert c.controller.status == "suspended"
    assert not c.permit_commands()
    hass.states.async_set("sensor.living", "unavailable")
    await hass.async_start()
    await c.async_evaluate()
    assert c.armed
    assert not c.startup_pending
    assert c.controller.status == "suspended"
    c.transport.send.assert_not_awaited()
    hass.states.async_set("sensor.living", "25", {"unit_of_measurement": "°C"})
    await c.async_evaluate()
    assert c.armed
    assert c.controller.status == "running"


async def test_fault_and_acknowledgement_remain_explicit(hass, installation):
    await hass.async_start()
    c = await setup(hass, installation)
    await c.arm(True)
    c.controller.fault = "command_not_applied:number.valve"
    await c.async_evaluate()
    assert c.armed
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    assert c.armed
    assert c.controller.status == "command_fault"
    assert c.controller.fault == "command_not_applied:number.valve"
    await c.reset_fault()
    assert not c.armed
    assert c.runtime["armed_requested"] is False
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    assert not installation.runtime_data.armed
    assert installation.runtime_data.controller.fault is None


async def test_failed_disk_write_does_not_enable_arming(hass, installation):
    c = await setup(hass, installation)
    with patch.object(c.store, "async_save", AsyncMock(side_effect=OSError("disk unavailable"))):
        with pytest.raises(OSError):
            await c.arm(True)
    assert not c.armed
    assert c.runtime["armed_requested"] is False


async def test_permissions_disabled_suspend_without_forgetting_operator_choice(hass, installation):
    await hass.async_start()
    c = await setup(hass, installation)
    await c.arm(True)
    c.config["settings"]["control_enabled"] = False
    await c.async_evaluate()
    assert c.armed
    assert c.runtime["armed_requested"] is True
    assert c.controller.status == "suspended"
    assert not c.permit_commands()
