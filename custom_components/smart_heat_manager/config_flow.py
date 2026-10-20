"""Native setup and editable options, including stable room CRUD."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import DEFAULTS, DOMAIN, ROOM_DEFAULTS
from .emitters import room_actuator_entities
from .models import effective_config
from .validation import validate_config


def entity(domains: list[str], multiple: bool = False):
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domains, multiple=multiple))


def number(low: float, high: float, step: float = 1, unit: str | None = None):
    kwargs = {"min": low, "max": high, "step": step, "mode": "box"}
    if unit:
        kwargs["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**kwargs))


BOOL = selector.BooleanSelector()
POWER = entity(["sensor", "input_number"])
TEMP = entity(["sensor", "climate", "input_number"])

SECTIONS = {
    "system": {
        "pump_entity": entity(["climate"]),
        "pump_mode": selector.SelectSelector(
            selector.SelectSelectorConfig(options=["heat", "auto"], translation_key="pump_mode")
        ),
        "pump_power_entity": POWER,
        "water_in_entity": TEMP,
        "water_out_entity": TEMP,
        "protection_entity": entity(["binary_sensor", "input_boolean"]),
    },
    "presence": {
        "presence_enabled": BOOL,
        "presence_entity": entity(["person", "device_tracker", "binary_sensor", "input_boolean"]),
        "presence_delay": number(0, 3600, unit="s"),
        "override_minutes": number(1, 1440, unit="min"),
    },
    "tempo": {
        "tempo_enabled": BOOL,
        "tempo_today_entity": entity(["sensor", "input_select"]),
        "tempo_tomorrow_entity": entity(["sensor", "input_select"]),
        "tempo_unknown_blocks": BOOL,
        "preheat_enabled": BOOL,
        "preheat_start": number(0, 5, unit="h"),
        "preheat_delta": number(0, 3, 0.1, "°C"),
        "white_delta": number(-5, 3, 0.1, "°C"),
        "red_delta": number(-5, 3, 0.1, "°C"),
    },
    "solar": {
        "solar_enabled": BOOL,
        "production_entity": POWER,
        "house_entity": POWER,
        "grid_entity": POWER,
        "grid_export_positive": BOOL,
        "house_includes_pump": BOOL,
        "solar_red_allowed": BOOL,
        "solar_start": number(0, 20000, 50, "W"),
        "solar_hold": number(0, 20000, 50, "W"),
        "solar_margin": number(0, 5000, 50, "W"),
        "solar_hysteresis": number(0, 2000, 50, "W"),
        "solar_delay": number(0, 7200, unit="s"),
        "solar_min_on": number(60, 14400, unit="s"),
        "solar_stop_delay": number(0, 7200, unit="s"),
    },
    "safety": {
        "control_enabled": BOOL,
        "hydraulic_confirmed": BOOL,
        "exclusive_confirmed": BOOL,
        "capabilities_confirmed": BOOL,
        "min_on": number(300, 14400, unit="s"),
        "min_off": number(300, 14400, unit="s"),
        "demand_delay": number(0, 3600, unit="s"),
        "drain_delay": number(60, 3600, unit="s"),
        "command_interval": number(15, 900, unit="s"),
        "ack_timeout": number(30, 1800, unit="s"),
        "sensor_max_age": number(60, 86400, unit="s"),
        "water_max": number(25, 80, 0.5, "°C"),
    },
}
ROOM_FIELDS = {
    "name": selector.TextSelector(),
    "sensor": TEMP,
    "actuators": entity(["climate", "number", "valve"], True),
    "configure_trvzb": BOOL,
    "actuator_notes": selector.TextSelector(),
    **{
        key: number(5, 35, 0.1, "°C")
        for key in ("present", "absent", "night", "holiday", "manual", "solar", "frost", "valve_hot", "valve_cold")
    },
    "hysteresis": number(0.1, 3, 0.1, "°C"),
    "gain": number(1, 100, 1, "%/°C"),
    "enabled": BOOL,
    "solar_enabled": BOOL,
}
TRVZB_FIELDS = {
    "climate_entity": entity(["climate"]),
    "opening_entity": entity(["number"]),
    "closing_entity": entity(["number"]),
    "firmware_confirmed": BOOL,
}


def schema(fields: dict, values: dict) -> vol.Schema:
    result = {}
    for key, validator in fields.items():
        optional = key.endswith("_entity") and key != "pump_entity" or key in ("actuator_notes", "actuators")
        if optional:
            marker = vol.Optional(key, description={"suggested_value": values[key]} if values.get(key) else {})
        else:
            marker = vol.Required(key, default=values[key]) if key in values else vol.Required(key)
        result[marker] = validator
    return vol.Schema(result)


class FlowMixin:
    working: dict
    editing: str | None = None
    pending_room: dict | None = None
    editing_head: str | None = None

    def owned_entity(self, entity_id: str) -> bool:
        record = er.async_get(self.hass).async_get(entity_id)
        return record is not None and record.platform == DOMAIN

    def check(self) -> None:
        validate_config(self.working)
        cfg = self.working["settings"]
        selected = [v for k, v in cfg.items() if k.endswith("_entity") and v]
        for room in self.working["rooms"]:
            selected.extend([room["sensor"], *room_actuator_entities(room)])
        if any(self.owned_entity(value) for value in selected):
            raise ValueError("recursive_entity")

    async def async_step_menu(self, user_input=None):
        return self.async_show_menu(
            step_id="menu", menu_options=["system", "presence", "tempo", "solar", "safety", "rooms", "finish"]
        )

    async def section(self, key, user_input):
        errors = {}
        if user_input is not None:
            previous = deepcopy(self.working["settings"])
            for field in SECTIONS[key]:
                self.working["settings"].pop(field, None)
            self.working["settings"].update(user_input)
            # Validate all invariants at commit; keep section editing possible while
            # optional source groups are being assembled.
            if (
                key == "safety"
                and user_input["control_enabled"]
                and not all(
                    user_input[k] for k in ("hydraulic_confirmed", "exclusive_confirmed", "capabilities_confirmed")
                )
            ):
                errors["base"] = "confirmations_required"
                self.working["settings"] = previous
            else:
                return await self.async_step_menu()
        return self.async_show_form(
            step_id=key, data_schema=schema(SECTIONS[key], self.working["settings"]), errors=errors
        )

    async def async_step_system(self, user_input=None):
        return await self.section("system", user_input)

    async def async_step_presence(self, user_input=None):
        return await self.section("presence", user_input)

    async def async_step_tempo(self, user_input=None):
        return await self.section("tempo", user_input)

    async def async_step_solar(self, user_input=None):
        return await self.section("solar", user_input)

    async def async_step_safety(self, user_input=None):
        return await self.section("safety", user_input)

    async def async_step_rooms(self, user_input=None):
        options = ["add_room"]
        if self.working["rooms"]:
            options.extend(["edit_room", "delete_room"])
        options.append("menu")
        return self.async_show_menu(step_id="rooms", menu_options=options)

    async def async_step_add_room(self, user_input=None):
        self.editing = None
        self.pending_room = None
        return await self.async_step_room()

    async def choose_room(self, step, user_input):
        if user_input is not None:
            self.editing = user_input["room"]
            self.pending_room = None
            if step == "delete_room":
                self.working["rooms"] = [r for r in self.working["rooms"] if r["id"] != self.editing]
                return await self.async_step_rooms()
            return await self.async_step_room()
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(
                {
                    vol.Required("room"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[{"value": r["id"], "label": r["name"]} for r in self.working["rooms"]]
                        )
                    )
                }
            ),
        )

    async def async_step_edit_room(self, user_input=None):
        return await self.choose_room("edit_room", user_input)

    async def async_step_delete_room(self, user_input=None):
        return await self.choose_room("delete_room", user_input)

    async def async_step_room(self, user_input=None):
        current = deepcopy(
            self.pending_room or next((r for r in self.working["rooms"] if r["id"] == self.editing), ROOM_DEFAULTS)
        )
        current["configure_trvzb"] = bool(current.get("trvzb_heads"))
        if user_input is not None:
            values = dict(user_input)
            configure_trvzb = values.pop("configure_trvzb", False)
            self.pending_room = deepcopy(
                ROOM_DEFAULTS
                | values
                | {
                    "id": self.editing or current.get("id") or uuid4().hex,
                    "trvzb_heads": current.get("trvzb_heads", []),
                }
            )
            if configure_trvzb:
                return await self.async_step_trvzb_heads()
            return await self.async_step_room_done()
        return self.async_show_form(step_id="room", data_schema=schema(ROOM_FIELDS, current))

    def candidate_room(self, room):
        candidate = deepcopy(self.working)
        candidate["rooms"] = [r for r in candidate["rooms"] if r["id"] != self.editing] + [room]
        check_settings = DEFAULTS | {"pump_entity": candidate["settings"]["pump_entity"]}
        validate_config({"settings": check_settings, "rooms": candidate["rooms"]})
        if any(self.owned_entity(e) for e in [room["sensor"], *room_actuator_entities(room)]):
            raise ValueError("recursive_entity")
        return candidate

    async def async_step_room_done(self, user_input=None):
        try:
            self.working = self.candidate_room(self.pending_room)
        except ValueError as err:
            values = self.pending_room | {"configure_trvzb": bool(self.pending_room.get("trvzb_heads"))}
            return self.async_show_form(
                step_id="room", data_schema=schema(ROOM_FIELDS, values), errors={"base": str(err)}
            )
        self.pending_room = None
        return await self.async_step_rooms()

    async def async_step_room_settings(self, user_input=None):
        return await self.async_step_room()

    async def async_step_trvzb_heads(self, user_input=None):
        options = ["add_trvzb"]
        if self.pending_room["trvzb_heads"]:
            options.extend(["edit_trvzb", "delete_trvzb"])
        options.extend(["room_done", "room_settings"])
        return self.async_show_menu(step_id="trvzb_heads", menu_options=options)

    async def async_step_add_trvzb(self, user_input=None):
        self.editing_head = None
        return await self.async_step_trvzb()

    async def choose_trvzb(self, step, user_input):
        if user_input is not None:
            self.editing_head = user_input["head"]
            if step == "delete_trvzb":
                self.pending_room["trvzb_heads"] = [
                    h for h in self.pending_room["trvzb_heads"] if h["id"] != self.editing_head
                ]
                return await self.async_step_trvzb_heads()
            return await self.async_step_trvzb()
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(
                {
                    vol.Required("head"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": h["id"], "label": h["climate_entity"]}
                                for h in self.pending_room["trvzb_heads"]
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_edit_trvzb(self, user_input=None):
        return await self.choose_trvzb("edit_trvzb", user_input)

    async def async_step_delete_trvzb(self, user_input=None):
        return await self.choose_trvzb("delete_trvzb", user_input)

    async def async_step_trvzb(self, user_input=None):
        current = next(
            (h for h in self.pending_room["trvzb_heads"] if h["id"] == self.editing_head), {"firmware_confirmed": False}
        )
        errors = {}
        if user_input is not None:
            head = dict(user_input) | {"id": self.editing_head or uuid4().hex}
            room = deepcopy(self.pending_room)
            room["trvzb_heads"] = [h for h in room["trvzb_heads"] if h["id"] != self.editing_head] + [head]
            try:
                self.candidate_room(room)
            except ValueError as err:
                errors["base"] = str(err)
                current = head
            else:
                self.pending_room = room
                return await self.async_step_trvzb_heads()
        # Every entity is required here, unlike optional installation monitors.
        data_schema = vol.Schema(
            {
                vol.Required(key, default=current[key]) if key in current else vol.Required(key): validator
                for key, validator in TRVZB_FIELDS.items()
            }
        )
        return self.async_show_form(step_id="trvzb", data_schema=data_schema, errors=errors)

    async def async_step_finish(self, user_input=None):
        if user_input is not None:
            return await self.async_step_menu()
        try:
            self.check()
        except ValueError as err:
            return self.async_show_form(step_id="finish", data_schema=vol.Schema({}), errors={"base": str(err)})
        return self.async_create_entry(
            title="Smart Heat Manager" if isinstance(self, SmartHeatFlow) else "", data=self.working
        )


class SmartHeatFlow(FlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        self.working = {"settings": dict(DEFAULTS), "rooms": []}
        if user_input is not None:
            self.working["settings"].update(user_input)
            return await self.async_step_menu()
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required("pump_entity"): entity(["climate"])})
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmartHeatOptionsFlow()


class SmartHeatOptionsFlow(FlowMixin, config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        self.working = deepcopy(effective_config(self.config_entry.data, self.config_entry.options))
        return await self.async_step_menu()
