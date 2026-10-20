"""Configuration invariants, also used by tests and the simulator."""

from math import isfinite

from .const import PUMP_TARGET_KEYS
from .emitters import room_actuator_entities


def validate_config(config: dict) -> None:
    cfg, rooms = config["settings"], config["rooms"]
    if not rooms:
        raise ValueError("room_required")
    if cfg.get("solar_enabled") and not (
        cfg.get("grid_entity") or cfg.get("production_entity") and cfg.get("house_entity")
    ):
        raise ValueError("solar_sources_required")
    if cfg.get("presence_enabled") and not cfg.get("presence_entity"):
        raise ValueError("presence_required")
    if cfg.get("tempo_enabled") and not cfg.get("tempo_today_entity"):
        raise ValueError("tempo_required")
    if cfg["solar_hold"] > cfg["solar_start"] or cfg["solar_hysteresis"] > cfg["solar_hold"]:
        raise ValueError("solar_thresholds_invalid")
    if cfg["control_enabled"] and not all(
        cfg[key] for key in ("hydraulic_confirmed", "exclusive_confirmed", "capabilities_confirmed")
    ):
        raise ValueError("confirmations_required")
    if cfg["pump_mode"] not in ("heat", "auto"):
        raise ValueError("pump_mode_not_supported")
    if any(not isfinite(cfg[key]) or not 5 <= cfg[key] <= 35 for key in PUMP_TARGET_KEYS):
        raise ValueError("temperature_invalid")
    outputs = [cfg["pump_entity"]]
    for room in rooms:
        for head in room.get("trvzb_heads", []):
            if (
                not head.get("climate_entity", "").startswith("climate.")
                or not head.get("opening_entity", "").startswith("number.")
                or not head.get("closing_entity", "").startswith("number.")
            ):
                raise ValueError("trvzb_entities_required")
            if not head.get("firmware_confirmed"):
                raise ValueError("trvzb_firmware_required")
        if not room_actuator_entities(room) or not room.get("name", "").strip():
            raise ValueError("room_required")
        if any(
            entity.endswith(("_valve_opening_degree", "_valve_closing_degree")) for entity in room.get("actuators", [])
        ):
            raise ValueError("trvzb_pair_required")
        for key in ("present", "absent", "night", "holiday", "manual", "solar", "frost", "valve_hot", "valve_cold"):
            if not isfinite(room[key]) or not 5 <= room[key] <= 35:
                raise ValueError("temperature_invalid")
        if room["valve_cold"] >= room["valve_hot"] or room["frost"] > min(
            room[key] for key in ("present", "absent", "night", "holiday", "manual", "solar")
        ):
            raise ValueError("temperature_invalid")
        if not 0.1 <= room["hysteresis"] <= 3 or not 1 <= room["gain"] <= 100:
            raise ValueError("temperature_invalid")
        outputs.extend(room_actuator_entities(room))
    if len(outputs) != len(set(outputs)):
        raise ValueError("duplicate_actuator")
    if any(room["sensor"] in outputs for room in rooms):
        raise ValueError("sensor_is_actuator")
