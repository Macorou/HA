"""Real Home Assistant fixtures, executed by the Linux CI job."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_heat_manager.const import DEFAULTS, DOMAIN, ROOM_DEFAULTS


@pytest.fixture(autouse=True)
def enable_integration(enable_custom_integrations):
    yield


@pytest.fixture
def installation(hass):
    hass.states.async_set("climate.pump", "off", {"hvac_modes": ["off", "heat", "auto"]})
    hass.states.async_set("sensor.living", "19", {"unit_of_measurement": "°C"})
    hass.states.async_set("number.valve", "0", {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"})
    hass.states.async_set("sensor.grid", "-3500", {"unit_of_measurement": "W"})
    data = {
        "settings": DEFAULTS | {"pump_entity": "climate.pump", "grid_entity": "sensor.grid"},
        "rooms": [
            ROOM_DEFAULTS | {"id": "living", "name": "Salon", "sensor": "sensor.living", "actuators": ["number.valve"]}
        ],
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data, title="Smart Heat Manager")
    entry.add_to_hass(hass)
    return entry
