"""Night planning: wall-clock boundaries, profile priorities and upgrades."""

import unittest
from datetime import UTC, datetime, timedelta, timezone

# isort: off
from tests.support import config
from shm_core.engine import Engine
from shm_core.models import Snapshot, effective_config
from shm_core.night import clock_time, night_active
from shm_core.validation import validate_config
# isort: on


class NightTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config(night_schedule_enabled=True, pump_normal_target=19, pump_night_target=17)

    def now(self, hour, minute=0):
        return datetime(2026, 10, 21, hour, minute, tzinfo=timezone(timedelta(hours=2)))

    def test_cross_midnight_and_exact_boundaries(self):
        for hour, minute, expected in [
            (21, 59, False),
            (22, 0, True),
            (23, 59, True),
            (0, 0, True),
            (6, 59, True),
            (7, 0, False),
            (12, 0, False),
        ]:
            with self.subTest(hour=hour, minute=minute):
                self.assertEqual(night_active(self.cfg["settings"], {}, self.now(hour, minute)), expected)

    def test_daytime_and_empty_window(self):
        self.cfg["settings"].update(night_start="01:00:00", night_end="05:00:00")
        for hour, expected in [(0, False), (1, True), (4, True), (5, False), (23, False)]:
            self.assertEqual(night_active(self.cfg["settings"], {}, self.now(hour)), expected)
        self.cfg["settings"]["night_end"] = "01:00:00"
        self.assertFalse(night_active(self.cfg["settings"], {}, self.now(1)))

    def test_local_clock_not_utc_and_both_repeated_hours(self):
        local = self.now(22)
        self.assertTrue(night_active(self.cfg["settings"], {}, local))
        self.assertFalse(night_active(self.cfg["settings"], {}, local.astimezone(UTC)))
        for offset in (1, 2):
            repeated = datetime(2026, 10, 25, 2, 30, tzinfo=timezone(timedelta(hours=offset)))
            self.assertTrue(night_active(self.cfg["settings"], {}, repeated))

    def test_default_disabled_and_persistent_toggle_priority(self):
        old = config()
        for key in ("night_start", "night_end", "night_schedule_enabled"):
            old["settings"].pop(key)
        upgraded = effective_config(old)
        self.assertFalse(night_active(upgraded["settings"], {}, self.now(23)))
        self.assertTrue(night_active(upgraded["settings"], {"night_schedule_enabled": True}, self.now(23)))
        self.assertFalse(night_active(self.cfg["settings"], {"night_schedule_enabled": False}, self.now(23)))

    def test_night_controls_pac_and_rooms_then_returns_to_day(self):
        snap = Snapshot(self.now(23), {"living": 25})
        result = Engine().evaluate(self.cfg, snap, {})
        self.assertEqual((result.mode, result.pump_target, result.rooms["living"].target), ("night", 17, 18))
        self.assertFalse(result.pump_requested)
        snap.now = self.now(7)
        result = Engine().evaluate(self.cfg, snap, {})
        self.assertEqual((result.mode, result.pump_target), ("present", 19))

    def test_explicit_modes_take_priority_and_expiry_returns_to_night(self):
        snap = Snapshot(self.now(23), {"living": 25})
        for mode in ("present", "absent", "holiday", "manual", "night"):
            runtime = {"overrides": {"mode": {"value": mode, "until": (snap.now + timedelta(hours=1)).isoformat()}}}
            self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).mode, mode)
            runtime["overrides"]["mode"]["until"] = snap.now.isoformat()
            self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).mode, "night")

    def test_detected_absence_has_priority(self):
        self.cfg["settings"].update(presence_enabled=True, presence_entity="binary_sensor.presence", presence_delay=0)
        snap = Snapshot(self.now(23), {"living": 25}, presence="off")
        engine = Engine()
        engine.evaluate(self.cfg, snap, {})
        snap.now += timedelta(seconds=1)
        self.assertEqual(engine.evaluate(self.cfg, snap, {}).mode, "absent")

    def test_room_temperature_override_and_tempo_safety_unchanged(self):
        snap = Snapshot(self.now(23), {"living": 25})
        runtime = {"overrides": {"room_living": {"value": 21, "until": (snap.now + timedelta(hours=1)).isoformat()}}}
        self.assertEqual(Engine().evaluate(self.cfg, snap, runtime).rooms["living"].target, 21)
        self.cfg["settings"].update(
            night_start="00:00:00", night_end="12:00:00", tempo_enabled=True, tempo_today_entity="sensor.tempo"
        )
        snap.now, snap.today = self.now(6), "red"
        result = Engine().evaluate(self.cfg, snap, {})
        self.assertEqual(result.mode, "night")
        self.assertTrue(result.pump_tempo_stop)
        self.assertIsNone(result.pump_target)

    def test_bad_times_rejected(self):
        for invalid in (None, 22, "", "24:00:00", "12:60:00", "22:00:00+02:00", "22:00:00.123"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                clock_time(invalid)
        self.cfg["settings"]["night_start"] = "invalid"
        with self.assertRaises(ValueError):
            validate_config(self.cfg)


if __name__ == "__main__":
    unittest.main()
