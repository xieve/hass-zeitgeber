"""
zeitgeber Component for Home-Assistant.

This component calculates color temperature and brightness to synchronize
your color changing lights with perceived color temperature of the sky throughout
the day. This gives your environment a more natural feel, with cooler whites during
the midday and warmer tints near twilight and dawn.

In addition, the component sets your lights to a nice warm white at 1% in "Sleep" mode,
which is far brighter than starlight but won't reset your circadian rhythm or break down
too much rhodopsin in your eyes.

Human circadian rhythms are heavily influenced by ambient light levels and
hues. Hormone production, brainwave activity, mood and wakefulness are
just some of the cognitive functions tied to cyclical natural light.
http://en.wikipedia.org/wiki/Zeitgeber

Here's some further reading:

http://www.cambridgeincolour.com/tutorials/sunrise-sunset-calculator.htm
http://en.wikipedia.org/wiki/Color_temperature

Technical notes: I had to make a lot of assumptions when writing this app
    *   There are no considerations for weather or altitude, but does use your
        hub's location to calculate the sun position.
    *   The component doesn't calculate a true "Blue Hour" -- it just sets the
        lights to 2700K (warm white) until your hub goes into Night mode
"""

import bisect
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum, auto
import logging
from math import asin, cos, pi, radians, sin
from typing import (
    TYPE_CHECKING,
    Any,
    Generator,
    Iterable,
    Literal,
    Mapping,
    Optional,
    ReadOnly,
    Sequence,
    TypedDict,
    cast,
    final,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.light import ATTR_TRANSITION, VALID_TRANSITION
from homeassistant.const import (
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
    Platform,
)
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_sunrise,
    async_track_sunset,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util.color import (
    color_RGB_to_xy,
    color_temperature_to_rgb,
    color_xy_to_hs,
)
from packaging import version

from .const import DOMAIN, Conf

CONF_MIN_CT, DEFAULT_MIN_CT = "min_colortemp", 2500
CONF_MAX_CT, DEFAULT_MAX_CT = "max_colortemp", 5500
CONF_MIN_BRIGHT, DEFAULT_MIN_BRIGHT = "min_brightness", 0
CONF_MAX_BRIGHT, DEFAULT_MAX_BRIGHT = "max_brightness", 100
CONF_INTERVAL, DEFAULT_INTERVAL = "interval", 300
CONF_SUNRISE_OFFSET = "sunrise_offset"
CONF_SUNSET_OFFSET = "sunset_offset"
CONF_DAWN_TIME = "dawn_time"
CONF_SUNRISE_TIME = "sunrise_time"
CONF_SUNSET_TIME = "sunset_time"
CONF_DUSK_TIME = "dusk_time"
DEFAULT_TRANSITION = 60
_PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.TIME]

REQUIRED_HA_VERSION = "2024.1.0"

if version.parse(HA_VERSION) < version.parse(REQUIRED_HA_VERSION):
    raise RuntimeError(
        f"This integration requires Home Assistant {REQUIRED_HA_VERSION} or newer."
    )

type SunEventsKey = Literal[
    "dawn",
    "sunrise",
    "golden_hour_am",
    "golden_hour_pm",
    "sunset",
    "dusk",
]
type SunEvents = dict[SunEventsKey, datetime]
type ManualConfigTimes = dict[SunEventsKey, time]
type ZeitgeberConfigEntry = ConfigEntry[ZeitgeberCoordinator]


@dataclass
class LightState:
    brightness: float
    temperature: int

    @property
    def rgb(self) -> tuple[int, int, int]:
        return cast(
            tuple[int, int, int],
            tuple(round(x) for x in color_temperature_to_rgb(self.temperature)),
        )

    @property
    def xy(self) -> tuple[float, float]:
        return color_RGB_to_xy(*self.rgb)

    @property
    def hs(self) -> tuple[float, float]:
        return color_xy_to_hs(*self.xy)


@dataclass
class ZeitgeberData:
    light_state: Optional[LightState]
    manual_config_times: ManualConfigTimes
    # sun_events: SunEvents


async def async_setup_entry(hass: HomeAssistant, entry: ZeitgeberConfigEntry) -> None:
    """Set up the zeitgeber platform."""
    coordinator = ZeitgeberCoordinator(
        hass,
        entry,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)


def ease_sine(x: float) -> float:
    return -(cos(pi * x) - 1) / 2


def interpolate(a: float, b: float, x: float) -> float:
    """
    Interpolate linearly between `a` and `b` where `a <= b` and `0 <= x <= 1`
    """
    return a + (b - a) * x


