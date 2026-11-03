"""
Circadian Lighting Component for Home-Assistant.

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
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum, auto
from math import asin, cos, pi, radians, sin
from typing import (
    TYPE_CHECKING,
    Generator,
    Iterable,
    Literal,
    Mapping,
    ReadOnly,
    Sequence,
    TypedDict,
    cast,
    final,
)

from astral import Observer, sun
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol
from homeassistant.components.light import ATTR_TRANSITION, VALID_TRANSITION
from homeassistant.const import (
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_sunrise,
    async_track_sunset,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.sun import get_astral_location
from homeassistant.util.color import (
    color_RGB_to_xy,
    color_temperature_to_rgb,
    color_xy_to_hs,
)
from packaging import version

DOMAIN = "circadian_lighting"
CIRCADIAN_LIGHTING_UPDATE_TOPIC = f"{DOMAIN}_update"

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

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_MIN_CT, default=DEFAULT_MIN_CT): vol.All(
                    vol.Coerce(int), vol.Range(min=1000, max=10000)
                ),
                vol.Optional(CONF_MAX_CT, default=DEFAULT_MAX_CT): vol.All(
                    vol.Coerce(int), vol.Range(min=1000, max=10000)
                ),
                vol.Optional(CONF_MIN_BRIGHT, default=DEFAULT_MIN_BRIGHT): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100)
                ),
                vol.Optional(CONF_MAX_BRIGHT, default=DEFAULT_MAX_BRIGHT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=100)
                ),
                vol.Optional(CONF_SUNRISE_OFFSET): cv.time_period_str,
                vol.Optional(CONF_SUNSET_OFFSET): cv.time_period_str,
                vol.Optional(CONF_SUNRISE_TIME): cv.time,
                vol.Optional(CONF_SUNSET_TIME): cv.time,
                vol.Optional(CONF_LATITUDE): cv.latitude,
                vol.Optional(CONF_LONGITUDE): cv.longitude,
                vol.Optional(CONF_ELEVATION): float,
                vol.Optional(CONF_INTERVAL, default=DEFAULT_INTERVAL): cv.time_period,
                vol.Optional(
                    ATTR_TRANSITION, default=DEFAULT_TRANSITION
                ): VALID_TRANSITION,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

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


@dataclass
class LightState:
    brightness: float
    temperature: int


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Circadian Lighting platform."""
    conf = config[DOMAIN]
    hass.data[DOMAIN] = CircadianLighting(
        hass,
        min_colortemp=conf.get(CONF_MIN_CT),
        max_colortemp=conf.get(CONF_MAX_CT),
        min_brightness=config.get(CONF_MIN_BRIGHT),
        max_brightness=config.get(CONF_MAX_BRIGHT),
        sunrise_offset=conf.get(CONF_SUNRISE_OFFSET),
        sunset_offset=conf.get(CONF_SUNSET_OFFSET),
        dawn_time=conf.get(CONF_DAWN_TIME),
        sunrise_time=conf.get(CONF_SUNRISE_TIME),
        sunset_time=conf.get(CONF_SUNSET_TIME),
        dusk_time=conf.get(CONF_DUSK_TIME),
        latitude=conf.get(CONF_LATITUDE, hass.config.latitude),
        longitude=conf.get(CONF_LONGITUDE, hass.config.longitude),
        elevation=conf.get(CONF_ELEVATION, hass.config.elevation),
        transition=conf.get(ATTR_TRANSITION),
    )
    await hass.data[DOMAIN]._async_init(interval=conf.get(CONF_INTERVAL))
    hass.async_create_task(async_load_platform(hass, "sensor", DOMAIN, {}, config))

    return True


def ease_sine(x: float):
    return -(cos(pi * x) - 1) / 2


def interpolate(a: float, b: float, x: float):
    """
    Interpolate linearly between `a` and `b` where `a <= b` and `0 <= x <= 1`
    """
    return a + (b - a) * x


