"""Lights: a manual switch to hide the timers on the clock (fork addition)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EchoWallClockConfigEntry
from .entity import ClockEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: EchoWallClockConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([LightsSwitch(entry)])


class LightsSwitch(ClockEntity, SwitchEntity, RestoreEntity):
    """On: the clock shows timers. Off: it shows nothing, whatever the timers do. Remembered across restarts."""

    def __init__(self, entry: EchoWallClockConfigEntry) -> None:
        super().__init__(entry, "lights")

    @property
    def is_on(self) -> bool:
        return self._controller.lights_enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state == "off":
            self._controller.set_lights_enabled(False)

    async def async_turn_on(self, **kwargs: object) -> None:
        self._controller.set_lights_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        self._controller.set_lights_enabled(False)
