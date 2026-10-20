"""Lifecycle, native entities, events, commands and graphical flow on real HA."""

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.smart_heat_manager.const import DOMAIN, ROOM_DEFAULTS
from custom_components.smart_heat_manager.diagnostics import async_get_config_entry_diagnostics

ROOM_INPUT_DEFAULTS = {key: value for key, value in ROOM_DEFAULTS.items() if key != "trvzb_heads"}


async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_setup_entities_and_unload(hass, installation):
    c = await setup(hass, installation)
    assert c.data.state == "heating"
    assert c.controller.status == "observation"
    assert not c.armed
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("climate", DOMAIN, f"{installation.entry_id}_room_living_climate")
    state = hass.states.get(entity_id)
    assert state.attributes["current_temperature"] == 19
    assert state.attributes["temperature"] == 20
    assert await hass.config_entries.async_unload(installation.entry_id)
    assert c.closed


async def test_sensor_loss_and_recovery(hass, installation):
    c = await setup(hass, installation)
    hass.states.async_set("sensor.living", "unavailable")
    await c.async_evaluate()
    assert c.data.state == "fault"
    assert not c.data.pump_requested
    hass.states.async_set("sensor.living", "19", {"unit_of_measurement": "°C"})
    await c.async_evaluate()
    assert c.data.state == "heating"


