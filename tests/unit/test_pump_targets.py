"""PAC targets are independent editable values, never a demand to start/stop."""

import unittest
from datetime import UTC, datetime, timedelta

# isort: off
from tests.support import config
from shm_core.engine import Engine
from shm_core.models import Snapshot
# isort: on


class PumpTargetTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config(pump_normal_target=21, pump_tempo_target=18, pump_solar_target=24)
        self.now = datetime(2026, 1, 12, 12, tzinfo=UTC)

    def evaluate(self, **values):
        return Engine().evaluate(self.cfg, Snapshot(self.now, {"living": 25}, **values), {})

    def test_normal_setpoint_preserved_without_room_demand(self):
        result = self.evaluate()
        self.assertFalse(result.pump_requested)
        self.assertEqual(result.pump_target, 21)

    def test_reduced_tempo_and_override_return_to_configured_normal(self):
        self.cfg["settings"].update(tempo_enabled=True, tempo_today_entity="sensor.tempo")
        self.assertEqual(self.evaluate(today="red").pump_target, 18)
        self.assertEqual(self.evaluate(today="unknown").pump_target, 18)
        runtime = {"overrides": {"tempo_bypass": {"value": True, "until": (self.now + timedelta(hours=1)).isoformat()}}}
        snap = Snapshot(self.now, {"living": 18}, today="red")
        self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).pump_target, 21)
        snap.temperatures["living"] = 3
        self.assertEqual(Engine().evaluate(self.cfg, snap, {}).pump_target, 21)

    def test_solar_setpoint_requires_qualified_surplus_and_eligible_room(self):
        self.cfg["settings"].update(solar_enabled=True, grid_entity="sensor.grid", solar_delay=0)
        engine = Engine()
        snap = Snapshot(self.now, {"living": 19}, grid=-5000)
        engine.evaluate(self.cfg, snap, {})
        snap.now += timedelta(seconds=1)
        self.assertEqual(engine.evaluate(self.cfg, snap, {}).pump_target, 24)
        self.cfg["rooms"][0]["solar_enabled"] = False
        self.assertEqual(engine.evaluate(self.cfg, snap, {}).pump_target, 21)
        self.cfg["rooms"][0]["solar_enabled"] = True
        snap.grid = None
        self.assertEqual(engine.evaluate(self.cfg, snap, {}).pump_target, 21)

    def test_pause_and_fault_preserve_physical_setpoint(self):
        snap = Snapshot(self.now, {"living": 18})
        self.assertIsNone(Engine().evaluate(self.cfg, snap, {"automation_enabled": False}).pump_target)
        self.assertIsNone(self.evaluate(protection=True).pump_target)
        self.assertIsNone(self.evaluate(pump_available=False).pump_target)


if __name__ == "__main__":
    unittest.main()