class CircadianLighting:
    """Calculate universal Circadian values."""

    brightness: float
    """Brightness in percent"""

    def __init__(
        self,
        hass,
        min_colortemp,
        max_colortemp,
        min_brightness,
        max_brightness,
        sunrise_offset,
        sunset_offset,
        dawn_time,
        sunrise_time,
        sunset_time,
        dusk_time,
        latitude,
        longitude,
        elevation,
        transition,
    ):
        self.hass: HomeAssistant = hass
        self._min_colortemp = min_colortemp
        self._max_colortemp = max_colortemp
        self._min_brightness = min_brightness
        self._max_brightness = max_brightness
        self._sunrise_offset = sunrise_offset
        self._sunset_offset = sunset_offset
        # FIXME: this needs to be initialized from the saved config values
        self._manual_config_times: ManualConfigTimes = {}
        self._latitude = latitude
        self._longitude = longitude
        self._elevation = elevation
        self._transition = transition

    async def _async_init(self, interval):
        if self._manual_config_times["sunrise"] is not None:
            async_track_time_change(
                self.hass,
                self.async_loop,
                hour=self._manual_config_times["sunrise"].hour,
                minute=self._manual_config_times["sunrise"].minute,
                second=self._manual_config_times["sunrise"].second,
            )
        else:
            async_track_sunrise(self.hass, self.async_loop, self._sunrise_offset)

        if self._manual_config_times["sunset"] is not None:
            async_track_time_change(
                self.hass,
                self.async_loop,
                hour=self._manual_config_times["sunset"].hour,
                minute=self._manual_config_times["sunset"].minute,
                second=self._manual_config_times["sunset"].second,
            )
        else:
            async_track_sunset(self.hass, self.async_loop, self._sunset_offset)

        async_track_time_interval(self.hass, self.async_loop, interval)

    def _get_sun_events(self, day: date) -> SunEvents:
        if self._manual_config_times["sunrise"] is not None and self._manual_config_times["sunset"] is not None:
            dawn = datetime.combine(day, self._manual_config_times["dawn"])
            sunrise = datetime.combine(day, self._manual_config_times["sunrise"])
            sunset = datetime.combine(day, self._manual_config_times["sunset"])
            dusk = datetime.combine(day, self._manual_config_times["dusk"])
        else:
            observer = Observer(self._latitude, self._longitude, self._elevation)
            dawn = sun.dawn(observer)
            sunrise = sun.sunrise(observer)
            sunset = sun.sunset(observer)
            dusk = sun.dusk(observer)

        events: SunEvents = {
            "dawn": dawn,
            "sunrise": sunrise,
            "golden_hour_am": sunrise + (sunrise - dawn),
            # "noon": sunrise + (sunset - sunrise) / 2,
            "golden_hour_pm": sunset - (dusk - sunset),
            "sunset": sunset,
            "dusk": dusk,
        }

        if self._sunrise_offset is not None:
            events["sunrise"] += self._sunrise_offset
        if self._sunset_offset is not None:
            events["sunset"] += self._sunset_offset

        return events

    def _relevant_events(self, now: datetime) -> list[tuple[SunEventsKey, datetime]]:
        """
        Returns the previous and next solar event
        """
        events = [
            pair
            for days in [-1, 0, 1]
            for pair in tuple(self._get_sun_events(now + timedelta(days=days)).items())
        ]
        # events is already sorted, since dicts are always ordered since Python 3.7 and
        # we insert in the correct order.
        # This is assuming that dawn, sunrise, noon, sunset, dusk occur in that order
        # on any given day.
        index_now = bisect.bisect(events, now, key=lambda pair: pair[1])
        return events[index_now - 1 : index_now + 1]

    def update(self, now: datetime):
        def target_state(event: SunEventsKey):
            match event:
                case "dawn":
                    return LightState(self._min_brightness, self._min_colortemp)
                case "sunrise":
                    return LightState(self._max_brightness, self._min_colortemp)
                case "golden_hour_am":
                    return LightState(self._max_brightness, self._max_colortemp)
                case "golden_hour_pm":
                    return LightState(self._max_brightness, self._max_colortemp)
                case "sunset":
                    return LightState(self._max_brightness, self._min_colortemp)
                case "dusk":
                    return LightState(self._min_brightness, self._min_colortemp)

        events: list[tuple[SunEventsKey, datetime]] = self._relevant_events(now)
        print(events, now)

        [(prev_event, prev_dt), (next_event, next_dt)] = events

        prev_target = target_state(prev_event)
        next_target = target_state(next_event)

        if prev_target == next_target:
            self._brightness = prev_target.brightness
            self._colortemp = prev_target.temperature
        else:
            eased_progress = ease_sine((now - prev_dt) / (next_dt - prev_dt))
            if prev_target.brightness != next_target.brightness:
                self._brightness = interpolate(
                    prev_target.brightness, next_target.brightness, eased_progress
                )
            if prev_target.temperature != next_target.temperature:
                self._colortemp = interpolate(
                    prev_target.temperature, next_target.temperature, eased_progress
                )

        self._rgb_color = cast(
            tuple[int, int, int],
            tuple(int(x) for x in color_temperature_to_rgb(self._colortemp)),
        )
        self._xy_color = color_RGB_to_xy(*self._rgb_color)
        self._hs_color = color_xy_to_hs(*self._xy_color)

    async def async_loop(self, *_):
        """Update Circadian Values."""
        now = datetime.now()
        self.update(now)
        async_dispatcher_send(self.hass, CIRCADIAN_LIGHTING_UPDATE_TOPIC)


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    hour = 3600
    sunrise, sunset = 6 * hour, 20 * hour
    noon = (sunrise + sunset) / 2
    midnight = noon + 12 * hour

    sub1 = plt.subplot(2, 1, 1)
    sub2 = plt.subplot(2, 1, 2)

    circadian_lighting = CircadianLighting(
        None,
        2700,
        5000,
        0,
        100,
        None,
        None,
        time(6),
        time(7),
        time(20),
        time(21, 30),
        0,
        0,
        0,
        0,
    )

    percent = []
    rgb = []
    for now in (minute * 60 + 30 for minute in range(24 * 60)):
        circadian_lighting.update(datetime.fromtimestamp(now))
        percent.append(circadian_lighting._brightness)
        rgb.append([int(x) for x in circadian_lighting._rgb_color])

    sub1.plot(percent)
    sub2.imshow([rgb], aspect="auto")
    plt.show()
