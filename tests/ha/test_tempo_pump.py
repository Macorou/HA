"""Actual HA lifecycle: timed bypass, native manual button, ownership and reload."""

from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from custom_components.smart_heat_manager.adapters import Command


def set_pump(hass, mode, context=None):
    hass.states.async_set(
        "climate.pump",
        mode,
        {
            "hvac_modes": ["off", "heat"],
            "supported_features": 385,
            "min_temp": 16,
            "max_temp": 30,
            "target_temp_step": 1,
            "temperature": 20,
        },
        context=context,
    )


@pytest.fixture
async def tempo_installation(hass, installation, freezer):
    dt_util.set_default_time_zone(ZoneInfo("Europe/Paris"))
    freezer.move_to("2026-01-12 11:00:00+00:00")  # noon local, confirmed red
    set_pump(hass, "heat")
    hass.states.async_set("sensor.tempo", "red")
    settings = installation.data["settings"] | {
        "tempo_enabled": True,
        "tempo_today_entity": "sensor.tempo",
        "control_enabled": True,
        "hydraulic_confirmed": True,
        "exclusive_confirmed": True,
        "capabilities_confirmed": True,
    }
    hass.config_entries.async_update_entry(installation, data=installation.data | {"settings": settings})
    calls = []

    async def mode(call):
        calls.append((call.service, call.data["hvac_mode"]))
        set_pump(hass, call.data["hvac_mode"], context=call.context)

    async def temperature(call):
        calls.append((call.service, call.data["temperature"]))
        state = hass.states.get("climate.pump")
        hass.states.async_set(
            "climate.pump", state.state, dict(state.attributes) | {"temperature": call.data["temperature"]}
        )

    async def valve(call):
        state = hass.states.get("number.valve")
        hass.states.async_set("number.valve", str(call.data["value"]), dict(state.attributes))

    assert await hass.config_entries.async_setup(installation.entry_id)
    await hass.async_block_till_done()
    hass.services.async_register("climate", "set_hvac_mode", mode)
    hass.services.async_register("climate", "set_temperature", temperature)
    hass.services.async_register("number", "set_value", valve)
    return installation.runtime_data, calls


async def test_observation_no_off_then_armed_off_and_22_resume(hass, tempo_installation, freezer):
    c, calls = tempo_installation
    assert calls == []
    assert c.data.pump_tempo_stop
    await c.arm(True)
    assert calls == [("set_hvac_mode", "off")]
    await hass.async_block_till_done()
    await c.async_evaluate()
    assert c.controller.tempo_state["confirmed"]
    freezer.move_to("2026-01-12 21:00:00+00:00")  # 22:00 local
    await c.async_evaluate()
    assert calls == [("set_hvac_mode", "off"), ("set_hvac_mode", "heat")]
    assert hass.states.get("climate.pump").state == "heat"
    await c.arm(False)


async def test_native_manual_on_is_respected_until_22(hass, tempo_installation, freezer):
    c, calls = tempo_installation
    await c.arm(True)
    await hass.async_block_till_done()
    set_pump(hass, "heat", context=Context(user_id="manual-user"))
    await hass.async_block_till_done()
    await c.async_evaluate()
    assert c.override("tempo_bypass")
    assert c.runtime["overrides"]["tempo_bypass"]["source"] == "pump_manual"
    assert c.runtime["overrides"]["tempo_bypass"]["until"] == "2026-01-12T21:00:00+00:00"
    assert not c.data.pump_tempo_stop
    freezer.move_to("2026-01-12 20:59:00+00:00")
    await c.async_evaluate()
    assert hass.states.get("climate.pump").state == "heat"
    assert [v for service, v in calls if service == "set_hvac_mode"] == ["off"]
    await c.arm(False)


async def test_switch_bypass_does_not_extend_itself_to_22(hass, tempo_installation, freezer):
    c, calls = tempo_installation
    await c.arm(True)
    await hass.async_block_till_done()
    freezer.move_to("2026-01-12 11:02:00+00:00")
    await c.set_override("tempo_bypass", True)
    await hass.async_block_till_done()
    await c.async_evaluate()
    assert c.runtime["overrides"]["tempo_bypass"]["until"] == "2026-01-12T13:02:00+00:00"
    assert hass.states.get("climate.pump").state == "heat"
    freezer.move_to("2026-01-12 13:02:00+00:00")
    await c.async_evaluate()
    assert hass.states.get("climate.pump").state == "off"
    assert [v for service, v in calls if service == "set_hvac_mode"] == ["off", "heat", "off"]
    await c.arm(False)


async def test_reload_preserves_owner_but_needs_explicit_rearm(hass, installation, tempo_installation, freezer):
    c, calls = tempo_installation
    await c.arm(True)
    await hass.async_block_till_done()
    await c.async_evaluate()
    await c.store.async_save(c.runtime)
    await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    assert not c.armed
    assert c.controller.owns_tempo_stop("climate.pump")
    freezer.move_to("2026-01-12 21:00:00+00:00")
    await c.async_evaluate()
    assert hass.states.get("climate.pump").state == "off"
    await c.arm(True)
    assert hass.states.get("climate.pump").state == "heat"
    await c.arm(False)


async def test_manual_off_cancels_owned_resume(hass, tempo_installation, freezer):
    c, calls = tempo_installation
    await c.arm(True)
    await hass.async_block_till_done()
    set_pump(hass, "heat", context=Context(user_id="manual-user"))
    await hass.async_block_till_done()
    await c.async_evaluate()
    set_pump(hass, "off", context=Context(user_id="manual-user"))
    await hass.async_block_till_done()
    await c.async_evaluate()
    freezer.move_to("2026-01-12 21:00:00+00:00")
    await c.async_evaluate()
    assert hass.states.get("climate.pump").state == "off"
    assert not c.controller.tempo_state
    await c.arm(False)


async def test_forged_mode_command_has_no_transport_authorization(hass, tempo_installation):
    c, calls = tempo_installation
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError, match="setpoint-only"):
        await c.transport.send(Command("climate.pump", "set_hvac_mode", "hvac_mode", "off", None))
    assert calls == []
