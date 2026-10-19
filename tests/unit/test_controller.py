import asyncio
import unittest
from datetime import UTC, datetime, timedelta

# isort: off
from tests.support import FakeTransport, config
from shm_core.adapters import EntityState, actuator_plan, pump_plan
from shm_core.controller import Controller
from shm_core.engine import Engine
from shm_core.models import Snapshot
# isort: on


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        self.cfg = config(min_on=300, min_off=300, demand_delay=0, drain_delay=60, command_interval=15, ack_timeout=30)
        self.transport = FakeTransport()
        self.controller = Controller(self.transport, self.now)
        self.engine = Engine()

    def decision(self, heat=True, **extra):
        snap = Snapshot(self.now, {"living": 18 if heat else 23}, **extra)
        return self.engine.evaluate(self.cfg, snap, {})

    async def tick(self, sec, heat=True, armed=True, decision=None):
        await self.controller.tick(self.cfg, decision or self.decision(heat), self.now + timedelta(seconds=sec), armed)

    async def test_observation_sends_nothing(self):
        await self.tick(1000, armed=False)
        self.assertEqual(self.transport.sent, [])

    async def test_restart_minimum_off_then_open_before_pump(self):
        await self.tick(0)
        await self.tick(299)
        self.assertEqual(self.transport.sent, [])
        await self.tick(300)
        self.assertEqual([c.entity_id for c in self.transport.sent], ["number.valve", "climate.pump"])
        self.assertEqual(self.transport.state("climate.pump").state, "heat")

    async def test_no_repeated_commands(self):
        await self.tick(0)
        await self.tick(300)
        total = len(self.transport.sent)
        for sec in (315, 330, 345):
            await self.tick(sec)
        self.assertEqual(len(self.transport.sent), total)

    async def test_minimum_on_and_delayed_valve_close(self):
        await self.tick(0)
        await self.tick(300)
        await self.tick(315)
        await self.tick(400, heat=False)
        self.assertEqual(self.controller.status, "minimum_on")
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        self.assertNotEqual(self.transport.state("number.valve").state, "0.0")
        await self.tick(615, heat=False)
        self.assertEqual(self.transport.state("climate.pump").state, "off")
        await self.tick(630, heat=False)
        self.assertEqual(self.controller.status, "draining")
        await self.tick(691, heat=False)
        self.assertEqual(float(self.transport.state("number.valve").state), 0)

    async def test_refused_command_latches_and_never_starts_pump(self):
        self.transport.acknowledge = False
        await self.tick(0)
        await self.tick(300)
        await self.tick(310)
        self.assertEqual(len(self.transport.sent), 1)
        await self.tick(331)
        self.assertEqual(self.controller.status, "command_fault")
        self.assertIn("command_not_applied", self.controller.fault)
        await self.tick(400)
        self.assertEqual(len(self.transport.sent), 1)

    async def test_cloud_error_latches_without_retry(self):
        self.transport.failure = True
        await self.tick(0)
        await self.tick(300)
        self.assertEqual(self.controller.status, "command_fault")
        await self.tick(600)
        self.assertEqual(len(self.transport.sent), 1)

    async def test_stuck_service_times_out_without_starting_pump(self):
        self.cfg["settings"]["ack_timeout"] = 0.01

        async def blocked(_command):
            await asyncio.Event().wait()

        self.transport.send = blocked
        await self.tick(0)
        await self.tick(300)
        self.assertEqual(self.controller.status, "command_fault")
        self.assertIn("TimeoutError", self.controller.fault)
        self.assertEqual(self.transport.state("climate.pump").state, "off")

    async def test_disarm_during_emitter_command_prevents_pump_start(self):
        permitted = True
        original_send = self.transport.send

        async def revoke(command):
            nonlocal permitted
            await original_send(command)
            permitted = False

        self.controller.permit = lambda: permitted
        self.transport.send = revoke
        await self.tick(0)
        await self.tick(300)
        self.assertEqual(self.controller.status, "suspended")
        self.assertEqual(self.transport.state("climate.pump").state, "off")
        self.assertIsNone(self.controller.fault)

    async def test_fault_preserves_positions(self):
        await self.tick(0)
        await self.tick(300)
        count = len(self.transport.sent)
        await self.tick(315, decision=self.decision(pump_available=False))
        self.assertEqual(len(self.transport.sent), count)
        self.assertEqual(self.controller.status, "suspended")

    async def test_unsupported_pump_sends_nothing(self):
        self.transport.entities["climate.pump"].attributes["hvac_modes"] = ["off"]
        await self.tick(0)
        self.assertEqual(self.controller.status, "command_fault")
        self.assertEqual(self.transport.sent, [])

    async def test_unsupported_actuator_checked_before_other_commands(self):
        self.transport.entities["number.valve"].attributes["unit_of_measurement"] = "W"
        await self.tick(0)
        self.assertEqual(self.transport.sent, [])
        self.assertIn("percentage", self.controller.fault)

    async def test_new_controller_never_reuses_armed_state(self):
        await self.tick(0)
        await self.tick(300)
        restarted = Controller(self.transport, self.now + timedelta(seconds=330))
        count = len(self.transport.sent)
        await restarted.tick(self.cfg, self.decision(False), self.now + timedelta(seconds=330), False)
        self.assertEqual(len(self.transport.sent), count)
        self.assertEqual(restarted.status, "observation")

    async def test_pump_start_requires_emitter_ack(self):
        self.transport.acknowledge = False
        await self.tick(0)
        await self.tick(300)
        self.assertEqual(self.controller.status, "opening_emitters")
        self.assertTrue(all(c.entity_id != "climate.pump" for c in self.transport.sent))

    def test_climate_adapter_clamps_and_respects_step(self):
        state = EntityState(
            "heat",
            {
                "hvac_modes": ["heat", "off"],
                "supported_features": 1,
                "min_temp": 5,
                "max_temp": 28,
                "target_temp_step": 0.5,
            },
        )
        commands = actuator_plan("climate.head", state, self.cfg["rooms"][0], 50)
        self.assertEqual(commands[-1].value, 28)

    def test_pump_cooling_mode_never_overwritten(self):
        state = EntityState("cool", {"hvac_modes": ["heat", "off", "cool"]})
        with self.assertRaisesRegex(ValueError, "external_mode"):
            pump_plan("climate.pump", state, "heat", True)


if __name__ == "__main__":
    unittest.main()
