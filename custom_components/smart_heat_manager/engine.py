"""Explicit state arbitration. No Home Assistant dependency and no I/O."""

from .const import PUMP_MODE_TARGETS
from .models import Decision, Snapshot, active_override
from .night import night_active
from .presence import Presence
from .regulation import regulate
from .solar import Solar, surplus
from .tempo import color, preheat, pump_stop_required, red_window_end, restricted


class Engine:
    def __init__(self) -> None:
        self.presence = Presence()
        self.solar = Solar()
        self.previous: dict[str, bool] = {}

    def evaluate(self, config: dict, snapshot: Snapshot, runtime: dict) -> Decision:
        cfg, now = config["settings"], snapshot.now
        overrides = runtime.get("overrides", {})
        mode = active_override(overrides, "mode", now) or "auto"
        if mode == "auto":
            mode = (
                self.presence.update(snapshot.presence, now, cfg["presence_delay"])
                if cfg["presence_enabled"]
                else "present"
            )
            # Detected absence and explicit mode overrides remain authoritative.
            if mode == "present" and night_active(cfg, runtime, now):
                mode = "night"
        today, tomorrow = color(snapshot.today), color(snapshot.tomorrow)
        tempo = cfg["tempo_enabled"] and restricted(today, now, cfg["tempo_unknown_blocks"])
        bypass = bool(active_override(overrides, "tempo_bypass", now))
        force = bool(active_override(overrides, "force", now))
        net, budget = surplus(snapshot, cfg)
        solar = self.solar.update(
            budget,
            now,
            runtime.get("solar_enabled", cfg["solar_enabled"])
            and (not tempo or cfg["solar_red_allowed"] or bypass or force),
            cfg,
        )
        anticipatory = (
            cfg["tempo_enabled"] and cfg["preheat_enabled"] and preheat(today, tomorrow, now, cfg["preheat_start"])
        )
        rooms = {}
        for room in config["rooms"]:
            rid = room["id"]
            room_solar = runtime.get("room_solar", {}).get(rid, room["solar_enabled"])
            solar_target = runtime.get("room_solar_target", {}).get(rid, room["solar"])
            target = room[mode]
            if cfg["tempo_enabled"]:
                target += cfg["white_delta"] if today == "white" else cfg["red_delta"] if today == "red" else 0
            if anticipatory:
                target = max(target, min(solar_target, target + cfg["preheat_delta"]))
            if solar and room_solar:
                target = max(target, solar_target)
            manual = active_override(overrides, f"room_{rid}", now)
            if manual is not None:
                target = float(manual)
            if force:
                target = max(target, room["present"])
            enabled = runtime.get("room_enabled", {}).get(rid, room["enabled"])
            result = regulate(room, snapshot.temperatures.get(rid), target, self.previous.get(rid, False), enabled)
            self.previous[rid] = result.demand
            if tempo and not (bypass or force or result.frost or solar and cfg["solar_red_allowed"] and room_solar):
                result.demand, result.opening, result.reason = False, 0, "tempo_blocked"
            rooms[rid] = result
        faults = []
        if not snapshot.pump_available:
            faults.append("pump_unavailable")
        if not snapshot.actuators_available:
            faults.append("actuator_unavailable")
        if any(item.temperature is None for item in rooms.values()):
            faults.append("room_sensor_unavailable")
        if snapshot.protection:
            faults.append("hardware_protection")
        if snapshot.monitoring_fault:
            faults.append("monitor_unavailable")
        if any(t is not None and t > cfg["water_max"] for t in (snapshot.water_in, snapshot.water_out)):
            faults.append("water_temperature_high")
        demand = any(r.demand for r in rooms.values())
        frost = any(r.frost for r in rooms.values())
        solar_demand = solar and any(
            rooms[r["id"]].demand and runtime.get("room_solar", {}).get(r["id"], r["solar_enabled"])
            for r in config["rooms"]
        )
        paused = not runtime.get("automation_enabled", True)
        if faults:
            state, reason = "fault", faults[0]
        elif paused:
            state, reason = "paused", "automation_disabled"
        elif frost:
            state, reason = "frost", "frost_priority"
        elif tempo and not (bypass or force or solar_demand and cfg["solar_red_allowed"]):
            state, reason = "tempo_blocked", "red_peak_hours" if today == "red" else "tempo_unknown"
        elif demand:
            state, reason = ("solar_heating", "solar_surplus") if solar_demand else ("heating", "room_demand")
        else:
            state, reason = "idle", "no_demand"
        tempo_stop = pump_stop_required(cfg, now, today, runtime)
        if tempo_stop:
            for room in rooms.values():
                room.demand, room.opening, room.reason = False, 0, "tempo_blocked"
            demand = False
            if not faults and not paused:
                state, reason = "tempo_blocked", "red_peak_hours"
        pump_target = None
        if not faults and not paused and not tempo_stop:
            # Follow the same effective profile as the rooms, not their demand.
            # No room demand never implies turning off the autonomous heat pump.
            pump_target = cfg[PUMP_MODE_TARGETS[mode]]
            if cfg["tempo_enabled"]:
                pump_target += cfg["white_delta"] if today == "white" else cfg["red_delta"] if today == "red" else 0
            if state == "tempo_blocked":
                pump_target = min(pump_target, cfg["pump_tempo_target"])
            elif state == "solar_heating":
                pump_target = max(pump_target, cfg["pump_solar_target"])
            if anticipatory and state != "tempo_blocked":
                pump_target = max(pump_target, min(cfg["pump_solar_target"], pump_target + cfg["preheat_delta"]))
            if force:
                pump_target = max(pump_target, cfg["pump_normal_target"])
        return Decision(
            state,
            reason,
            mode,
            demand and not faults and not paused,
            rooms,
            net,
            budget,
            solar and not tempo_stop,
            today,
            bool(tempo),
            bypass or force,
            faults,
            pump_target,
            tempo_stop,
            red_window_end(today, now, cfg["tempo_enabled"]),
        )
