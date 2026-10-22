"""Acknowledged setpoints with a narrowly owned Tempo stop/resume exception."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .adapters import Command, Transport, pump_target_value, pump_temperature_plan, pump_tempo_mode_plan
from .emitters import emitter_plan, room_actuator_entities, room_emitters
from .models import Decision


@dataclass
class Pending:
    command: Command
    since: datetime


class ControlSuspended(Exception):
    """The operator or current safety inputs revoked further commands."""


class Controller:
    def __init__(
        self,
        transport: Transport,
        now: datetime,
        valve_position_feature: int = 4,
        permit: Callable[[], bool] | None = None,
    ) -> None:
        now = now.astimezone(UTC)
        self.transport = transport
        self.permit = permit or (lambda: True)
        self.send_timeout = 30.0
        self.valve_position_feature = valve_position_feature
        self.pending: dict[str, Pending] = {}
        self.last_sent: dict[str, datetime] = {}
        self.fault: str | None = None
        self.status = "observation"
        self.observed_on: bool | None = None
        self.transition = now
        self.tempo_state: dict = {}
        self.save_tempo = None
        self.mode_authorization: Command | None = None
        self.save_state = None

    async def checkpoint(self):
        if self.save_state is not None:
            await self.save_state()

    async def checkpoint_tempo(self):
        if self.save_tempo is not None:
            await self.save_tempo()

    def owns_tempo_stop(self, entity_id):
        return self.tempo_state.get("entity_id") == entity_id and self.tempo_state.get("confirmed") is True

    def may_resume_tempo(self, cfg, decision, now):
        if not self.owns_tempo_stop(cfg["pump_entity"]) or decision.pump_tempo_stop:
            return False
        try:
            until = datetime.fromisoformat(self.tempo_state["until"])
            return bool(until.tzinfo and (now >= until or decision.override_active or not cfg["tempo_enabled"]))
        except (KeyError, TypeError, ValueError):
            return False

    async def apply_tempo_mode(self, command, now, interval):
        self.mode_authorization = command
        try:
            return await self.apply(command, now, interval)
        finally:
            self.mode_authorization = None

    def reset_fault(self) -> None:
        self.fault = None
        self.pending.clear()

    def emitter_fault(self, config: dict) -> bool:
        """Only a known emitter acknowledgement fault may spare the native PAC.

        Keep the fault latched, including after a late report or restart. Never
        reinterpret transport, storage, unknown-entity or PAC faults as local.
        """
        prefix = "command_not_applied:"
        if not self.fault or not self.fault.startswith(prefix):
            return False
        entity = self.fault[len(prefix) :]
        return entity != config["settings"]["pump_entity"] and any(
            entity in room_actuator_entities(room) for room in config["rooms"]
        )

    def check_pending(self, now: datetime, timeout: float, pump_entity: str | None = None) -> None:
        for key, item in list(self.pending.items()):
            if item.command.matches(self.transport.state(item.command.entity_id)):
                del self.pending[key]
            elif (now - item.since).total_seconds() >= timeout:
                # A late emitter must never mask a PAC fault. Existing faults
                # remain latched even when a delayed report finally matches.
                if self.fault is None or item.command.entity_id == pump_entity:
                    self.fault = f"command_not_applied:{item.command.entity_id}"

    async def apply(self, command: Command, now: datetime, interval: float) -> bool:
        if not self.permit():
            raise ControlSuspended
        if command.key in self.pending:
            return False
        if command.matches(self.transport.state(command.entity_id)):
            return True
        if command.key in self.last_sent and (now - self.last_sent[command.key]).total_seconds() < interval:
            return False
        domain = command.entity_id.split(".", 1)[0]
        if not self.transport.has_service(domain, command.service):
            raise ValueError(f"service_missing:{domain}.{command.service}")
        # Record before awaiting: subsequent state events cannot duplicate the command.
        self.pending[command.key] = Pending(command, now)
        self.last_sent[command.key] = now
        # Persist before the physical write, including an unacknowledged intent.
        await self.checkpoint()
        if not self.permit():
            raise ControlSuspended
        async with asyncio.timeout(self.send_timeout):
            await self.transport.send(command)
        return command.matches(self.transport.state(command.entity_id))

    async def tick(self, config: dict, decision: Decision, now: datetime, armed: bool) -> None:
        now = now.astimezone(UTC)
        cfg = config["settings"]
        self.send_timeout = min(30.0, cfg["ack_timeout"])
        state = self.transport.state(cfg["pump_entity"])
        on = state is not None and state.available and state.state != "off"
        if self.observed_on is None or on != self.observed_on:
            self.transition = now
            self.observed_on = on
        if not armed:
            self.status = "observation"
            self.pending.clear()
            return
        if self.tempo_state and self.tempo_state.get("entity_id") != cfg["pump_entity"]:
            self.tempo_state.clear()
            await self.checkpoint_tempo()
        pending_mode = self.pending.get(f"{cfg['pump_entity']}:hvac_mode")
        if state is not None and state.state == "off" and pending_mode and pending_mode.command.value == "off":
            self.tempo_state["confirmed"] = True
            await self.checkpoint_tempo()
        if self.fault and not self.emitter_fault(config):
            self.status = "command_fault"
            return
        self.check_pending(now, cfg["ack_timeout"], cfg["pump_entity"])
        await self.checkpoint()
        if self.fault and not self.emitter_fault(config):
            self.status = "command_fault"
            return
        if decision.state in ("fault", "paused"):
            self.status = "suspended"
            return
        try:
            if decision.pump_tempo_stop:
                if state is None or not state.available:
                    raise ValueError("pump_unavailable")
                if state.state == "off":
                    self.status = "tempo_stopped" if self.owns_tempo_stop(cfg["pump_entity"]) else "pump_off"
                    return
                stop = pump_tempo_mode_plan(cfg["pump_entity"], state, cfg["pump_mode"], "off")
                if not decision.pump_tempo_until:
                    raise ValueError("tempo_deadline_missing")
                if not self.tempo_state:
                    self.tempo_state.update(
                        entity_id=cfg["pump_entity"], mode=state.state, until=decision.pump_tempo_until, confirmed=False
                    )
                    # Persist intent before the service call; only an acknowledged
                    # stop earns permission to restore. An ambiguous stop fails off.
                    await self.checkpoint_tempo()
                ready = await self.apply_tempo_mode(stop, now, cfg["command_interval"])
                if ready:
                    self.tempo_state["confirmed"] = True
                    await self.checkpoint_tempo()
                self.status = "tempo_stopped" if ready else "tempo_stopping"
                return
            resuming = state is not None and state.state == "off" and self.may_resume_tempo(cfg, decision, now)
            if state is not None and state.state == "off" and not resuming:
                self.status = "pump_off"
                return
            if state is not None and state.state == cfg["pump_mode"] and self.tempo_state:
                self.tempo_state.clear()
                await self.checkpoint_tempo()
            # Check every capability before issuing any command.
            if decision.pump_target is None:
                self.status = "suspended"
                return
            if resuming:
                pump_target_value(state, decision.pump_target)
                pump = pump_tempo_mode_plan(cfg["pump_entity"], state, cfg["pump_mode"], self.tempo_state["mode"])
            else:
                pump = pump_temperature_plan(cfg["pump_entity"], state, cfg["pump_mode"], decision.pump_target)
            plans = []
            # A confirmed independent hydraulic flow is mandatory for the
            # integration. The native PAC does not depend on room valve ACKs.
            # Leave ALL emitter commands suspended while an emitter fault is
            # latched; the operator must investigate/reset them explicitly.
            for room in [] if self.emitter_fault(config) else config["rooms"]:
                opening = decision.rooms[room["id"]].opening
                for emitter in room_emitters(room):
                    plans.append(
                        emitter_plan(
                            emitter,
                            self.transport,
                            room,
                            opening,
                            valve_position_feature=self.valve_position_feature,
                        )
                    )
            if any(
                not self.transport.has_service(c.entity_id.split(".")[0], c.service)
                for c in [pump, *(c for plan in plans for c in plan)]
            ):
                raise ValueError("service_missing")
            all_ready = True
            for commands in plans:
                for command in commands:
                    ready = await self.apply(command, now, cfg["command_interval"])
                    all_ready = all_ready and ready
                    if not ready:
                        break
            if resuming:
                if await self.apply_tempo_mode(pump, now, cfg["command_interval"]):
                    self.tempo_state.clear()
                    await self.checkpoint_tempo()
                self.status = "tempo_resuming"
                return
            # Re-read mode after awaited head commands; never wake an externally
            # stopped pump or overwrite a switch to cooling/another native mode.
            current = self.transport.state(cfg["pump_entity"])
            if current is not None and current.state == "off":
                self.status = "pump_off"
                return
            pump = pump_temperature_plan(cfg["pump_entity"], current, cfg["pump_mode"], decision.pump_target)
            ready = await self.apply(pump, now, cfg["command_interval"])
            if self.emitter_fault(config):
                self.status = "emitter_fault"
            elif not all_ready:
                self.status = "opening_emitters"
            else:
                self.status = "running" if ready else "adjusting_setpoint"
        except ControlSuspended:
            self.status = "suspended"
        except Exception as err:  # Service implementations can raise third-party errors.
            self.fault = f"{type(err).__name__}:{err}"
            self.status = "command_fault"
