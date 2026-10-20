"""Logical radiators: one standard entity or a coordinated SONOFF TRVZB group."""

from dataclasses import dataclass

from .adapters import Command, Transport, actuator_plan


@dataclass(frozen=True)
class Emitter:
    key: str
    entities: tuple[str, ...]
    profile: str = "standard"


def room_emitters(room: dict) -> list[Emitter]:
    return [Emitter(entity, (entity,)) for entity in room.get("actuators", [])] + [
        Emitter(
            head["opening_entity"], (head["opening_entity"], head["closing_entity"], head["climate_entity"]), "trvzb"
        )
        for head in room.get("trvzb_heads", [])
    ]


def room_actuator_entities(room: dict) -> list[str]:
    return [entity for emitter in room_emitters(room) for entity in emitter.entities]


def emitter_plan(
    emitter: Emitter, transport: Transport, room: dict, opening: float, *, valve_position_feature: int = 4
) -> list[Command]:
    if emitter.profile == "standard":
        entity = emitter.entities[0]
        if entity.endswith(("_valve_opening_degree", "_valve_closing_degree")):
            raise ValueError("trvzb_pair_required")
        return actuator_plan(
            entity, transport.state(entity), room, opening, valve_position_feature=valve_position_feature
        )
    opening_entity, closing_entity, climate_entity = emitter.entities
    head = next(h for h in room.get("trvzb_heads", []) if h["opening_entity"] == opening_entity)
    if not head.get("firmware_confirmed"):
        raise ValueError("trvzb_firmware_required")
    climate = transport.state(climate_entity)
    if climate is None or not climate.available:
        raise ValueError("actuator_unavailable")
    if "heat" not in climate.attributes.get("hvac_modes", []):
        raise ValueError("head_heat_mode_not_supported")
    if climate.state not in ("off", "heat", "auto"):
        raise ValueError("head_external_mode")
    # The two values define the two native endpoints, not two independent valves.
    # Making them complementary requests the same opening whether the native
    # thermostat calls for open or closed. Readback confirms settings, not motion.
    opened = actuator_plan(opening_entity, transport.state(opening_entity), room, opening)[0]
    closed = actuator_plan(closing_entity, transport.state(closing_entity), room, 100 - float(opened.value))[0]
    if abs(float(opened.value) + float(closed.value) - 100) > 0.01:
        raise ValueError("trvzb_steps_incompatible")
    return [opened, closed, Command(climate_entity, "set_hvac_mode", "hvac_mode", "heat", None)]
