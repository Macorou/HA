"""PAC targets are independent editable values, never a demand to start/stop."""

import unittest
from datetime import UTC, datetime, timedelta

# isort: off
from tests.support import config
from shm_core.const import PUMP_MODE_TARGETS
from shm_core.engine import Engine
from shm_core.models import Snapshot, effective_config
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
        self.assertIsNone(self.evaluate(today="red").pump_target)
        self.assertEqual(self.evaluate(today="unknown").pump_target, 18)
        runtime = {"overrides": {"tempo_bypass": {"value": True, "until": (self.now + timedelta(hours=1)).isoformat()}}}
        snap = Snapshot(self.now, {"living": 18}, today="red")
        self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).pump_target, 21)
        snap.temperatures["living"] = 3
        self.assertIsNone(Engine().evaluate(self.cfg, snap, {}).pump_target)

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

    def profile_runtime(self, mode, until=None):
        return {"overrides": {"mode": {"value": mode, "until": (until or self.now + timedelta(hours=1)).isoformat()}}}

    def test_all_profiles_have_independent_persistent_setting_keys(self):
        snap = Snapshot(self.now, {"living": 25})
        for index, (mode, key) in enumerate(PUMP_MODE_TARGETS.items()):
            with self.subTest(mode=mode):
                self.cfg["settings"][key] = 19 + index
                result = Engine().evaluate(self.cfg, snap, self.profile_runtime(mode))
                self.assertEqual(result.mode, mode)
                self.assertEqual(result.pump_target, 19 + index)
                self.assertFalse(result.pump_requested)

    def test_upgrade_preserves_existing_present_target(self):
        old = config(pump_normal_target=23)
        for key in ("pump_absent_target", "pump_night_target", "pump_holiday_target", "pump_manual_target"):
            old["settings"].pop(key)
        loaded = effective_config(old)
        self.assertEqual(loaded["settings"]["pump_normal_target"], 23)
        self.assertEqual(loaded["settings"]["pump_absent_target"], 17)
        self.assertEqual(loaded["settings"]["pump_holiday_target"], 16)

    def test_auto_presence_switches_pump_profile_after_debounce(self):
        self.cfg["settings"].update(presence_enabled=True, presence_delay=30)
        engine = Engine()
        snap = Snapshot(self.now, {"living": 25}, presence="on")
        self.assertEqual(engine.evaluate(self.cfg, snap, {}).pump_target, 21)
        snap.presence = "off"
        engine.evaluate(self.cfg, snap, {})
        snap.now += timedelta(seconds=31)
        result = engine.evaluate(self.cfg, snap, {})
        self.assertEqual(result.mode, "absent")
        self.assertEqual(result.pump_target, 17)
        snap.presence = "on"
        engine.evaluate(self.cfg, snap, {})
        snap.now += timedelta(seconds=31)
        self.assertEqual(engine.evaluate(self.cfg, snap, {}).pump_target, 21)

    def test_profile_override_expires_without_turning_off_pump(self):
        snap = Snapshot(self.now, {"living": 25})
        runtime = self.profile_runtime("absent", self.now)
        self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).pump_target, 21)

    def test_confirmed_red_stops_even_with_a_low_away_target(self):
        self.cfg["settings"].update(tempo_enabled=True, tempo_today_entity="sensor.tempo", pump_absent_target=16)
        snap = Snapshot(self.now, {"living": 25}, today="red")
        result = Engine().evaluate(self.cfg, snap, self.profile_runtime("absent"))
        self.assertIsNone(result.pump_target)
        self.assertTrue(result.pump_tempo_stop)

    def test_profile_color_offset_and_force_follow_room_rules(self):
        self.cfg["settings"].update(tempo_enabled=True, tempo_today_entity="sensor.tempo", white_delta=-1)
        snap = Snapshot(self.now, {"living": 25}, today="white")
        runtime = self.profile_runtime("absent")
        self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).pump_target, 16)
        runtime["overrides"]["force"] = {"value": True, "until": (self.now + timedelta(hours=1)).isoformat()}
        self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).pump_target, 21)

    def manual_runtime(self, target=23, entity="climate.pump"):
        return {
            "overrides": {
                "pump_target": {
                    "value": target,
                    "entity_id": entity,
                    "until": (self.now + timedelta(hours=1)).isoformat(),
                }
            }
        }

    def test_direct_manual_pump_target_never_changes_room_profile_or_target(self):
        snap = Snapshot(self.now, {"living": 19})
        result = Engine().evaluate(self.cfg, snap, self.manual_runtime())
        self.assertEqual(result.mode, "present")
        self.assertEqual(result.pump_profile, "manual")
        self.assertEqual(result.pump_target, 23)
        self.assertEqual(result.rooms["living"].target, 20)

    def test_manual_pump_is_scoped_to_entity_and_fixed_expiry(self):
        snap = Snapshot(self.now, {"living": 19})
        runtime = self.manual_runtime(entity="climate.old_pump")
        self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).pump_target, 21)
        runtime = self.manual_runtime()
        snap.now += timedelta(hours=1)
        self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).pump_target, 21)

    def test_manual_pump_does_not_bypass_red_stop_unknown_cap_pause_or_protection(self):
        self.cfg["settings"].update(tempo_enabled=True, tempo_today_entity="sensor.tempo")
        runtime = self.manual_runtime()
        red = Engine().evaluate(self.cfg, Snapshot(self.now, {"living": 19}, today="red"), runtime)
        self.assertIsNone(red.pump_target)
        self.assertTrue(red.pump_tempo_stop)
        unknown = Engine().evaluate(self.cfg, Snapshot(self.now, {"living": 19}), runtime)
        self.assertEqual(unknown.pump_target, 18)
        protected = Engine().evaluate(self.cfg, Snapshot(self.now, {"living": 19}, protection=True), runtime)
        self.assertIsNone(protected.pump_target)
        runtime["automation_enabled"] = False
        self.assertIsNone(Engine().evaluate(self.cfg, Snapshot(self.now, {"living": 19}), runtime).pump_target)

    def test_invalid_manual_pump_value_suspends_instead_of_raising(self):
        for target in ("bad", True, float("nan"), float("inf"), {}):
            result = Engine().evaluate(self.cfg, Snapshot(self.now, {"living": 19}), self.manual_runtime(target))
            self.assertIn("invalid_pump_override", result.faults)
            self.assertIsNone(result.pump_target)


if __name__ == "__main__":
    unittest.main()
