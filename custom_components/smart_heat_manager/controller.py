"""Serial physical orchestration, acknowledgements and hydraulic sequencing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .adapters import Command, Transport, actuator_plan, pump_plan
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
        self.off_since = now
        self.demand_since: datetime | None = None
        self.held_open: dict[str, float] = {}

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
            if not on:
                self.off_since = now
            self.observed_on = on
        if not armed:
            self.status = "observation"
            self.demand_since = None
            self.pending.clear()
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
            pump = pump_plan(cfg["pump_entity"], state, cfg["pump_mode"], decision.pump_requested)
            plans: dict[str, list[Command]] = {}
            for room in config["rooms"]:
                opening = decision.rooms[room["id"]].opening
                for entity in room["actuators"]:
                    plans[entity] = actuator_plan(
                        entity,
                        self.transport.state(entity),
                        room,
                        opening,
                        valve_position_feature=self.valve_position_feature,
                    )
            if decision.pump_requested:
                if self.demand_since is None:
                    self.demand_since = now
            else:
                self.demand_since = None
            requested = decision.pump_requested
            elapsed = (now - self.transition).total_seconds()
            if on and not requested and elapsed < cfg["min_on"]:
                requested = True
                self.status = "minimum_on"
            elif (
                not on
                and requested
                and (
                    elapsed < cfg["min_off"]
                    or self.demand_since is None
                    or (now - self.demand_since).total_seconds() < cfg["demand_delay"]
                )
            ):
                self.status = "minimum_off"
                return
            else:
                self.status = (
                    "running" if on and requested else "starting" if requested else "stopping" if on else "idle"
                )
            # Preserve the last openings during stop sequencing and circulation.
            draining = not on and (now - self.off_since).total_seconds() < cfg["drain_delay"]
            holding = (on and not decision.pump_requested) or draining
            all_ready = True
            for room in config["rooms"]:
                opening = decision.rooms[room["id"]].opening
                for entity in room["actuators"]:
                    if holding:
                        opening_for_entity = max(opening, self.held_open.get(entity, 0))
                    else:
                        opening_for_entity = opening
                    # On rearm while PAC already enabled, unknown positions stay untouched
                    # unless they need opening. Hydraulic bypass is independently required.
                    if holding and entity not in self.held_open and opening_for_entity == 0:
                        continue
                    commands = actuator_plan(
                        entity,
                        self.transport.state(entity),
                        room,
                        opening_for_entity,
                        valve_position_feature=self.valve_position_feature,
                    )
                    for command in commands:
                        ready = await self.apply(command, now, cfg["command_interval"])
                        all_ready = all_ready and ready
                        if not ready:
                            break
                    if opening_for_entity > 0:
                        self.held_open[entity] = opening_for_entity
                    elif not holding:
                        self.held_open.pop(entity, None)
            if requested and not on and not all_ready:
                self.status = "opening_emitters"
                return
            pump = pump_plan(cfg["pump_entity"], state, cfg["pump_mode"], requested)
            await self.apply(pump, now, cfg["command_interval"])
            if draining and not requested:
                self.status = "draining"
            if not holding and not requested:
                self.held_open.clear()
        except ControlSuspended:
            self.status = "suspended"
        except Exception as err:  # Service implementations can raise third-party errors.
            self.fault = f"{type(err).__name__}:{err}"
            self.status = "command_fault"
