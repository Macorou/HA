"""One TRVZB is a coordinated opening/closing/climate group, never two valves."""

import unittest
from datetime import UTC, datetime, timedelta

# isort: off
from tests.support import FakeTransport, config
from shm_core.adapters import EntityState
from shm_core.controller import Controller
from shm_core.emitters import emitter_plan, room_actuator_entities, room_emitters
from shm_core.engine import Engine
from shm_core.models import Snapshot, effective_config
from shm_core.validation import validate_config
# isort: on


def trvzb_fixture():
    cfg = config(min_on=300, min_off=300, demand_delay=0, drain_delay=60, command_interval=15, ack_timeout=30)
    room = cfg["rooms"][0]
    room["actuators"] = []
    room["trvzb_heads"] = [
        {
            "id": "head",
            "climate_entity": "climate.head",
            "opening_entity": "number.opening",
            "closing_entity": "number.closing",
            "firmware_confirmed": True,
        }
    ]
    transport = FakeTransport()
    transport.entities.update(
        {
            "climate.head": EntityState("off", {"hvac_modes": ["heat", "off", "auto"]}),
            "number.opening": EntityState("0", {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"}),
            "number.closing": EntityState("100", {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"}),
        }
    )
    return cfg, transport


class TRVZBTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg, self.transport = trvzb_fixture()
        self.room = self.cfg["rooms"][0]
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        self.controller = Controller(self.transport, self.now)
        self.engine = Engine()

    def plan(self, opening):
        return emitter_plan(room_emitters(self.room)[0], self.transport, self.room, opening)

    def test_endpoints_are_complementary_for_all_percentages(self):
        for opening in range(101):
            commands = self.plan(opening)
            self.assertEqual(commands[0].value, opening)
            self.assertEqual(commands[1].value, 100 - opening)
            self.assertEqual(commands[2].value, "heat")
            self.assertTrue(all(c.field != "temperature" for c in commands))

    def test_distinct_roles_and_only_one_logical_emitter(self):
        self.assertEqual(len(room_emitters(self.room)), 1)
        self.assertEqual(set(room_actuator_entities(self.room)), {"climate.head", "number.opening", "number.closing"})
        validate_config(self.cfg)

    def test_missing_closing_entity_rejected(self):
        self.room["trvzb_heads"][0].pop("closing_entity")
        with self.assertRaisesRegex(ValueError, "trvzb_entities_required"):
            validate_config(self.cfg)

    def test_firmware_confirmation_required(self):
        self.room["trvzb_heads"][0]["firmware_confirmed"] = False
        with self.assertRaisesRegex(ValueError, "trvzb_firmware_required"):
            self.plan(50)

    def test_duplicate_entity_across_group_and_standard_rejected(self):
        self.room["actuators"] = ["climate.head"]
        with self.assertRaisesRegex(ValueError, "duplicate_actuator"):
            validate_config(self.cfg)

    def test_same_opening_and_closing_entity_rejected(self):
        self.room["trvzb_heads"][0]["closing_entity"] = "number.opening"
        with self.assertRaisesRegex(ValueError, "duplicate_actuator"):
            validate_config(self.cfg)

    def test_legacy_configuration_still_loads(self):
        original = config()
        original["rooms"][0].pop("trvzb_heads", None)
        loaded = effective_config(original)
        validate_config(loaded)
        self.assertEqual(loaded["rooms"][0]["trvzb_heads"], [])
        self.assertEqual(room_emitters(loaded["rooms"][0])[0].profile, "standard")

    def test_incompatible_percentage_steps_rejected(self):
        self.transport.entities["number.closing"].attributes["step"] = 10
        with self.assertRaisesRegex(ValueError, "trvzb_steps_incompatible"):
            self.plan(37)

    def test_endpoints_not_allowed_as_independent_standard_valves(self):
        self.room["trvzb_heads"] = []
        self.room["actuators"] = ["number.sonoff_valve_closing_degree"]
        with self.assertRaisesRegex(ValueError, "trvzb_pair_required"):
            validate_config(self.cfg)

    async def tick(self, sec, heat=True, armed=True):
        decision = self.engine.evaluate(self.cfg, Snapshot(self.now, {"living": 18 if heat else 23}), {})
        await self.controller.tick(self.cfg, decision, self.now + timedelta(seconds=sec), armed)

    async def test_both_endpoints_before_head_mode_and_pump_setpoint(self):
        await self.tick(0)
        await self.tick(300)
        self.assertEqual(
            [c.entity_id for c in self.transport.sent],
            ["number.opening", "number.closing", "climate.head", "climate.pump"],
        )

    async def test_no_commands_in_observation(self):
        await self.tick(0, armed=False)
        await self.tick(900, armed=False)
        self.assertEqual(self.transport.sent, [])

    async def test_missing_member_blocks_before_any_command(self):
        self.transport.entities["number.closing"].state = "unavailable"
        await self.tick(0)
        self.assertEqual(self.transport.sent, [])
        self.assertEqual(self.controller.status, "command_fault")

    async def test_closing_ack_required_before_pump_setpoint(self):
        original_send = self.transport.send

        async def send(command):
            if command.entity_id == "number.closing":
                self.transport.sent.append(command)
                return
            await original_send(command)

        self.transport.send = send
        await self.tick(0)
        await self.tick(10)
        self.assertEqual(self.controller.status, "opening_emitters")
        self.assertEqual(self.transport.state("climate.pump").attributes["temperature"], 17)
        await self.tick(331)
        self.assertEqual(self.controller.status, "command_fault")

    async def test_pair_closes_without_turning_off_autonomous_pump(self):
        await self.tick(0)
        await self.tick(300)
        await self.tick(315)
        await self.tick(400, heat=False)
        self.assertEqual(float(self.transport.state("number.opening").state), 0)
        self.assertEqual(float(self.transport.state("number.closing").state), 100)
        await self.tick(615, heat=False)
        await self.tick(630, heat=False)
        self.assertEqual(self.controller.status, "running")
        self.assertEqual(self.transport.state("climate.pump").state, "heat")
        await self.tick(691, heat=False)
        self.assertEqual(float(self.transport.state("number.opening").state), 0)
        self.assertEqual(float(self.transport.state("number.closing").state), 100)

    async def test_no_duplicate_writes_on_stable_demand(self):
        await self.tick(0)
        await self.tick(300)
        count = len(self.transport.sent)
        await self.tick(315)
        await self.tick(330)
        self.assertEqual(len(self.transport.sent), count)


if __name__ == "__main__":
    unittest.main()
