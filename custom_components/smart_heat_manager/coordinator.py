"""Event driven HA boundary, persistent preferences and expiring overrides."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import timedelta
from math import isfinite

from homeassistant.components import persistent_notification
from homeassistant.components.valve import ValveEntityFeature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .adapters import EntityState, pump_plan
from .const import DOMAIN, MODES
from .controller import Controller
from .emitters import emitter_plan, room_actuator_entities, room_emitters
from .engine import Engine
from .models import Snapshot, active_override, effective_config
from .validation import validate_config

_LOGGER = logging.getLogger(__name__)


class HATransport:
    def __init__(self, hass):
        self.hass = hass

    def state(self, entity_id):
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        attrs = dict(state.attributes)
        if state.domain == "climate" and self.hass.config.units.temperature_unit == "°F":
            for key in ("min_temp", "max_temp", "temperature", "current_temperature"):
                if attrs.get(key) is not None:
                    attrs[key] = (float(attrs[key]) - 32) * 5 / 9
            if attrs.get("target_temp_step"):
                attrs["target_temp_step"] = float(attrs["target_temp_step"]) * 5 / 9
        return EntityState(state.state, attrs)

    def has_service(self, domain, service):
        return self.hass.services.has_service(domain, service)

    async def send(self, command):
        domain = command.entity_id.split(".", 1)[0]
        _LOGGER.info(
            "Command %s.%s to %s: %s=%s", domain, command.service, command.entity_id, command.field, command.value
        )
        value = command.value
        if domain == "climate" and command.field == "temperature" and self.hass.config.units.temperature_unit == "°F":
            value = float(value) * 9 / 5 + 32
        await self.hass.services.async_call(
            domain, command.service, {"entity_id": command.entity_id, command.field: value}, blocking=True
        )


class HeatCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry)
        self.entry = entry
        self.config = effective_config(entry.data, entry.options)
        validate_config(self.config)
        self.engine = Engine()
        self.transport = HATransport(hass)
        self.controller = Controller(
            self.transport, dt_util.now(), int(ValveEntityFeature.SET_POSITION), self.permit_commands
        )
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.runtime = {"overrides": {}}
        self.armed = False
        self.lock = asyncio.Lock()
        self.cancel_scheduled = None
        self.closed = False
        self.last_reason = None
        self.last_alert = None
        self.snapshot = None

    @property
    def settings(self):
        return self.config["settings"] | self.runtime.get("numbers", {})

    @property
    def controlled_entities(self):
        return [
            self.settings["pump_entity"],
            *(entity for room in self.config["rooms"] for entity in room_actuator_entities(room)),
        ]

    async def async_start(self):
        saved = await self.store.async_load()
        if isinstance(saved, dict):
            self.runtime.update(saved)
        self.runtime.setdefault("overrides", {})
        try:
            validate_config({"settings": self.settings, "rooms": self.config["rooms"]})
        except ValueError:
            self.runtime.pop("numbers", None)
            _LOGGER.warning("Discarding daily numeric preferences incompatible with the updated options")
        tracked = {v for k, v in self.settings.items() if k.endswith("_entity") and v}
        for room in self.config["rooms"]:
            tracked.update([room["sensor"], *room_actuator_entities(room)])
        self.entry.async_on_unload(async_track_state_change_event(self.hass, list(tracked), self.schedule))
        self.entry.async_on_unload(async_track_time_interval(self.hass, self.schedule, timedelta(seconds=15)))
        self.entry.async_on_unload(self.shutdown)
        await self.async_evaluate()

    @callback
    def shutdown(self):
        self.closed = True
        self.armed = False
        if self.cancel_scheduled:
            self.cancel_scheduled()
            self.cancel_scheduled = None

    @callback
    def schedule(self, _event=None):
        if self.closed or self.cancel_scheduled is not None:
            return
        self.cancel_scheduled = async_call_later(self.hass, 0.25, self.run_scheduled)

    async def run_scheduled(self, _now):
        self.cancel_scheduled = None
        await self.async_evaluate()

    def fresh_state(self, entity_id, max_age=None):
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        last = getattr(state, "last_reported", state.last_updated)
        max_age = self.settings["sensor_max_age"] if max_age is None else max_age
        is_helper = state.domain in ("input_number", "input_boolean", "input_select")
        if max_age and not is_helper and (dt_util.utcnow() - last).total_seconds() > max_age:
            return None
        return state

    def text(self, key):
        age = 172800 if key.startswith("tempo_") else 0 if key == "presence_entity" else None
        state = self.fresh_state(self.settings.get(key), max_age=age)
        return state.state if state else None

    def numeric(self, entity_id, kind, allow_negative=False, *, max_age=None):
        state = self.fresh_state(entity_id, max_age=max_age)
        if state is None:
            return None
        raw = state.attributes.get("current_temperature") if state.domain == "climate" else state.state
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not isfinite(value):
            return None
        unit = (
            self.hass.config.units.temperature_unit
            if state.domain == "climate"
            else state.attributes.get("unit_of_measurement")
        )
        if kind == "temperature":
            if unit == "°F":
                value = (value - 32) * 5 / 9
            elif unit != "°C":
                return None
            return value if -40 <= value <= 100 else None
        if unit == "kW":
            value *= 1000
        elif unit != "W":
            return None
        return value if value >= 0 or allow_negative else None

    def build_snapshot(self):
        cfg = self.settings
        pump = self.fresh_state(cfg["pump_entity"], max_age=0)
        # Room sensors may suppress identical readings. Their HA timestamps are
        # not device heartbeats: trust the source integration's availability,
        # while retaining unit/range validation and strict ages for monitoring.
        temps = {r["id"]: self.numeric(r["sensor"], "temperature", max_age=0) for r in self.config["rooms"]}
        protection = self.text("protection_entity")
        monitors = [key for key in ("protection_entity", "water_in_entity", "water_out_entity") if cfg.get(key)]
        monitor_fault = any(self.fresh_state(cfg[key]) is None for key in monitors)
        monitor_fault = monitor_fault or any(
            self.numeric(cfg.get(key), "temperature") is None
            for key in ("water_in_entity", "water_out_entity")
            if cfg.get(key)
        )
        return Snapshot(
            now=dt_util.now(),
            temperatures=temps,
            pump_available=pump is not None,
            pump_on=pump is not None and pump.state != "off",
            actuators_available=all(
                self.fresh_state(e, max_age=0) is not None
                for r in self.config["rooms"]
                for e in room_actuator_entities(r)
            ),
            presence=self.text("presence_entity"),
            today=self.text("tempo_today_entity"),
            tomorrow=self.text("tempo_tomorrow_entity"),
            grid=self.numeric(cfg.get("grid_entity"), "power", allow_negative=True),
            production=self.numeric(cfg.get("production_entity"), "power"),
            house=self.numeric(cfg.get("house_entity"), "power"),
            pump_power=self.numeric(cfg.get("pump_power_entity"), "power"),
            protection=protection not in (None, "off"),
            water_in=self.numeric(cfg.get("water_in_entity"), "temperature"),
            water_out=self.numeric(cfg.get("water_out_entity"), "temperature"),
            monitoring_fault=monitor_fault,
        )

    def permit_commands(self):
        if not self.armed or self.closed or not self.runtime.get("automation_enabled", True):
            return False
        snapshot = self.build_snapshot()
        return (
            snapshot.pump_available
            and snapshot.actuators_available
            and all(t is not None for t in snapshot.temperatures.values())
            and not snapshot.protection
            and not snapshot.monitoring_fault
            and all(t is None or t <= self.settings["water_max"] for t in (snapshot.water_in, snapshot.water_out))
        )

    async def async_evaluate(self):
        async with self.lock:
            if self.closed:
                return
            cfg = {"settings": self.settings, "rooms": self.config["rooms"]}
            self.snapshot = self.build_snapshot()
            decision = self.engine.evaluate(cfg, self.snapshot, self.runtime)
            # Commands are still individually checked at the last boundary.
            armed = self.armed and all(
                self.settings[k]
                for k in ("control_enabled", "hydraulic_confirmed", "exclusive_confirmed", "capabilities_confirmed")
            )
            await self.controller.tick(cfg, decision, self.snapshot.now, armed)
            reason = (decision.state, decision.reason, self.controller.status, self.controller.fault)
            if reason != self.last_reason:
                _LOGGER.info("Decision %s (%s), controller %s", decision.state, decision.reason, self.controller.status)
                self.last_reason = reason
            alert = self.controller.fault or (", ".join(decision.faults) if decision.faults else None)
            if alert and alert != self.last_alert:
                persistent_notification.async_create(
                    self.hass,
                    f"Smart Heat Manager : {alert}. Commandes suspendues ; vérifier les diagnostics et l'installation.",
                    title="Smart Heat Manager",
                    notification_id=f"{DOMAIN}_{self.entry.entry_id}",
                )
            elif not alert and self.last_alert:
                persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_{self.entry.entry_id}")
            self.last_alert = alert
            self.async_set_updated_data(decision)

    async def save(self):
        self.store.async_delay_save(lambda: self.runtime, 1)
        await self.async_evaluate()

    async def set_preference(self, key, value, room_id=None):
        if room_id:
            self.runtime.setdefault(key, {})[room_id] = value
        else:
            self.runtime[key] = value
        await self.save()

    async def set_override(self, key, value):
        self.runtime["overrides"][key] = {
            "value": value,
            "until": (dt_util.utcnow() + timedelta(minutes=self.settings["override_minutes"])).isoformat(),
        }
        await self.save()

    async def clear_override(self, key):
        self.runtime["overrides"].pop(key, None)
        await self.save()

    def override(self, key):
        return active_override(self.runtime["overrides"], key, dt_util.now())

    async def set_mode(self, mode):
        if mode not in MODES:
            raise HomeAssistantError("Mode inconnu")
        if mode == "auto":
            self.runtime["overrides"].clear()
            await self.save()
        else:
            await self.set_override("mode", mode)

    async def set_number(self, key, value, room_id=None):
        if not isfinite(value):
            raise HomeAssistantError("Valeur non finie")
        if room_id:
            if not 5 <= value <= 35:
                raise HomeAssistantError("Température hors limites")
            self.runtime.setdefault("room_solar_target", {})[room_id] = value
        else:
            candidate = self.settings | {key: value}
            try:
                validate_config({"settings": candidate, "rooms": self.config["rooms"]})
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            self.runtime.setdefault("numbers", {})[key] = value
        await self.save()

    def capabilities(self):
        result = {}
        relevant = {
            "hvac_modes",
            "supported_features",
            "min_temp",
            "max_temp",
            "target_temp_step",
            "min",
            "max",
            "step",
            "unit_of_measurement",
        }
        for entity in self.controlled_entities:
            state = self.transport.state(entity)
            result[entity] = {
                "state": state.state if state else None,
                "capabilities": {k: v for k, v in state.attributes.items() if k in relevant} if state else {},
            }
        return result

    async def arm(self, value):
        if not value:
            self.armed = False
            await self.async_evaluate()
            return
        if not all(
            self.settings[k]
            for k in ("control_enabled", "hydraulic_confirmed", "exclusive_confirmed", "capabilities_confirmed")
        ):
            raise HomeAssistantError(
                "Valider les capacités, le débit indépendant et l'arrêt des anciens pilotes dans les options Sécurités."
            )
        if not self.data or self.data.faults or self.controller.fault:
            raise HomeAssistantError("Résoudre les défauts avant l'armement.")
        try:
            commands = [
                pump_plan(
                    self.settings["pump_entity"],
                    self.transport.state(self.settings["pump_entity"]),
                    self.settings["pump_mode"],
                    False,
                )
            ]
            for room in self.config["rooms"]:
                for emitter in room_emitters(room):
                    commands.extend(
                        emitter_plan(
                            emitter,
                            self.transport,
                            room,
                            0,
                            valve_position_feature=int(ValveEntityFeature.SET_POSITION),
                        )
                    )
            if any(not self.transport.has_service(c.entity_id.split(".")[0], c.service) for c in commands):
                raise ValueError("service_missing")
        except (ValueError, TypeError) as err:
            raise HomeAssistantError(f"Capacités non validées : {err}") from err
        self.armed = True
        await self.async_evaluate()

    async def reset_fault(self):
        self.armed = False
        self.controller.reset_fault()
        await self.async_evaluate()

    def diagnostic_data(self):
        return {
            "config": self.config,
            "runtime": self.runtime,
            "armed": self.armed,
            "decision": asdict(self.data) if self.data else None,
            "controller": {
                "state": self.controller.status,
                "fault": self.controller.fault,
                "pending": {
                    key: {"command": asdict(item.command), "since": item.since.isoformat()}
                    for key, item in self.controller.pending.items()
                },
            },
            "capabilities": self.capabilities(),
        }
