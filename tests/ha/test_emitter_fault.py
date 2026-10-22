"""The recorded Bureau failure must not block PAC absence after a reload."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.smart_heat_manager.const import DOMAIN

from .test_persistent_arming import setup


@pytest.mark.parametrize("profile,target", [("absent", 17), ("night", 18), ("holiday", 16), ("present", 20)])
async def test_latched_emitter_fault_keeps_native_profiles_after_reload(hass, installation, profile, target):
    await hass.async_start()
    c = await setup(hass, installation)
    await c.arm(True)
    c.controller.fault = "command_not_applied:number.valve"
    await c.async_evaluate()
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    assert c.armed
    assert c.controller.status == "emitter_fault"
    calls = []

    async def temperature(call):
        calls.append(dict(call.data))
        state = hass.states.get("climate.pump")
        hass.states.async_set(
            "climate.pump", "heat", dict(state.attributes) | {"temperature": call.data["temperature"]}
        )

    hass.services.async_register("climate", "set_temperature", temperature)
    c.runtime["overrides"]["mode"] = {
        "value": profile,
        "until": (dt_util.now() + timedelta(hours=1)).isoformat(),
    }
    # Make present also exercise a real setpoint change.
    state = hass.states.get("climate.pump")
    hass.states.async_set("climate.pump", "heat", dict(state.attributes) | {"temperature": 19})
    await c.async_evaluate()
    assert c.data.mode == profile
    assert hass.states.get("climate.pump").attributes["temperature"] == target
    assert calls and all(call["entity_id"] == "climate.pump" for call in calls)
    assert c.controller.fault == "command_not_applied:number.valve"
    assert c.runtime["armed_requested"] is True
    registry = er.async_get(hass)
    controller = registry.async_get_entity_id("sensor", DOMAIN, f"{installation.entry_id}_controller")
    await hass.async_block_till_done()
    assert hass.states.get(controller).state == "emitter_fault"
    assert hass.states.get(controller).attributes["fault_scope"] == "emitters"
    fault = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{installation.entry_id}_fault")
    assert hass.states.get(fault).state == "on"
    assert hass.states.get("number.valve").state == "0"


async def test_emitter_fault_does_not_bypass_live_safety_or_disarm(hass, installation):
    await hass.async_start()
    c = await setup(hass, installation)
    await c.arm(True)
    c.controller.fault = "command_not_applied:number.valve"
    c.transport.send = AsyncMock()
    c.runtime["overrides"]["mode"] = {"value": "absent", "until": (dt_util.now() + timedelta(hours=1)).isoformat()}
    hass.states.async_set("sensor.living", "unavailable")
    await c.async_evaluate()
    assert c.controller.status == "suspended"
    c.transport.send.assert_not_awaited()
    hass.states.async_set("sensor.living", "25", {"unit_of_measurement": "°C"})
    await c.arm(False)
    assert c.controller.status == "observation"
    c.transport.send.assert_not_awaited()
