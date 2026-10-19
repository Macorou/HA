"""Load the pure package without executing the Home Assistant entry point."""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "custom_components" / "smart_heat_manager"
if "shm_core" not in sys.modules:
    package = types.ModuleType("shm_core")
    package.__path__ = [str(CORE)]
    package.__spec__ = importlib.util.spec_from_loader("shm_core", loader=None, is_package=True)
    sys.modules["shm_core"] = package

from shm_core.adapters import EntityState  # noqa: E402
from shm_core.const import DEFAULTS, ROOM_DEFAULTS  # noqa: E402


def config(**settings):
    return {
        "settings": DEFAULTS | {"pump_entity": "climate.pump"} | settings,
        "rooms": [
            ROOM_DEFAULTS | {"id": "living", "name": "Salon", "sensor": "sensor.living", "actuators": ["number.valve"]}
        ],
    }


class FakeTransport:
    def __init__(self, acknowledge=True):
        self.entities = {
            "climate.pump": EntityState("off", {"hvac_modes": ["off", "heat", "auto"]}),
            "number.valve": EntityState("0", {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"}),
        }
        self.sent = []
        self.acknowledge = acknowledge
        self.failure = False

    def state(self, entity_id):
        return self.entities.get(entity_id)

    def has_service(self, domain, service):
        return True

    async def send(self, command):
        self.sent.append(command)
        if self.failure:
            raise RuntimeError("cloud_disconnected")
        if self.acknowledge:
            state = self.entities[command.entity_id]
            if command.attribute:
                state.attributes[command.attribute] = command.value
            else:
                state.state = str(command.value)
