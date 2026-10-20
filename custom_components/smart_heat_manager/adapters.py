"""Capability checked HA service plans, independent of the HA runtime."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Protocol


@dataclass
class EntityState:
    state: str
    attributes: dict[str, Any]

    @property
    def available(self) -> bool:
        return self.state not in ("unknown", "unavailable", "")


@dataclass(frozen=True)
class Command:
    entity_id: str
    service: str
    field: str
    value: str | float
    attribute: str | None
    tolerance: float = 0.1

    @property
    def key(self) -> str:
        return f"{self.entity_id}:{self.field}"

    def matches(self, state: EntityState | None) -> bool:
        if state is None or not state.available:
            return False
        value = state.state if self.attribute is None else state.attributes.get(self.attribute)
        if isinstance(self.value, str):
            return value == self.value
        try:
            return abs(float(value) - self.value) <= self.tolerance
        except (TypeError, ValueError):
            return False


class Transport(Protocol):
    """A future local Modbus transport can implement the same boundary."""

    def state(self, entity_id: str) -> EntityState | None: ...
    def has_service(self, domain: str, service: str) -> bool: ...
    async def send(self, command: Command) -> None: ...


def bounded(value: float, low: float, high: float, step: float) -> float:
    if not all(isfinite(x) for x in (value, low, high, step)) or high <= low or step <= 0:
        raise ValueError("invalid_range")
    return round(min(high, max(low, low + round((value - low) / step) * step)), 3)


def actuator_plan(
    entity_id: str, state: EntityState | None, room: dict, opening: float, *, valve_position_feature: int = 4
) -> list[Command]:
    if state is None or not state.available:
        raise ValueError("actuator_unavailable")
    domain = entity_id.split(".", 1)[0]
    attrs = state.attributes
    if domain == "climate":
        if not int(attrs.get("supported_features", 0)) & 1:
            raise ValueError("target_temperature_not_supported")
        if "heat" not in attrs.get("hvac_modes", []):
            raise ValueError("head_heat_mode_not_supported")
        commands = [Command(entity_id, "set_hvac_mode", "hvac_mode", "heat", None)]
        value = room["valve_hot"] if opening > 0 else room["valve_cold"]
        low, high = attrs.get("min_temp"), attrs.get("max_temp")
        if low is None or high is None:
            raise ValueError("head_temperature_bounds_missing")
        value = bounded(value, float(low), float(high), float(attrs.get("target_temp_step") or 0.5))
        commands.append(Command(entity_id, "set_temperature", "temperature", value, "temperature", 0.26))
        return commands
    if domain == "number":
        # Generic numbers are accepted only as explicit 0–100 % valve openings.
        if (
            attrs.get("unit_of_measurement") != "%"
            or float(attrs.get("min", -1)) != 0
            or float(attrs.get("max", -1)) != 100
        ):
            raise ValueError("number_must_be_percentage_0_100")
        value = bounded(opening, 0, 100, float(attrs.get("step") or 1))
        return [Command(entity_id, "set_value", "value", value, None, 0.51)]
    if domain == "valve":
        if not int(attrs.get("supported_features", 0)) & valve_position_feature:
            raise ValueError("valve_position_not_supported")
        return [Command(entity_id, "set_valve_position", "position", round(opening), "current_position", 1)]
    raise ValueError("unsupported_actuator")


def pump_target_value(state: EntityState | None, target: float) -> float:
    """Validate an ambient setpoint without silently exceeding native limits."""
    if state is None or not state.available:
        raise ValueError("pump_unavailable")
    attrs = state.attributes
    if not int(attrs.get("supported_features", 0)) & 1:
        raise ValueError("pump_temperature_not_supported")
    try:
        low, high = float(attrs["min_temp"]), float(attrs["max_temp"])
        step = float(attrs.get("target_temp_step") or 0.5)
        if not all(isfinite(v) for v in (target, low, high, step)) or not low <= target <= high:
            raise ValueError("pump_temperature_out_of_range")
        value = bounded(target, low, high, step)
        if abs(value - target) > 0.001:
            raise ValueError("pump_temperature_step_invalid")
        return value
    except (KeyError, TypeError) as err:
        raise ValueError("pump_temperature_bounds_missing") from err


def pump_temperature_plan(entity_id: str, state: EntityState | None, mode: str, target: float) -> Command:
    """Never enable, disable, or change a heat pump's native operating mode."""
    value = pump_target_value(state, target)
    if mode not in ("heat", "auto"):
        raise ValueError("pump_mode_not_supported")
    if state.state == "off":
        raise ValueError("pump_manually_off")
    if state.state != mode:
        raise ValueError("pump_external_mode")
    return Command(entity_id, "set_temperature", "temperature", value, "temperature", 0.01)
