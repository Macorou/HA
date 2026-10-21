"""Persistent operator arming, feature toggles and expiring economic overrides."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .entity import HeatEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities(
        [
            *(
                HeatSwitch(c, key)
                for key in (
                    "armed",
                    "automation_enabled",
                    "solar_enabled",
                    "force",
                    "tempo_bypass",
                    "night_schedule_enabled",
                )
            ),
            *(HeatSwitch(c, "room_solar", room) for room in c.config["rooms"]),
        ]
    )


class HeatSwitch(HeatEntity, SwitchEntity):
    def __init__(self, coordinator, key, room=None):
        super().__init__(coordinator, key, room)
        self.key = key
        if key == "armed":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self):
        c = self.coordinator
        if self.key == "armed":
            return c.armed
        if self.key in ("force", "tempo_bypass"):
            return bool(c.override(self.key))
        if self.key == "night_schedule_enabled":
            return c.runtime.get(self.key, c.settings[self.key])
        if self.room:
            return c.runtime.get("room_solar", {}).get(self.room["id"], self.room["solar_enabled"])
        return c.runtime.get(self.key, c.settings["solar_enabled"] if self.key == "solar_enabled" else True)

    @property
    def extra_state_attributes(self):
        if self.key == "armed":
            return {"persistent": True, "waiting_for_ha_start": self.coordinator.startup_pending}
        if self.key == "night_schedule_enabled":
            return {"schedule_type": "night"}
        if self.key in ("force", "tempo_bypass"):
            return {
                "expires_at": self.coordinator.runtime["overrides"].get(self.key, {}).get("until")
                if self.is_on
                else None
            }
        return None

    async def change(self, value):
        c = self.coordinator
        if self.key == "armed":
            await c.arm(value)
        elif self.key in ("force", "tempo_bypass"):
            if value:
                await c.set_override(self.key, True)
            else:
                await c.clear_override(self.key)
        elif self.room:
            await c.set_preference("room_solar", value, self.room["id"])
        else:
            await c.set_preference(self.key, value)

    async def async_turn_on(self, **kwargs):
        await self.change(True)

    async def async_turn_off(self, **kwargs):
        await self.change(False)
