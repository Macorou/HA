import asyncio
import unittest
from datetime import UTC, datetime, timedelta

# isort: off
from tests.support import FakeTransport, config
from shm_core.adapters import EntityState, actuator_plan, pump_temperature_plan
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

    async def test_emitters_confirmed_before_temperature_only_adjustment(self):
        await self.tick(0)
        self.assertEqual([c.entity_id for c in self.transport.sent], ["number.valve", "climate.pump"])
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        self.assertEqual(self.transport.sent[-1].service, "set_temperature")
        self.assertEqual(self.transport.sent[-1].value, 20)

    async def test_no_repeated_commands(self):
        await self.tick(0)
        await self.tick(300)
        total = len(self.transport.sent)
        for sec in (315, 330, 345):
            await self.tick(sec)
        self.assertEqual(len(self.transport.sent), total)

    async def test_satisfied_rooms_never_stop_or_lower_autonomous_pump(self):
        await self.tick(0)
        await self.tick(300)
        await self.tick(315)
        await self.tick(400, heat=False)
        self.assertEqual(self.controller.status, "running")
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 20)
        self.assertEqual(float(self.transport.state("number.valve").state), 0)
        await self.tick(615, heat=False)
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        await self.tick(630, heat=False)
        self.assertEqual(self.controller.status, "running")
        await self.tick(691, heat=False)
        self.assertEqual(float(self.transport.state("number.valve").state), 0)

    async def test_refused_command_latches_and_never_starts_pump(self):
        self.transport.acknowledge = False
        await self.tick(0)
        await self.tick(300)
        await self.tick(10)
        self.assertEqual(len(self.transport.sent), 1)
        await self.tick(31)
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
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 17)

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
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 17)
        self.assertIsNone(self.controller.fault)

    async def test_fault_preserves_positions(self):
        await self.tick(0)
        await self.tick(300)
        count = len(self.transport.sent)
        await self.tick(315, decision=self.decision(pump_available=False))
        self.assertEqual(len(self.transport.sent), count)
        self.assertEqual(self.controller.status, "suspended")

    async def test_unsupported_pump_sends_nothing(self):
        self.transport.entities["climate.pump"].attributes["supported_features"] = 0
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

    async def test_pump_setpoint_requires_emitter_ack(self):
        self.transport.acknowledge = False
        await self.tick(0)
        await self.tick(10)
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
        state = EntityState("cool", dict(self.transport.state("climate.pump").attributes))
        with self.assertRaisesRegex(ValueError, "external_mode"):
            pump_temperature_plan("climate.pump", state, "heat", 20)

    async def test_manual_pump_off_never_wakes_even_for_frost_or_solar(self):
        self.transport.entities["climate.pump"].state = "off"
        for temp in (3, 18, 25):
            decision = self.engine.evaluate(self.cfg, Snapshot(self.now, {"living": temp}), {})
            await self.tick(500, decision=decision)
            self.assertEqual(self.controller.status, "pump_off")
        self.assertEqual(self.transport.sent, [])

    async def test_manual_stop_during_head_write_prevents_setpoint(self):
        original_send = self.transport.send

        async def stop(command):
            await original_send(command)
            self.transport.entities["climate.pump"].state = "off"

        self.transport.send = stop
        await self.tick(0)
        self.assertEqual(self.controller.status, "pump_off")
        self.assertTrue(all(c.entity_id != "climate.pump" for c in self.transport.sent))

    async def test_confirmed_red_hours_stop_pump_instead_of_reducing_temperature(self):
        self.cfg["settings"].update(tempo_enabled=True, tempo_today_entity="sensor.tempo")
        self.transport.entities["climate.pump"].attributes["temperature"] = 20
        decision = self.engine.evaluate(self.cfg, Snapshot(self.now.replace(hour=12), {"living": 18}, today="red"), {})
        self.assertIsNone(decision.pump_target)
        await self.tick(0, decision=decision)
        pump_commands = [c for c in self.transport.sent if c.entity_id == "climate.pump"]
        self.assertEqual([(c.service, c.value) for c in pump_commands], [("set_hvac_mode", "off")])
        self.assertEqual(self.transport.state("climate.pump").state, "off")

    async def test_no_mode_commands_across_requests_faults_pause_and_idle(self):
        for sec, heat in ((0, True), (30, False), (60, True), (90, False)):
            await self.tick(sec, heat=heat)
        await self.tick(120, decision=self.decision(pump_available=False))
        paused = self.engine.evaluate(self.cfg, Snapshot(self.now, {"living": 18}), {"automation_enabled": False})
        await self.tick(150, decision=paused)
        commands = [c for c in self.transport.sent if c.entity_id == "climate.pump"]
        self.assertTrue(commands)
        self.assertTrue(all(c.service == "set_temperature" and c.field == "temperature" for c in commands))

    def test_pump_target_respects_native_bounds_steps_and_off(self):
        state = self.transport.state("climate.pump")
        for target in (15, 31, float("nan"), 20.5):
            with self.assertRaises(ValueError):
                pump_temperature_plan("climate.pump", state, "heat", target)
        state.state = "off"
        with self.assertRaisesRegex(ValueError, "manually_off"):
            pump_temperature_plan("climate.pump", state, "heat", 20)


if __name__ == "__main__":
    unittest.main()
