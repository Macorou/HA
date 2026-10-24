"""Pure data contracts shared by HA, the simulator and the regulation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .const import DEFAULTS, ROOM_DEFAULTS


@dataclass
class Reading:
    value: float | None
    valid: bool = True


@dataclass
class Snapshot:
    now: datetime
    temperatures: dict[str, float | None]
    pump_available: bool = True
    pump_on: bool = False
    actuators_available: bool = True
    presence: str | None = None
    today: str | None = None
    tomorrow: str | None = None
    grid: float | None = None
    production: float | None = None
    house: float | None = None
    pump_power: float | None = None
    protection: bool = False
    water_in: float | None = None
    water_out: float | None = None
    monitoring_fault: bool = False


@dataclass
class RoomDecision:
    temperature: float | None
    target: float
    demand: bool
    opening: float
    reason: str
    frost: bool = False


@dataclass
class Decision:
    state: str
    reason: str
    mode: str
    pump_requested: bool  # Logical room demand only; never an on/off command.
    rooms: dict[str, RoomDecision]
    surplus: float | None
    solar_budget: float | None
    solar_active: bool
    tempo: str
    tempo_blocked: bool
    override_active: bool
    faults: list[str] = field(default_factory=list)
    pump_target: float | None = None
    pump_tempo_stop: bool = False
    pump_tempo_until: str | None = None
    pump_profile: str | None = None


def effective_config(data: dict, options: dict | None = None) -> dict[str, Any]:
    source = options if options and "settings" in options else data
    return {
        "settings": DEFAULTS | source.get("settings", {}),
        "rooms": [ROOM_DEFAULTS | room for room in source.get("rooms", [])],
    }


def active_override(overrides: dict, key: str, now: datetime) -> Any:
    item = overrides.get(key)
    if not isinstance(item, dict):
        return None
    try:
        until = datetime.fromisoformat(item["until"])
        if until.tzinfo and until > now:
            return item["value"]
    except (ValueError, KeyError, TypeError):
        pass
    return None
