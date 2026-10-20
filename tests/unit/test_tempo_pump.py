"""Tempo is the sole automatic PAC mode exception, with acknowledged ownership."""

import unittest
from datetime import UTC, datetime, timedelta, timezone

# isort: off
from tests.support import FakeTransport, config
from shm_core.controller import Controller
from shm_core.engine import Engine
from shm_core.models import Snapshot
# isort: on


class TempoPumpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 12, 5, 59, tzinfo=timezone(timedelta(hours=1)))
        self.cfg = config(tempo_enabled=True, tempo_today_entity="sensor.tempo", command_interval=15, ack_timeout=30)
        self.transport = FakeTransport()
        self.controller = Controller(self.transport, self.now)
        self.runtime = {"overrides": {}}

    async def tick(self, hour, minute=0, *, today="red", armed=True, protection=False):
        now = self.now.replace(hour=hour, minute=minute)
        decision = Engine().evaluate(
            self.cfg, Snapshot(now, {"living": 18}, today=today, protection=protection), self.runtime
        )
        await self.controller.tick(self.cfg, decision, now, armed)
        return decision

    def modes(self):
        return [c.value for c in self.transport.sent if c.entity_id == "climate.pump" and c.service == "set_hvac_mode"]

    async def test_6_stop_once_then_22_restore_once_then_temperature_only(self):
        await self.tick(5, 59)
        self.assertEqual(self.modes(), [])
        decision = await self.tick(6)
        self.assertEqual(decision.pump_tempo_until, "2026-01-12T21:00:00+00:00")
        self.assertEqual(self.modes(), ["off"])
        self.assertTrue(self.controller.owns_tempo_stop("climate.pump"))
        await self.tick(21, 59)
        self.assertEqual(self.modes(), ["off"])
        await self.tick(22)
        self.assertEqual(self.modes(), ["off", "heat"])
        await self.tick(22, 1)
        await self.tick(23)
        self.assertEqual(self.modes(), ["off", "heat"])
        self.assertEqual(self.transport.state("climate.pump").state, "heat")

    async def test_already_manually_off_never_auto_restarts_at_22(self):
        self.transport.entities["climate.pump"].state = "off"
        await self.tick(6)
        await self.tick(22)
        self.assertEqual(self.transport.sent, [])
        self.assertEqual(self.controller.tempo_state, {})

    async def test_timed_bypass_resumes_then_stops_at_expiration(self):
        await self.tick(6)
        self.runtime["overrides"]["tempo_bypass"] = {
            "value": True,
            "until": self.now.replace(hour=13, minute=0).isoformat(),
        }
        await self.tick(12)
        self.assertEqual(self.modes(), ["off", "heat"])
        await self.tick(12, 1)
        await self.tick(13)
        self.assertEqual(self.modes(), ["off", "heat", "off"])
        await self.tick(22)
        self.assertEqual(self.modes(), ["off", "heat", "off", "heat"])

    async def test_observation_pause_and_fault_send_no_modes(self):
        await self.tick(6, armed=False)
        self.runtime["automation_enabled"] = False
        await self.tick(7)
        self.runtime["automation_enabled"] = True
        await self.tick(8, protection=True)
        self.assertEqual(self.modes(), [])

    async def test_unknown_blue_and_white_do_not_authorize_stop(self):
        for color in ("unknown", "blue", "white"):
            await self.tick(12, today=color)
        self.assertEqual(self.modes(), [])

    async def test_restart_keeps_confirmed_ownership_but_stays_disarmed(self):
        await self.tick(6)
        restored = Controller(self.transport, self.now.replace(hour=20))
        restored.tempo_state = dict(self.controller.tempo_state)
        self.controller = restored
        await self.tick(22, armed=False)
        self.assertEqual(self.modes(), ["off"])
        await self.tick(22, 1)
        self.assertEqual(self.modes(), ["off", "heat"])

    async def test_unconfirmed_persisted_intent_does_not_authorize_restart(self):
        self.transport.entities["climate.pump"].state = "off"
        self.controller.tempo_state = {
            "entity_id": "climate.pump",
            "mode": "heat",
            "confirmed": False,
            "until": self.now.replace(hour=22).astimezone(UTC).isoformat(),
        }
        await self.tick(22)
        self.assertEqual(self.modes(), [])

    async def test_deferred_off_ack_is_required_before_restore(self):
        self.transport.acknowledge = False
        await self.tick(6)
        self.assertFalse(self.controller.tempo_state["confirmed"])
        self.transport.entities["climate.pump"].state = "off"
        self.transport.acknowledge = True
        await self.tick(6)
        self.assertTrue(self.controller.tempo_state["confirmed"])
        await self.tick(22)
        self.assertEqual(self.modes(), ["off", "heat"])

    async def test_ack_failure_latches_without_a_blind_restart(self):
        self.transport.acknowledge = False
        await self.tick(6)
        await self.tick(6, 1)
        await self.tick(22)
        self.assertEqual(self.modes(), ["off"])
        self.assertIn("command_not_applied", self.controller.fault)