class ZeitgeberCoordinator(DataUpdateCoordinator[ZeitgeberData]):
    """Calculate universal zeitgeber values."""

    brightness: float
    """Brightness in percent"""

    @callback
    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ZeitgeberConfigEntry,
    ):
        super().__init__(
            hass,
            logging.getLogger(__name__),
            config_entry=config_entry,
            name=DOMAIN,
            # always_update=False,
            # update_interval=timedelta(minutes=1),
        )
        self._poll = False
        self._wake_next: Optional[datetime] = None

    @callback
    def _get_sun_events(self, day: date) -> SunEvents:
        try:
            dawn = datetime.combine(day, self.data.manual_config_times["dawn"])
            sunrise = datetime.combine(day, self.data.manual_config_times["sunrise"])
            sunset = datetime.combine(day, self.data.manual_config_times["sunset"])
            dusk = datetime.combine(day, self.data.manual_config_times["dusk"])
        except KeyError:
            return {}
        # observer = Observer(self._latitude, self._longitude, self._elevation)
        # dawn = sun.dawn(observer)
        # sunrise = sun.sunrise(observer)
        # sunset = sun.sunset(observer)
        # dusk = sun.dusk(observer)

        # TODO: make this more flexible, allow customization of golden hour etc
        events: SunEvents = {
            "dawn": dawn,
            "sunrise": sunrise,
            "golden_hour_am": sunrise + (sunrise - dawn),
            # "noon": sunrise + (sunset - sunrise) / 2,
            "golden_hour_pm": sunset - (dusk - sunset),
            "sunset": sunset,
            "dusk": dusk,
        }

        return events

    @callback
    def _relevant_events(self, now: datetime) -> list[tuple[SunEventsKey, datetime]]:
        """
        Returns the previous and next solar event
        """
        events = [
            pair
            for days in [-1, 0, 1]
            for pair in tuple(self._get_sun_events(now + timedelta(days=days)).items())
        ]
        events.sort(key=lambda pair: pair[1])
        index_now = bisect.bisect(events, now, key=lambda pair: pair[1])
        return events[index_now - 1 : index_now + 1]

    @callback
    def _update(self, now: datetime) -> ZeitgeberData:
        """Update zeitgeber data. Warning: this updates `self.data` statefully."""
        self.logger.debug(self.config_entry.options)

        def target_state(event: SunEventsKey):
            assert self.config_entry is not None
            o = self.config_entry.options
            match event:
                case "dawn":
                    return LightState(o[Conf.MIN_BRIGHTNESS], o[Conf.MIN_COLOR_TEMP])
                case "sunrise":
                    return LightState(o[Conf.MAX_BRIGHTNESS], o[Conf.MIN_COLOR_TEMP])
                case "golden_hour_am":
                    return LightState(o[Conf.MAX_BRIGHTNESS], o[Conf.MAX_COLOR_TEMP])
                case "golden_hour_pm":
                    return LightState(o[Conf.MAX_BRIGHTNESS], o[Conf.MAX_COLOR_TEMP])
                case "sunset":
                    return LightState(o[Conf.MAX_BRIGHTNESS], o[Conf.MIN_COLOR_TEMP])
                case "dusk":
                    return LightState(o[Conf.MIN_BRIGHTNESS], o[Conf.MIN_COLOR_TEMP])

        if self.data is None:
            self.data = ZeitgeberData(None, {})

        events: list[tuple[SunEventsKey, datetime]] = self._relevant_events(now)

        # If uninitialized
        if len(events) < 2:
            return self.data

        [(prev_event, prev_dt), (next_event, next_dt)] = events

        prev_target = target_state(prev_event)
        next_target = target_state(next_event)

        if prev_target == next_target:
            self.data.light_state = LightState(
                prev_target.brightness, prev_target.temperature
            )
            self._wake_next = next_dt
        else:
            eased_progress = ease_sine((now - prev_dt) / (next_dt - prev_dt))
            self.data.light_state = LightState(
                interpolate(
                    prev_target.brightness, next_target.brightness, eased_progress
                ),
                round(
                    interpolate(
                        prev_target.temperature, next_target.temperature, eased_progress
                    )
                ),
            )
            self._wake_next = None

        return self.data

    @callback
    async def _async_update_data(self) -> ZeitgeberData:
        """Update zeitgeber data and schedule next update"""
        data = self._update(datetime.now())

        async def refresh(*_):
            await self.async_refresh()

        if self._wake_next is None:
            self.update_interval = timedelta(minutes=1)
        else:
            async_track_point_in_time(self.hass, refresh, self._wake_next)

        return data


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    hour = 3600
    sunrise, sunset = 6 * hour, 20 * hour
    noon = (sunrise + sunset) / 2
    midnight = noon + 12 * hour

    sub1 = plt.subplot(2, 1, 1)
    sub2 = plt.subplot(2, 1, 2)

    zeitgeber = ZeitgeberCoordinator(
        None,
        {},
    )

    percent = []
    rgb = []
    for now in (minute * 60 + 30 for minute in range(24 * 60)):
        zeitgeber._update(datetime.fromtimestamp(now))
        percent.append(zeitgeber.data.light_state.brightness)
        rgb.append(
            [
                int(x)
                for x in color_temperature_to_rgb(
                    zeitgeber.data.light_state.temperature
                )
            ]
        )

    sub1.plot(percent)
    sub2.imshow([rgb], aspect="auto")
    plt.show()
