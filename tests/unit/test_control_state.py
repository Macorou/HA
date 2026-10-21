"""The persisted command journal cannot turn a restart into a blind retry."""

import unittest
from datetime import UTC, datetime, timedelta

# isort: off
from tests.support import FakeTransport, config
from shm_core.adapters import Command
from shm_core.controller import Controller, Pending
from shm_core.controller import ControlSuspended
from shm_core.control_state import dump_control, restore_control
# isort: on


class ControlStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 21, 12, tzinfo=UTC)
        self.transport = FakeTransport(acknowledge=False)
        self.controller = Controller(self.transport, self.now)

    def test_pending_fault_and_rate_limits_round_trip(self):
        command = Command("number.valve", "set_value", "value", 50, None)
        self.controller.pending[command.key] = Pending(command, self.now)
        self.controller.last_sent[command.key] = self.now
        self.controller.fault = "command_not_applied:number.valve"
        saved = dump_control(self.controller)
        restarted = Controller(self.transport, self.now)
        restore_control(restarted, saved, ["number.valve"])
        self.assertEqual(dump_control(restarted), saved)

    def test_missing_journal_never_arms_a_new_controller(self):
        restore_control(self.controller, None, [])
        self.assertIsNone(self.controller.fault)
        self.assertEqual(self.controller.pending, {})

    def test_malformed_journal_fails_closed(self):
        for saved in ([], {"pending": []}, {"fault": True}, {"last_sent": {"number.valve:value": "bad"}}):
            with self.subTest(saved=saved):
                restore_control(self.controller, saved, ["number.valve"])
                self.assertEqual(self.controller.fault, "invalid_saved_control_state")

    def test_removed_entities_and_ambiguous_tempo_intent(self):
        command = Command("climate.pump", "set_hvac_mode", "hvac_mode", "off", None)
        self.controller.pending[command.key] = Pending(command, self.now)
        saved = dump_control(self.controller)
        restore_control(self.controller, saved, [])
        self.assertEqual(self.controller.pending, {})
        restore_control(self.controller, saved, ["climate.pump"])
        self.assertEqual(self.controller.fault, "invalid_saved_control_state")
        self.controller.tempo_state = {"confirmed": True}
        saved["fault"] = None
        restore_control(self.controller, saved, ["climate.pump"])
        self.assertIn(command.key, self.controller.pending)

    async def test_checkpoint_precedes_write_and_restart_does_not_retry_pending(self):
        order = []

        async def checkpoint():
            order.append("saved")
            self.saved = dump_control(self.controller)

        self.controller.save_state = checkpoint
        original = self.transport.send

        async def send(command):
            order.append("sent")
            await original(command)

        self.transport.send = send
        command = Command("number.valve", "set_value", "value", 50, None)
        await self.controller.apply(command, self.now, 60)
        self.assertEqual(order, ["saved", "sent"])
        restarted = Controller(self.transport, self.now)
        restore_control(restarted, self.saved, ["number.valve"])
        await restarted.apply(command, self.now + timedelta(seconds=1), 60)
        self.assertEqual(len(self.transport.sent), 1)
        restarted.check_pending(self.now + timedelta(seconds=181), config()["settings"]["ack_timeout"])
        self.assertIsNotNone(restarted.fault)

    async def test_disarm_during_storage_checkpoint_prevents_physical_write(self):
        allowed = True
        self.controller.permit = lambda: allowed

        async def checkpoint():
            nonlocal allowed
            allowed = False

        self.controller.save_state = checkpoint
        command = Command("number.valve", "set_value", "value", 50, None)
        with self.assertRaises(ControlSuspended):
            await self.controller.apply(command, self.now, 60)
        self.assertEqual(self.transport.sent, [])


if __name__ == "__main__":
    unittest.main()
