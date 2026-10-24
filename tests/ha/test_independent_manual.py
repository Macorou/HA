"""Native PAC +/- and room climates each own a separate timed manual hold."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.smart_heat_manager.adapters import Command
from custom_components.smart_heat_manager.const import DOMAIN, ROOM_DEFAULTS
from custom_components.smart_heat_manager.controller import Pending

from .test_pump_temperature import set_pump


@pytest.fixture
async def manual_installation(hass, installation):
    await hass.async_start()
    set_pump(hass, temperature=17)
    hass.states.async_set("sensor.bedroom", "19", {"unit_of_measurement": "°C"})
    hass.states.async_set("number.bedroom", "0", {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"})
    data = installation.data | {
        "settings": installation.data["settings"]
        | {
            "control_enabled": True,
            "hydraulic_confirmed": True,
            "exclusive_confirmed": True,
            "capabilities_confirmed": True,
            "pump_night_target": 17,
        },
        "rooms": installation.data["rooms"]
        + [
            ROOM_DEFAULTS
            | {"id": "bedroom", "name": "Bedroom", "sensor": "sensor.bedroom", "actuators": ["number.bedroom"]}
        ],
    }
    hass.config_entries.async_update_entry(installation, data=data)
    calls = []

    async def temperature(call):
        calls.append(dict(call.data))
        entity = call.data["entity_id"]
        if entity in ("climate.pump", ["climate.pump"]):
            state = hass.states.get("climate.pump")
            hass.states.async_set(
                "climate.pump",
                state.state,
                dict(state.attributes) | {"temperature": call.data["temperature"]},
                context=call.context,
            )

    async def value(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        state = hass.states.get(entity)
        hass.states.async_set(entity, str(call.data["value"]), dict(state.attributes))

    # Entity platforms register their services first; replace only the native
    # climate dispatch below when exercising pump calls. Room tests use objects.
    assert await hass.config_entries.async_setup(installation.entry_id)
    await hass.async_block_till_done()
    hass.services.async_register("climate", "set_temperature", temperature)
    hass.services.async_register("number", "set_value", value)
    c = installation.runtime_data
    await c.set_mode("night")
    await c.arm(True)
    await hass.async_block_till_done()
    return c, calls


async def ui_temperature(hass, user, value, entity="climate.pump"):
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity, "temperature": value},
        blocking=True,
        context=Context(user_id=user.id),
    )
    await hass.async_block_till_done()


async def test_native_pac_plus_adopts_manual_without_touching_rooms(
    hass, installation, manual_installation, hass_admin_user
):
    c, calls = manual_installation
    await ui_temperature(hass, hass_admin_user, 21)
    await c.async_evaluate()
    assert c.pump_manual_target == 21
    assert c.data.pump_target == 21
    assert c.data.pump_profile == "manual"
    assert c.data.mode == "night"
    assert all(room.target == 18 for room in c.data.rooms.values())
    assert hass.states.get("climate.pump").attributes["temperature"] == 21
    for _ in range(3):
        await c.async_evaluate()
    assert len(calls) == 1  # Native user call, no duplicate SHM command.
    registry = er.async_get(hass)
    mode = registry.async_get_entity_id("select", DOMAIN, f"{installation.entry_id}_pump_override")
    await hass.async_block_till_done()
    assert hass.states.get(mode).state == "manual"


async def test_each_room_and_pac_are_independent_and_auto_is_local(
    hass, installation, manual_installation, hass_admin_user
):
    from custom_components.smart_heat_manager.climate import RoomClimate
    from custom_components.smart_heat_manager.select import PumpMode

    c, _ = manual_installation
    living = RoomClimate(c, c.config["rooms"][0])
    bedroom = RoomClimate(c, c.config["rooms"][1])
    await bedroom.async_set_temperature(temperature=21.5)
    assert bedroom.preset_mode == "manual"
    assert c.data.rooms["bedroom"].target == 21.5
    assert c.data.rooms["living"].target == 18
    assert c.data.pump_target == 17
    await ui_temperature(hass, hass_admin_user, 22)
    await c.async_evaluate()
    await living.async_set_temperature(temperature=19.5)
    assert c.data.pump_target == 22
    assert c.data.rooms["bedroom"].target == 21.5
    assert c.data.rooms["living"].target == 19.5
    await bedroom.async_set_preset_mode("auto")
    assert c.data.rooms["bedroom"].target == 18
    assert c.data.rooms["living"].target == 19.5
    assert c.data.pump_target == 22
    # Let the PAC command interval elapse before an explicit early auto return.
    c.controller.last_sent.clear()
    await PumpMode(c).async_select_option("auto")
    assert c.data.pump_target == 17
    assert c.data.rooms["living"].target == 19.5
    assert living.preset_mode == "manual"
    assert c.override("mode") == "night"


async def test_manual_minus_and_repeated_clicks_use_latest_value_and_expiry(
    hass, manual_installation, hass_admin_user, freezer
):
    c, _ = manual_installation
    await ui_temperature(hass, hass_admin_user, 22)
    await c.async_evaluate()
    first = c.runtime["overrides"]["pump_target"]["until"]
    freezer.tick(timedelta(seconds=20))
    await ui_temperature(hass, hass_admin_user, 19)
    await ui_temperature(hass, hass_admin_user, 18)
    await c.async_evaluate()
    assert c.data.pump_target == 18
    assert c.runtime["overrides"]["pump_target"]["until"] > first
    until = c.runtime["overrides"]["pump_target"]["until"]
    # A normal temperature report must neither change the target nor extend time.
    state = hass.states.get("climate.pump")
    hass.states.async_set("climate.pump", state.state, dict(state.attributes) | {"current_temperature": 20.1})
    await hass.async_block_till_done()
    await c.async_evaluate()
    assert c.runtime["overrides"]["pump_target"]["until"] == until
    freezer.move_to(until)
    await c.async_evaluate()
    assert c.pump_manual_target is None
    assert c.data.pump_profile != "manual"
    assert c.data.pump_target == 20  # General night override also expired -> presence.
    assert hass.states.get("climate.pump").state == "heat"


async def test_manual_pac_survives_reload_without_renewing_expiry(
    hass, installation, manual_installation, hass_admin_user
):
    c, _ = manual_installation
    await ui_temperature(hass, hass_admin_user, 21)
    await c.async_evaluate()
    until = c.runtime["overrides"]["pump_target"]["until"]
    assert await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    c = installation.runtime_data
    assert c.armed
    assert c.data.pump_target == 21
    assert c.runtime["overrides"]["pump_target"]["until"] == until


async def test_automatic_and_other_thermostat_calls_do_not_create_pac_hold(hass, manual_installation, hass_admin_user):
    c, _ = manual_installation
    await c.transport.send(Command("climate.pump", "set_temperature", "temperature", 20, "temperature"))
    await hass.async_block_till_done()
    await c.async_evaluate()
    assert c.pump_manual_target is None
    await ui_temperature(hass, hass_admin_user, 23, "climate.other")
    await c.async_evaluate()
    assert c.pump_manual_target is None


async def test_manual_request_supersedes_pending_automatic_target_not_latched_fault(
    hass, manual_installation, hass_admin_user
):
    c, calls = manual_installation
    command = Command("climate.pump", "set_temperature", "temperature", 20, "temperature")
    c.controller.pending[command.key] = Pending(command, dt_util.utcnow())
    c.controller.fault = "command_not_applied:number.valve"
    await ui_temperature(hass, hass_admin_user, 21)
    await c.async_evaluate()
    assert c.data.pump_target == 21
    assert c.controller.fault == "command_not_applied:number.valve"
    assert c.controller.status == "emitter_fault"
    assert len(calls) == 1


async def test_ui_change_during_observation_never_arms_or_sends_shm_commands(
    hass, manual_installation, hass_admin_user
):
    c, calls = manual_installation
    await c.arm(False)
    await ui_temperature(hass, hass_admin_user, 21)
    await c.async_evaluate()
    assert not c.armed
    assert c.data.pump_target == 21
    assert c.controller.status == "observation"
    assert len(calls) == 1


async def test_denied_user_service_event_cannot_induce_integration_owned_write(
    hass, manual_installation, hass_admin_user
):
    c, calls = manual_installation
    denied = SimpleNamespace(is_active=True, permissions=SimpleNamespace(check_entity=lambda *_: False))
    with patch.object(hass.auth, "async_get_user", AsyncMock(return_value=denied)):
        hass.bus.async_fire(
            EVENT_CALL_SERVICE,
            {
                "domain": "climate",
                "service": "set_temperature",
                "service_data": {"entity_id": "climate.pump", "temperature": 25},
            },
            context=Context(user_id=hass_admin_user.id),
        )
        await hass.async_block_till_done()
        await c.async_evaluate()
    assert c.pump_manual_target is None
    assert calls == []


async def test_delayed_native_readback_is_not_duplicated_or_overwritten(hass, manual_installation, hass_admin_user):
    c, calls = manual_installation
    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {
            "domain": "climate",
            "service": "set_temperature",
            "service_data": {"entity_id": "climate.pump", "temperature": 21},
        },
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.async_block_till_done()
    assert c.pump_manual_events
    assert not c.permit_pump_temperature()  # An in-flight automatic cycle yields.
    await c.async_evaluate()
    assert c.data.pump_target == 21
    assert c.controller.pending["climate.pump:temperature"].command.value == 21
    assert calls == []  # Native request is already executing, do not repeat it.
    state = hass.states.get("climate.pump")
    hass.states.async_set("climate.pump", "heat", dict(state.attributes) | {"temperature": 21})
    await hass.async_block_till_done()
    await c.async_evaluate()
    assert "climate.pump:temperature" not in c.controller.pending
    assert c.controller.fault is None
    assert calls == []


async def test_native_manual_off_stays_off_even_with_pac_temperature_hold(hass, manual_installation, hass_admin_user):
    c, calls = manual_installation
    state = hass.states.get("climate.pump")
    hass.states.async_set("climate.pump", "off", dict(state.attributes))
    await hass.async_block_till_done()
    await ui_temperature(hass, hass_admin_user, 21)
    await c.async_evaluate()
    assert c.pump_manual_target == 21
    assert c.controller.status == "pump_off"
    assert hass.states.get("climate.pump").state == "off"
    assert len(calls) == 1  # Only the user's direct setpoint call.
