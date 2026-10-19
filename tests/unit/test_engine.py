import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone

# isort: off
from tests.support import config
from shm_core.const import ROOM_DEFAULTS
from shm_core.engine import Engine
from shm_core.models import Snapshot, active_override
from shm_core.presence import Presence
from shm_core.regulation import regulate
from shm_core.solar import Solar, surplus
from shm_core.validation import validate_config
# isort: on


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 12, 12, tzinfo=UTC)
        self.cfg = config()
        self.engine = Engine()
        self.runtime = {"overrides": {}}

    def snapshot(self, **kwargs):
        return Snapshot(**({"now": self.now, "temperatures": {"living": 19}} | kwargs))

    def decide(self, **kwargs):
        return self.engine.evaluate(self.cfg, self.snapshot(**kwargs), self.runtime)

    def override(self, key, value, minutes=60):
        self.runtime["overrides"][key] = {"value": value, "until": (self.now + timedelta(minutes=minutes)).isoformat()}

    def test_room_uses_external_sensor(self):
        result = self.decide()
        self.assertTrue(result.pump_requested)
        self.assertEqual(result.rooms["living"].temperature, 19)

    def test_tempo_red_hours_and_blue_white(self):
        self.cfg["settings"]["tempo_enabled"] = True
        for hour, blocked in [(5, False), (6, True), (21, True), (22, False)]:
            result = self.decide(now=self.now.replace(hour=hour), today="Rouge")
            self.assertEqual(result.pump_requested, not blocked, hour)
        for value in ("Bleu", "Blanc", "TEMPO_BLUE"):
            self.assertTrue(self.decide(today=value).pump_requested)

    def test_manual_tempo_override_expires_at_exact_deadline(self):
        self.cfg["settings"]["tempo_enabled"] = True
        self.override("tempo_bypass", True)
        self.assertTrue(self.decide(today="red").pump_requested)
        self.assertFalse(self.decide(today="red", now=self.now + timedelta(hours=1)).pump_requested)

    def test_force_overrides_economics_but_not_fault(self):
        self.cfg["settings"]["tempo_enabled"] = True
        self.override("force", True)
        self.assertTrue(self.decide(today="red").pump_requested)
        self.assertFalse(self.decide(today="red", protection=True).pump_requested)

    def test_frost_has_priority_over_tempo_and_disabled_room(self):
        self.cfg["settings"]["tempo_enabled"] = True
        self.cfg["rooms"][0]["enabled"] = False
        decision = self.decide(today="red", temperatures={"living": 5})
        self.assertEqual(decision.state, "frost")
        self.assertTrue(decision.pump_requested)

    def test_lost_sensor_faults_whole_installation(self):
        decision = self.decide(temperatures={"living": None})
        self.assertEqual(decision.state, "fault")
        self.assertFalse(decision.pump_requested)

    def test_lg_unavailable(self):
        self.assertIn("pump_unavailable", self.decide(pump_available=False).faults)

    def test_water_over_limit_and_monitoring_loss(self):
        self.assertEqual(self.decide(water_out=70).state, "fault")
        self.assertEqual(self.decide(monitoring_fault=True).state, "fault")

    def test_multiple_rooms_independent(self):
        self.cfg["rooms"].append(
            ROOM_DEFAULTS
            | {"id": "bedroom", "name": "Chambre", "sensor": "sensor.bedroom", "actuators": ["climate.head"]}
        )
        result = self.decide(temperatures={"living": 19, "bedroom": 22})
        self.assertTrue(result.rooms["living"].demand)
        self.assertFalse(result.rooms["bedroom"].demand)
        result = self.decide(temperatures={"living": 19, "bedroom": 18})
        self.assertEqual(sum(r.demand for r in result.rooms.values()), 2)

    def test_hysteresis_and_proportional_valve(self):
        room = self.cfg["rooms"][0]
        cold = regulate(room, 18, 20, False)
        close = regulate(room, 20.1, 20, True)
        self.assertGreater(cold.opening, close.opening)
        self.assertTrue(close.demand)
        self.assertFalse(regulate(room, 20.4, 20, True).demand)
        self.assertFalse(regulate(room, 19.9, 20, False).demand)

    def test_occupancy_unknown_preserves_last_mode(self):
        presence = Presence()
        self.assertEqual(presence.update("not_home", self.now, 60), "present")
        self.assertEqual(presence.update("not_home", self.now + timedelta(seconds=60), 60), "absent")
        self.assertEqual(presence.update(None, self.now + timedelta(hours=1), 60), "absent")

    def test_presence_interruption_restarts_debounce(self):
        p = Presence()
        p.update("off", self.now, 60)
        p.update(None, self.now + timedelta(seconds=30), 60)
        self.assertEqual(p.update("off", self.now + timedelta(seconds=90), 60), "present")

    def test_local_timezone_boundary(self):
        self.cfg["settings"]["tempo_enabled"] = True
        paris = self.now.replace(hour=6, tzinfo=timezone(timedelta(hours=1)))
        self.assertEqual(self.decide(now=paris, today="red").state, "tempo_blocked")

    def test_preheat_uses_today_after_midnight(self):
        self.cfg["settings"].update(tempo_enabled=True, preheat_enabled=True)
        early = self.decide(now=self.now.replace(hour=4), today="red", tomorrow="blue")
        self.assertEqual(early.rooms["living"].target, 21)
        normal = self.decide(now=self.now.replace(hour=4), today="blue", tomorrow="red")
        self.assertEqual(normal.rooms["living"].target, 20)

    def test_preheat_never_reduces_normal_target(self):
        self.cfg["settings"].update(tempo_enabled=True, preheat_enabled=True)
        self.cfg["rooms"][0]["present"] = 24
        result = self.decide(now=self.now.replace(hour=4), today="red")
        self.assertEqual(result.rooms["living"].target, 24)

    def test_unknown_tempo_blocks_unless_overridden(self):
        self.cfg["settings"]["tempo_enabled"] = True
        self.assertEqual(self.decide().state, "tempo_blocked")

    def test_solar_does_not_bypass_red_for_opted_out_room(self):
        self.cfg["settings"].update(tempo_enabled=True, solar_enabled=True, solar_delay=0, solar_red_allowed=True)
        self.cfg["rooms"][0]["solar_enabled"] = False
        self.assertFalse(self.decide(grid=-4000, today="red").pump_requested)
        self.cfg["rooms"][0]["solar_enabled"] = True
        self.assertTrue(self.decide(grid=-4000, today="red").pump_requested)

    def test_solar_ceiling_and_manual_override_priority(self):
        self.cfg["settings"].update(solar_enabled=True, solar_delay=0)
        self.assertEqual(self.decide(grid=-4000).rooms["living"].target, 22)
        self.override("room_living", 19)
        self.assertEqual(self.decide(grid=-4000).rooms["living"].target, 19)

    def test_pause_never_commands_even_frost(self):
        self.runtime["automation_enabled"] = False
        self.assertFalse(self.decide(temperatures={"living": 3}).pump_requested)

    def test_bad_override_ignored_and_restart_expiry(self):
        runtime = {"x": {"value": True, "until": "invalid"}}
        self.assertIsNone(active_override(runtime, "x", self.now))
        self.override("force", True, minutes=-1)
        restarted = Engine().evaluate(self.cfg, self.snapshot(), deepcopy(self.runtime))
        self.assertFalse(restarted.override_active)

    def test_duplicate_outputs_rejected(self):
        self.cfg["rooms"].append(deepcopy(self.cfg["rooms"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate_actuator"):
            validate_config(self.cfg)

    def test_no_solar_production_only(self):
        self.cfg["settings"].update(solar_enabled=True, production_entity="sensor.pv")
        with self.assertRaisesRegex(ValueError, "solar_sources_required"):
            validate_config(self.cfg)


class SolarTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 12, tzinfo=UTC)
        self.cfg = config()["settings"]
        self.solar = Solar()

    def test_grid_signs(self):
        snapshot = Snapshot(self.now, {}, grid=-3500)
        self.assertEqual(surplus(snapshot, self.cfg), (3500, 3300))
        snapshot.grid = 3500
        self.assertEqual(surplus(snapshot, self.cfg | {"grid_export_positive": True}), (3500, 3300))

    def test_house_pump_not_counted_twice(self):
        snapshot = Snapshot(self.now, {}, production=5000, house=1500, pump_power=1000)
        self.assertEqual(surplus(snapshot, self.cfg)[0], 3500)
        self.assertEqual(surplus(snapshot, self.cfg | {"house_includes_pump": False})[0], 2500)

    def test_surplus_reduction_after_pump_start(self):
        before = Snapshot(self.now, {}, grid=-3500)
        after = Snapshot(self.now, {}, grid=-500, pump_on=True, pump_power=3000)
        self.assertEqual(surplus(before, self.cfg)[1], surplus(after, self.cfg)[1])

    def test_grid_import_not_truncated_before_compensation(self):
        snapshot = Snapshot(self.now, {}, grid=1000, pump_on=True, pump_power=3000)
        self.assertEqual(surplus(snapshot, self.cfg), (-1000, 1800))

    def test_unstable_solar_debounce_and_hold(self):
        cfg = self.cfg | {"solar_delay": 60, "solar_min_on": 180, "solar_stop_delay": 60}

        def update(budget, sec):
            return self.solar.update(budget, self.now + timedelta(seconds=sec), True, cfg)

        self.assertFalse(update(4000, 0))
        self.assertFalse(update(0, 30))
        self.assertFalse(update(4000, 60))
        self.assertTrue(update(4000, 120))
        self.assertTrue(update(0, 150))
        self.assertTrue(update(0, 220))
        self.assertFalse(update(0, 300))

    def test_lost_solar_data_ends_extra_heating(self):
        self.solar.update(4000, self.now, True, self.cfg | {"solar_delay": 0})
        self.assertFalse(self.solar.update(None, self.now, True, self.cfg))


if __name__ == "__main__":
    unittest.main()
