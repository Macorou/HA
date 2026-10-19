"""Duration qualification must use elapsed time across a DST fold."""

import unittest
from datetime import datetime, timedelta, tzinfo

# isort: off
from tests.support import config
from shm_core.presence import Presence
from shm_core.solar import Solar
from shm_core.controller import Controller
from tests.support import FakeTransport
# isort: on


class FoldZone(tzinfo):
    def utcoffset(self, dt):
        return timedelta(hours=2 - dt.fold)

    def dst(self, dt):
        return timedelta(0)


class ClockTests(unittest.TestCase):
    def test_qualifications_across_repeated_local_hour(self):
        zone = FoldZone()
        before = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=0)
        after = datetime(2026, 10, 25, 2, 30, 1, tzinfo=zone, fold=1)
        self.assertEqual((after - before).total_seconds(), 1)  # wall clock alone is wrong
        cfg = config()["settings"] | {"solar_delay": 60}
        solar = Solar()
        self.assertFalse(solar.update(4000, before, True, cfg))
        self.assertTrue(solar.update(4000, after, True, cfg))
        presence = Presence()
        self.assertEqual(presence.update("off", before, 60), "present")
        self.assertEqual(presence.update("off", after, 60), "absent")

    def test_controller_normalizes_initial_transition(self):
        before = datetime(2026, 10, 25, 2, 30, tzinfo=FoldZone(), fold=0)
        controller = Controller(FakeTransport(), before)
        self.assertEqual(controller.transition.hour, 0)


if __name__ == "__main__":
    unittest.main()
