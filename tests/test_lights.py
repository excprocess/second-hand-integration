"""Fork: switch the clock's lights off with a picked entity or the Lights switch."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.second_hand.const import CONF_HELPERS, CONF_SUPPRESS, DOMAIN
from custom_components.second_hand.controller import ClockController

from .test_integration import FakeLink, _settle

NIGHT = "input_boolean.night_mode"


def _tea(hass: HomeAssistant, seconds: float = 180) -> None:
    ends = dt_util.utcnow() + timedelta(seconds=seconds)
    hass.states.async_set("timer.tea", "active", {"finishes_at": ends.isoformat()})


async def test_entity_on_hides_timers_and_off_restores_them(hass: HomeAssistant) -> None:
    hass.states.async_set(NIGHT, "off")
    _tea(hass)
    link = FakeLink()
    controller = ClockController(hass, [], ["timer.tea"], link, suppress_entities=[NIGHT])
    await controller.async_start()
    link.up()
    assert link.labels()[2:] == ["SetAlert"]

    hass.states.async_set(NIGHT, "on")
    await _settle(hass)
    assert link.labels()[3:] == ["DeleteAlert"]
    assert "helper:timer.tea" in controller.timers  # the Timers sensor still lists it

    # A new timer started while suppressed stays off the clock.
    hass.states.async_set("timer.mug", "active", {"finishes_at": (dt_util.utcnow() + timedelta(minutes=5)).isoformat()})
    await _settle(hass)
    assert len(link.sent) == 4

    hass.states.async_set(NIGHT, "off")
    await _settle(hass)
    assert link.labels()[4:] == ["SetAlert"]
    await controller.async_stop()


async def test_no_pulse_and_connect_shows_nothing_while_suppressed(hass: HomeAssistant) -> None:
    hass.states.async_set(NIGHT, "on")
    _tea(hass, 1)
    link = FakeLink()
    controller = ClockController(hass, [], ["timer.tea"], link, suppress_entities=[NIGHT])
    await controller.async_start()
    link.up()
    assert link.labels() == ["timeinfo", "ClearIndicator"]
    hass.bus.async_fire("timer.finished", {"entity_id": "timer.tea"})
    await asyncio.sleep(2.3)
    await _settle(hass)
    assert link.labels() == ["timeinfo", "ClearIndicator"]
    await controller.async_stop()


async def test_lights_switch_and_changing_the_entities(hass: HomeAssistant) -> None:
    hass.states.async_set(NIGHT, "on")
    _tea(hass)
    link = FakeLink()
    controller = ClockController(hass, [], ["timer.tea"], link)
    await controller.async_start()
    link.up()
    assert link.labels()[2:] == ["SetAlert"]
    controller.set_lights_enabled(False)
    assert link.labels()[3:] == ["DeleteAlert"]
    controller.update_sources([], ["timer.tea"], [], [NIGHT])
    controller.set_lights_enabled(True)  # NIGHT is on, so still hidden
    await _settle(hass)
    assert link.labels()[3:] == ["DeleteAlert"]
    hass.states.async_set(NIGHT, "off")
    await _settle(hass)
    assert link.labels()[4:] == ["SetAlert"]
    await controller.async_stop()


async def test_lights_switch_entity(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Kitchen clock", options={CONF_HELPERS: ["timer.tea"], CONF_SUPPRESS: []})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.kitchen_clock_lights").state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.kitchen_clock_lights"}, blocking=True)
    assert hass.states.get("switch.kitchen_clock_lights").state == "off"
    assert entry.runtime_data.lights_suppressed
    assert await hass.config_entries.async_unload(entry.entry_id)
