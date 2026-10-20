"""Acknowledged emitters and heat-pump setpoints; never heat-pump mode commands."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .adapters import Command, Transport, pump_temperature_plan
from .emitters import emitter_plan, room_emitters
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

    def reset_fault(self) -> None:
        self.fault = None
        self.pending.clear()

    def check_pending(self, now: datetime, timeout: float) -> None:
        for key, item in list(self.pending.items()):
            if item.command.matches(self.transport.state(item.command.entity_id)):
                del self.pending[key]
            elif (now - item.since).total_seconds() >= timeout:
                self.fault = f"command_not_applied:{item.command.entity_id}"

    async def apply(self, command: Command, now: datetime, interval: float) -> bool:
        if not self.permit():
            raise ControlSuspended
        if command.matches(self.transport.state(command.entity_id)):
            return True
        if command.key in self.pending:
            return False
        if command.key in self.last_sent and (now - self.last_sent[command.key]).total_seconds() < interval:
            return False
        domain = command.entity_id.split(".", 1)[0]
        if not self.transport.has_service(domain, command.service):
            raise ValueError(f"service_missing:{domain}.{command.service}")
        # Record before awaiting: subsequent state events cannot duplicate the command.
        self.pending[command.key] = Pending(command, now)
        self.last_sent[command.key] = now
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
        # A temperature write can wake some devices. Send nothing when manually
        # off, and never attempt to restore a previous mode, even for frost/solar.
        if state is not None and state.state == "off":
            self.status = "pump_off"
            self.pending.clear()
            return
        if self.fault:
            self.status = "command_fault"
            return
        self.check_pending(now, cfg["ack_timeout"])
        if self.fault:
            self.status = "command_fault"
            return
        if decision.state in ("fault", "paused"):
            self.status = "suspended"
            return
        try:
            # Check every capability before issuing any command.
            if decision.pump_target is None:
                self.status = "suspended"
                return
            pump = pump_temperature_plan(cfg["pump_entity"], state, cfg["pump_mode"], decision.pump_target)
            plans = []
            for room in config["rooms"]:
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
            if not all_ready:
                self.status = "opening_emitters"
                return
            # Re-read mode after awaited head commands; never wake an externally
            # stopped pump or overwrite a switch to cooling/another native mode.
            current = self.transport.state(cfg["pump_entity"])
            if current is not None and current.state == "off":
                self.status = "pump_off"
                return
            pump = pump_temperature_plan(cfg["pump_entity"], current, cfg["pump_mode"], decision.pump_target)
            ready = await self.apply(pump, now, cfg["command_interval"])
            self.status = "running" if ready else "adjusting_setpoint"
        except ControlSuspended:
            self.status = "suspended"
        except Exception as err:  # Service implementations can raise third-party errors.
            self.fault = f"{type(err).__name__}:{err}"
            self.status = "command_fault"
