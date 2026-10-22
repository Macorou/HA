"""A stalled room command must not freeze independent native PAC profiles."""

import unittest
from datetime import UTC, datetime, timedelta

# isort: off
from tests.support import FakeTransport, config
from shm_core.adapters import Command
from shm_core.controller import Controller, Pending
from shm_core.control_state import dump_control, restore_control
from shm_core.engine import Engine
from shm_core.models import Snapshot
# isort: on


class EmitterFaultTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 8, 53, tzinfo=UTC)
        self.cfg = config(demand_delay=0, ack_timeout=180, command_interval=60, hydraulic_confirmed=True)
        self.transport = FakeTransport()
        self.transport.entities["climate.pump"].attributes["temperature"] = 20
        self.controller = Controller(self.transport, self.now)
        self.engine = Engine()
        original = self.transport.send

        async def send(command):
            if command.entity_id == "number.valve":
                self.transport.sent.append(command)  # Successful service, no readback.
            else:
                await original(command)

        self.transport.send = send

    async def tick(self, seconds, mode="present", armed=True, **snapshot):
        now = self.now + timedelta(seconds=seconds)
        decision = self.engine.evaluate(
            self.cfg,
            Snapshot(now, {"living": 18}, **snapshot),
            {"overrides": {"mode": {"value": mode, "until": (now + timedelta(hours=1)).isoformat()}}},
        )
        await self.controller.tick(self.cfg, decision, now, armed)

    async def latch(self):
        await self.tick(0)
        await self.tick(181)
        self.assertEqual(self.controller.fault, "command_not_applied:number.valve")
        self.assertEqual(self.controller.status, "emitter_fault")

    async def test_actual_incident_absence_after_valve_timeout_lowers_pump(self):
        await self.latch()
        await self.tick(1981, mode="absent")
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 17)
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        self.assertEqual([c.entity_id for c in self.transport.sent], ["number.valve", "climate.pump"])
        self.assertTrue(self.controller.emitter_fault(self.cfg))

    async def test_pending_valve_does_not_delay_absence(self):
        await self.tick(0)
        await self.tick(10, mode="absent")
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 17)
        self.assertEqual(self.controller.status, "opening_emitters")

    async def test_late_ack_never_clears_fault_or_restarts_emitters(self):
        await self.latch()
        pending = self.controller.pending["number.valve:value"]
        self.transport.entities["number.valve"].state = str(pending.command.value)
        await self.tick(2298, mode="absent")
        await self.tick(2400, mode="present")
        self.assertEqual(self.controller.fault, "command_not_applied:number.valve")
        self.assertEqual(sum(c.entity_id == "number.valve" for c in self.transport.sent), 1)
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 20)

    async def test_legacy_persisted_fault_is_local_after_reload_without_reset(self):
        await self.latch()
        saved = dump_control(self.controller)
        self.controller = Controller(self.transport, self.now)
        restore_control(self.controller, saved, ["climate.pump", "number.valve"])
        await self.tick(2400, mode="night")
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 18)
        self.assertEqual(self.controller.fault, saved["fault"])
        self.assertEqual(sum(c.entity_id == "number.valve" for c in self.transport.sent), 1)

    async def test_pump_timeout_supersedes_valve_fault_and_blocks_further_commands(self):
        await self.latch()
        self.transport.acknowledge = False
        await self.tick(200, mode="absent")
        await self.tick(381, mode="absent")
        self.assertEqual(self.controller.fault, "command_not_applied:climate.pump")
        self.assertEqual(self.controller.status, "command_fault")
        count = len(self.transport.sent)
        await self.tick(500, mode="night")
        self.assertEqual(len(self.transport.sent), count)

    async def test_unknown_storage_and_transport_faults_never_get_a_bypass(self):
        for fault in ("invalid_saved_control_state", "TimeoutError:", "command_not_applied:number.removed"):
            with self.subTest(fault=fault):
                self.controller.fault = fault
                await self.tick(500, mode="absent")
                self.assertEqual(self.controller.status, "command_fault")
                self.assertEqual(self.transport.sent, [])

    async def test_protection_missing_sensor_and_pause_still_suspend_everything(self):
        await self.latch()
        count = len(self.transport.sent)
        for snapshot in ({"protection": True}, {"pump_available": False}, {"actuators_available": False}):
            await self.tick(500, mode="absent", **snapshot)
            self.assertEqual(self.controller.status, "suspended")
        decision = self.engine.evaluate(self.cfg, Snapshot(self.now, {"living": 18}), {"automation_enabled": False})
        await self.controller.tick(self.cfg, decision, self.now, True)
        self.assertEqual(self.controller.status, "suspended")
        self.assertEqual(len(self.transport.sent), count)

    async def test_disarm_and_native_off_still_send_nothing(self):
        await self.latch()
        count = len(self.transport.sent)
        await self.tick(500, mode="absent", armed=False)
        self.assertEqual(self.controller.status, "observation")
        self.transport.entities["climate.pump"].state = "off"
        await self.tick(600, mode="absent")
        self.assertEqual(self.controller.status, "pump_off")
        self.assertEqual(len(self.transport.sent), count)

    async def test_live_permission_revocation_still_blocks_native_pump(self):
        await self.latch()
        count = len(self.transport.sent)
        self.controller.permit = lambda: False
        await self.tick(500, mode="absent")
        self.assertEqual(self.controller.status, "suspended")
        self.assertEqual(len(self.transport.sent), count)

    async def test_red_stop_and_owned_resume_work_with_emitter_fault(self):
        await self.latch()
        self.cfg["settings"].update(tempo_enabled=True, tempo_today_entity="sensor.tempo")
        # UTC fixture: 10:53 local; confirmed red stop, not a setpoint bypass.
        await self.tick(500, today="red")
        self.assertEqual(self.transport.state("climate.pump").state, "off")
        self.assertTrue(self.controller.tempo_state["confirmed"])
        await self.tick(14 * 3600, today="red")
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        await self.tick(14 * 3600 + 61, mode="night", today="red")
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 18)
        self.assertEqual(sum(c.entity_id == "number.valve" for c in self.transport.sent), 1)

    async def test_pump_fault_wins_independent_of_pending_insertion_order(self):
        for entities in (("climate.pump", "number.valve"), ("number.valve", "climate.pump")):
            self.controller.reset_fault()
            for entity in entities:
                command = Command(entity, "set_value", "value", 50, None)
                self.controller.pending[command.key] = Pending(command, self.now)
            self.controller.check_pending(self.now + timedelta(seconds=181), 180, "climate.pump")
            self.assertEqual(self.controller.fault, "command_not_applied:climate.pump")
