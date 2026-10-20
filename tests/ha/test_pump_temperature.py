"""Autonomous heat pump: persistent editable targets and a hard no-mode boundary."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.smart_heat_manager.adapters import Command
from custom_components.smart_heat_manager.const import DOMAIN


def set_pump(hass, state="heat", temperature=17):
    hass.states.async_set(
        "climate.pump",
        state,
        {
            "hvac_modes": ["off", "heat", "auto"],
            "supported_features": 385,
            "min_temp": 16,
            "max_temp": 30,
            "target_temp_step": 1,
            "temperature": temperature,
        },
    )


async def setup(hass, entry):
    set_pump(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_pump_numbers_editable_persistent_and_native_bounded(hass, installation):
    c = await setup(hass, installation)
    c.transport.send = AsyncMock()
    registry = er.async_get(hass)
    for key, value in (("pump_normal_target", 21), ("pump_tempo_target", 18), ("pump_solar_target", 24)):
        entity_id = registry.async_get_entity_id("number", DOMAIN, f"{installation.entry_id}_{key}")
        state = hass.states.get(entity_id)
        assert state.attributes["min"] == 16
        assert state.attributes["max"] == 30
        assert state.attributes["step"] == 1
        await hass.services.async_call("number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True)
        assert c.settings[key] == value
        assert float(hass.states.get(entity_id).state) == value
    with pytest.raises(HomeAssistantError):
        await c.set_number("pump_normal_target", 20.5)
    with pytest.raises(HomeAssistantError):
        await c.set_number("pump_normal_target", 15)
    c.transport.send.assert_not_awaited()
    await c.store.async_save(c.runtime)
    await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    assert not c.armed
    assert [c.settings[key] for key in ("pump_normal_target", "pump_tempo_target", "pump_solar_target")] == [21, 18, 24]
    assert c.data.pump_target == 21


@pytest.mark.parametrize("service", ["turn_on", "turn_off", "set_hvac_mode", "set_preset_mode"])
async def test_pump_transport_rejects_every_non_temperature_command(hass, installation, service):
    c = await setup(hass, installation)
    with pytest.raises(HomeAssistantError, match="setpoint-only"):
        await c.transport.send(Command("climate.pump", service, "hvac_mode", "off", None))
    assert hass.states.get("climate.pump").state == "heat"
    assert hass.states.get("climate.pump").attributes["temperature"] == 17


async def test_pump_transport_rejects_temperature_write_if_manually_off(hass, installation):
    c = await setup(hass, installation)
    set_pump(hass, "off")
    with pytest.raises(ValueError, match="manually_off"):
        await c.transport.send(Command("climate.pump", "set_temperature", "temperature", 20, "temperature"))
    assert hass.states.get("climate.pump").state == "off"


async def test_armed_temperature_only_and_satisfied_room_keeps_normal_target(hass, installation):
    c = await setup(hass, installation)
    calls = []

    async def set_temperature(call):
        calls.append(("climate", call.service, dict(call.data)))
        state = hass.states.get("climate.pump")
        hass.states.async_set(
            "climate.pump", state.state, dict(state.attributes) | {"temperature": call.data["temperature"]}
        )

    async def set_value(call):
        calls.append(("number", call.service, dict(call.data)))
        state = hass.states.get("number.valve")
        hass.states.async_set("number.valve", str(call.data["value"]), dict(state.attributes))

    hass.services.async_register("climate", "set_temperature", set_temperature)
    hass.services.async_register("number", "set_value", set_value)
    c.config["settings"].update(
        control_enabled=True, hydraulic_confirmed=True, exclusive_confirmed=True, capabilities_confirmed=True
    )
    await c.arm(True)
    assert hass.states.get("climate.pump").state == "heat"
    assert hass.states.get("climate.pump").attributes["temperature"] == 20
    assert [domain for domain, _, _ in calls] == ["number", "climate"]
    hass.states.async_set("sensor.living", "25", {"unit_of_measurement": "°C"})
    await c.async_evaluate()
    assert not c.data.pump_requested
    assert c.data.pump_target == 20
    assert all(service == "set_temperature" for domain, service, _ in calls if domain == "climate")
    assert hass.states.get("climate.pump").state == "heat"
    assert hass.states.get("climate.pump").attributes["temperature"] == 20
    await c.arm(False)