async def test_units_and_grid_sign(hass, installation):
    c = await setup(hass, installation)
    hass.states.async_set("sensor.grid", "-3.5", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.living", "68", {"unit_of_measurement": "°F"})
    await c.async_evaluate()
    assert c.data.surplus == 3500
    assert c.data.rooms["living"].temperature == 20
    hass.states.async_set("sensor.grid", "3.5", {"unit_of_measurement": "kWh"})
    await c.async_evaluate()
    assert c.data.surplus is None


async def test_arming_requires_confirmations(hass, installation):
    c = await setup(hass, installation)
    with pytest.raises(HomeAssistantError):
        await c.arm(True)
    assert not c.armed


async def test_diagnostics_redact_entities(hass, installation):
    await setup(hass, installation)
    data = await async_get_config_entry_diagnostics(hass, installation)
    assert "sensor.living" not in str(data)
    assert "climate.pump" not in str(data)
    assert "Salon" not in str(data)


async def test_override_storage_and_reload_disarms(hass, installation):
    c = await setup(hass, installation)
    await c.set_override("tempo_bypass", True)
    await c.store.async_save(c.runtime)
    assert c.override("tempo_bypass") is True
    await hass.config_entries.async_reload(installation.entry_id)
    await hass.async_block_till_done()
    assert not installation.runtime_data.armed
    assert installation.runtime_data.override("tempo_bypass") is True


async def menu(manager, result, step):
    return await manager.async_configure(result["flow_id"], {"next_step_id": step})


async def test_options_room_edit_preserves_id_and_delete(hass, installation):
    await setup(hass, installation)
    manager = hass.config_entries.options
    result = await manager.async_init(installation.entry_id)
    result = await menu(manager, result, "rooms")
    result = await menu(manager, result, "edit_room")
    result = await manager.async_configure(result["flow_id"], {"room": "living"})
    assert result["step_id"] == "room"
    room = ROOM_INPUT_DEFAULTS | {"name": "Séjour", "sensor": "sensor.living", "actuators": ["number.valve"]}
    result = await manager.async_configure(result["flow_id"], room)
    result = await menu(manager, result, "menu")
    result = await menu(manager, result, "finish")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert installation.options["rooms"][0]["id"] == "living"
    assert installation.options["rooms"][0]["name"] == "Séjour"


async def test_user_flow_builds_installation(hass):
    hass.states.async_set("climate.pump", "off", {"hvac_modes": ["off", "heat"]})
    hass.states.async_set("sensor.living", "19", {"unit_of_measurement": "°C"})
    hass.states.async_set("number.valve", "0", {"min": 0, "max": 100, "unit_of_measurement": "%"})
    manager = hass.config_entries.flow
    result = await manager.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "user"
    result = await manager.async_configure(result["flow_id"], {"pump_entity": "climate.pump"})
    result = await menu(manager, result, "rooms")
    result = await menu(manager, result, "add_room")
    room = ROOM_INPUT_DEFAULTS | {"name": "Salon", "sensor": "sensor.living", "actuators": ["number.valve"]}
    result = await manager.async_configure(result["flow_id"], room)
    assert result["step_id"] == "rooms"
    result = await menu(manager, result, "menu")
    result = await menu(manager, result, "finish")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert result["result"].runtime_data.controller.status == "observation"


async def test_finish_error_returns_to_menu(hass, installation):
    await setup(hass, installation)
    manager = hass.config_entries.options
    result = await manager.async_init(installation.entry_id)
    result = await menu(manager, result, "rooms")
    result = await menu(manager, result, "delete_room")
    result = await manager.async_configure(result["flow_id"], {"room": "living"})
    result = await menu(manager, result, "menu")
    result = await menu(manager, result, "finish")
    assert result["errors"]["base"] == "room_required"
    result = await manager.async_configure(result["flow_id"], {})
    assert result["step_id"] == "menu"


async def test_options_pair_two_trvzb_heads_and_monitor_all_members(hass, installation):
    for suffix in ("one", "two"):
        hass.states.async_set(f"climate.head_{suffix}", "off", {"hvac_modes": ["off", "heat", "auto"]})
        for role, value in (("opening", "0"), ("closing", "100")):
            hass.states.async_set(
                f"number.{suffix}_{role}", value, {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"}
            )
    await setup(hass, installation)
    manager = hass.config_entries.options
    result = await manager.async_init(installation.entry_id)
    result = await menu(manager, result, "rooms")
    result = await menu(manager, result, "edit_room")
    result = await manager.async_configure(result["flow_id"], {"room": "living"})
    room = ROOM_INPUT_DEFAULTS | {"name": "Salon", "sensor": "sensor.living", "actuators": [], "configure_trvzb": True}
    result = await manager.async_configure(result["flow_id"], room)
    assert result["step_id"] == "trvzb_heads"
    for suffix in ("one", "two"):
        result = await menu(manager, result, "add_trvzb")
        assert result["step_id"] == "trvzb"
        result = await manager.async_configure(
            result["flow_id"],
            {
                "climate_entity": f"climate.head_{suffix}",
                "opening_entity": f"number.{suffix}_opening",
                "closing_entity": f"number.{suffix}_closing",
                "firmware_confirmed": True,
            },
        )
        assert result["step_id"] == "trvzb_heads"
    result = await menu(manager, result, "room_done")
    result = await menu(manager, result, "menu")
    result = await menu(manager, result, "finish")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    heads = installation.options["rooms"][0]["trvzb_heads"]
    assert len(heads) == 2
    c = installation.runtime_data
    assert len(c.controlled_entities) == 7  # PAC and two three-entity groups
    assert c.controller.status == "observation"
    diag = await async_get_config_entry_diagnostics(hass, installation)
    assert "number.one_closing" not in str(diag)
    assert "climate.head_one" not in str(diag)
    hass.states.async_set("number.two_closing", "unavailable")
    await c.async_evaluate()
    assert "actuator_unavailable" in c.data.faults
    # Editing/removing a head keeps the room ID and the other head's association.
    result = await manager.async_init(installation.entry_id)
    result = await menu(manager, result, "rooms")
    result = await menu(manager, result, "edit_room")
    result = await manager.async_configure(result["flow_id"], {"room": "living"})
    result = await manager.async_configure(result["flow_id"], room)
    result = await menu(manager, result, "delete_trvzb")
    result = await manager.async_configure(result["flow_id"], {"head": heads[1]["id"]})
    result = await menu(manager, result, "room_done")
    result = await menu(manager, result, "menu")
    result = await menu(manager, result, "finish")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert installation.options["rooms"][0]["id"] == "living"
    assert installation.options["rooms"][0]["trvzb_heads"] == [heads[0]]


async def test_trvzb_wizard_rejects_same_number_for_both_roles(hass, installation):
    await setup(hass, installation)
    manager = hass.config_entries.options
    result = await manager.async_init(installation.entry_id)
    result = await menu(manager, result, "rooms")
    result = await menu(manager, result, "edit_room")
    result = await manager.async_configure(result["flow_id"], {"room": "living"})
    result = await manager.async_configure(
        result["flow_id"],
        ROOM_INPUT_DEFAULTS
        | {
            "name": "Salon",
            "sensor": "sensor.living",
            "actuators": [],
            "configure_trvzb": True,
        },
    )
    result = await menu(manager, result, "add_trvzb")
    result = await manager.async_configure(
        result["flow_id"],
        {
            "climate_entity": "climate.head",
            "opening_entity": "number.shared",
            "closing_entity": "number.shared",
            "firmware_confirmed": True,
        },
    )
    assert result["errors"]["base"] == "duplicate_actuator"


async def test_trvzb_wizard_requires_firmware_confirmation(hass, installation):
    await setup(hass, installation)
    manager = hass.config_entries.options
    result = await manager.async_init(installation.entry_id)
    result = await menu(manager, result, "rooms")
    result = await menu(manager, result, "edit_room")
    result = await manager.async_configure(result["flow_id"], {"room": "living"})
    result = await manager.async_configure(
        result["flow_id"],
        ROOM_INPUT_DEFAULTS
        | {
            "name": "Salon",
            "sensor": "sensor.living",
            "actuators": [],
            "configure_trvzb": True,
        },
    )
    result = await menu(manager, result, "add_trvzb")
    result = await manager.async_configure(
        result["flow_id"],
        {
            "climate_entity": "climate.head",
            "opening_entity": "number.opening",
            "closing_entity": "number.closing",
            "firmware_confirmed": False,
        },
    )
    assert result["errors"]["base"] == "trvzb_firmware_required"
