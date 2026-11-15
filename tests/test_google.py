"""Fork: timers from Google Home's timers sensors (`leikoilja/ha-google-home`)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.second_hand import protocol
from custom_components.second_hand.const import (
    CONF_ALEXA_SENSORS,
    CONF_ASSIST_DEVICES,
    CONF_GOOGLE_SENSORS,
    CONF_HELPERS,
    DOMAIN,
)
from custom_components.second_hand.controller import ClockController
from custom_components.second_hand.sources_entities import parse_google

from .test_integration import FakeLink, _settle

SPEAKER = "sensor.kitchen_speaker_timers"
ID1 = "timer/ab65c73e-3c5f-4b14-8af9-9c2582ebb1d5"
ID2 = "timer/55ae7a73-0965-475e-9e49-2442d9dea25c"


def _item(timer_id: str, ends_at: datetime | None, status: str = "set", label: str | None = None) -> dict[str, Any]:
    """One timer dict like `ha-google-home` puts in its `timers` attribute."""
    return {
        "timer_id": timer_id,
        "fire_time": int(ends_at.timestamp()) if ends_at else None,
        "local_time": ends_at.strftime("%Y-%m-%d %H:%M:%S") if ends_at else None,
        "local_time_iso": ends_at.isoformat() if ends_at else None,
        "duration": "0:15:00",
        "status": status,
        "label": label,
    }


def _set(hass: HomeAssistant, *items: dict[str, Any]) -> None:
    ends = [datetime.fromtimestamp(i["fire_time"], UTC) for i in items if i.get("fire_time")]
    state = min(ends).isoformat() if ends else "unavailable"
    hass.states.async_set(SPEAKER, state, {"timers": list(items), "friendly_name": "Kitchen speaker timers"})


def test_parse_google() -> None:
    ends = datetime(2026, 11, 15, 15, 0, tzinfo=UTC)
    timers = parse_google(
        {
            "timers": [
                _item(ID1, ends, label="pasta"),
                _item(ID2, ends + timedelta(minutes=5), status="paused", label="tea"),
                _item("timer/ringing", ends, status="ringing"),
                _item("timer/none", None, status="none"),
                {"status": "set"},
                42,
            ]
        }
    )
    assert [(t.key, t.ends_at, t.paused, t.name) for t in timers] == [
        (f"google:{ID1}", ends, False, "pasta"),
        (f"google:{ID2}", None, True, "tea"),
    ]
    # Fallback to local_time_iso when fire_time is missing, and tolerance for epoch ms.
    iso_only = {**_item(ID1, ends), "fire_time": None}
    ms_time = {**_item(ID2, ends), "fire_time": int(ends.timestamp() * 1000)}
    assert [t.ends_at for t in parse_google({"timers": [iso_only, ms_time]})] == [ends, ends]
    assert parse_google({}) == []
    assert parse_google({"timers": [{**_item(ID1, None), "local_time_iso": None}]}) == []


async def test_google_timer_lifecycle(hass: HomeAssistant) -> None:
    link = FakeLink()
    controller = ClockController(hass, [], [], link, google_sensors=[SPEAKER])
    await controller.async_start()
    link.up()
    assert link.labels() == ["timeinfo", "ClearIndicator"]

    ends1 = dt_util.utcnow().replace(microsecond=0) + timedelta(minutes=15)
    ends2 = dt_util.utcnow().replace(microsecond=0) + timedelta(minutes=20)
    _set(hass, _item(ID1, ends1), _item(ID2, ends2, label="pasta"))
    await _settle(hass)
    assert link.labels()[2:] == ["SetAlert", "SetAlert"]
    assert controller.timers[f"google:{ID2}"].name == "pasta"

    # Pause deletes it; resume shows it again with the same token.
    _set(hass, _item(ID1, ends1, status="paused"), _item(ID2, ends2))
    await _settle(hass)
    assert link.labels()[4:] == ["DeleteAlert"]
    assert controller.timers[f"google:{ID1}"].paused
    _set(hass, _item(ID1, ends1 + timedelta(minutes=1)), _item(ID2, ends2))
    await _settle(hass)
    assert link.labels()[5:] == ["SetAlert"]
    token = protocol.alert_token(f"google:{ID1}").encode()
    assert token in link.sent[4] and token in link.sent[5]

    # Cancel (drops off the sensor long before its end): DeleteAlert, no pulse.
    _set(hass, _item(ID2, ends2))
    await _settle(hass)
    assert link.labels()[6:] == ["DeleteAlert"]
    _set(hass)
    await _settle(hass)
    assert link.labels()[7:] == ["DeleteAlert"]
    assert controller.timers == {}
    await controller.async_stop()


async def test_google_timer_ringing_pulses_once(hass: HomeAssistant) -> None:
    """When status becomes `ringing` right at the end time, the timer drops off and pulses once."""
    link = FakeLink()
    controller = ClockController(hass, [], [], link, google_sensors=[SPEAKER])
    await controller.async_start()
    link.up()
    ends = dt_util.utcnow().replace(microsecond=0) + timedelta(seconds=2)
    _set(hass, _item(ID1, ends))
    await _settle(hass)
    await asyncio.sleep(1)
    _set(hass, _item(ID1, ends, status="ringing"))
    await _settle(hass)
    await asyncio.sleep(2.5)
    await _settle(hass)
    assert link.labels()[2:] == ["SetAlert", "timers=active"]
    await controller.async_stop()


async def test_options_with_google_only(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Kitchen clock", options={CONF_HELPERS: ["timer.tea"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ends = dt_util.utcnow().replace(microsecond=0) + timedelta(minutes=5)
    _set(hass, _item(ID1, ends))

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_ASSIST_DEVICES: [], CONF_HELPERS: [], CONF_ALEXA_SENSORS: [], CONF_GOOGLE_SENSORS: [SPEAKER]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    state = hass.states.get("sensor.kitchen_clock_timers")
    assert state.state == "1"
    assert state.attributes["timers"][0]["id"] == f"google:{ID1}"
    assert await hass.config_entries.async_unload(entry.entry_id)
