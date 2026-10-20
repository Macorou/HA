"""Offline scenario runner; never connects to Home Assistant or hardware."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("shm_sim")
package.__path__ = [str(ROOT / "custom_components" / "smart_heat_manager")]
package.__spec__ = importlib.util.spec_from_loader("shm_sim", loader=None, is_package=True)
sys.modules["shm_sim"] = package

from shm_sim.const import DEFAULTS, ROOM_DEFAULTS  # noqa: E402
from shm_sim.engine import Engine  # noqa: E402
from shm_sim.models import Snapshot  # noqa: E402


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    cfg = {
        "settings": DEFAULTS | {"tempo_enabled": True, "solar_enabled": True, "solar_delay": 60},
        "rooms": [ROOM_DEFAULTS | {"id": "living", "name": "Salon"}],
    }
    now = datetime(2026, 1, 12, 12, tzinfo=UTC)
    engine = Engine()
    runtime = {"overrides": {}}
    scenarios = [
        ("Besoin normal bleu", 0, {"today": "blue", "grid": 0}),
        ("Rouge HP", 15, {"today": "red", "grid": 0}),
        ("Dérogation rouge", 30, {"today": "red", "grid": 0, "override": True}),
        ("Expiration dérogation", 120, {"today": "red", "grid": 0}),
        ("Surplus en qualification", 180, {"today": "blue", "grid": -3500}),
        ("Solaire qualifié", 241, {"today": "blue", "grid": -3500}),
        ("PAC consomme 3 kW", 260, {"today": "blue", "grid": -500, "pump_on": True, "pump_power": 3000}),
        ("Perte sonde", 280, {"today": "blue", "temperatures": {"living": None}}),
        ("Perte LG", 300, {"today": "blue", "pump_available": False}),
    ]
    records = []
    for label, sec, values in scenarios:
        when = now + timedelta(seconds=sec)
        if values.pop("override", False):
            runtime["overrides"]["tempo_bypass"] = {"value": True, "until": (when + timedelta(seconds=60)).isoformat()}
        snap = Snapshot(**({"now": when, "temperatures": {"living": 19}} | values))
        result = engine.evaluate(cfg, snap, runtime)
        records.append(
            {
                "scenario": label,
                "state": result.state,
                "reason": result.reason,
                "target": result.rooms["living"].target,
                "surplus": result.surplus,
                "budget": result.solar_budget,
                "requested": result.pump_requested,
                "pump_setpoint": result.pump_target,
            }
        )
    if args.json:
        print(json.dumps(records, indent=2, ensure_ascii=False))
    else:
        for row in records:
            print(
                f"{row['scenario']:28} {row['state']:16} cible pièce={row['target']:4.1f} °C  cible PAC={row['pump_setpoint']}"
            )


if __name__ == "__main__":
    run()
