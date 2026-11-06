"""
This file contains all data structures and functions used to determine the state of
this integration. All functions in here have no side-effects.
"""

from bisect import bisect
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import cos, pi
from typing import Any, Literal, Mapping, Optional, cast

from homeassistant.util.color import (
    color_RGB_to_xy,
    color_temperature_to_rgb,
    color_xy_to_hs,
)
from homeassistant.core import callback

from const import Conf

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


@callback
def ease_sine(x: float) -> float:
    return -(cos(pi * x) - 1) / 2


@callback
def interpolate(a: float, b: float, x: float) -> float:
    """
    Interpolate linearly between `a` and `b` where `a <= b` and `0 <= x <= 1`
    """
    return a + (b - a) * x


@callback
def calculate_state(
    now: datetime, options: Mapping[str, Any], manual_config_times: ManualConfigTimes
) -> tuple[Optional[datetime], Optional[LightState]]:
    """Update zeitgeber data. Warning: this updates `self.data` statefully."""

    def target_state(event: SunEventsKey):
        o = options
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

    events: list[tuple[SunEventsKey, datetime]] = relevant_events(
        now, manual_config_times
    )

    # If uninitialized
    if len(events) < 2:
        return (None, None)

    [(prev_event, prev_dt), (next_event, next_dt)] = events

    prev_target = target_state(prev_event)
    next_target = target_state(next_event)

    if prev_target == next_target:
        return (next_dt, LightState(prev_target.brightness, prev_target.temperature))
    else:
        eased_progress = ease_sine((now - prev_dt) / (next_dt - prev_dt))
        return (
            None,
            LightState(
                interpolate(
                    prev_target.brightness, next_target.brightness, eased_progress
                ),
                round(
                    interpolate(
                        prev_target.temperature, next_target.temperature, eased_progress
                    )
                ),
            ),
        )


@callback
def relevant_events(
    now: datetime, manual_config_times: ManualConfigTimes
) -> list[tuple[SunEventsKey, datetime]]:
    """
    Returns the previous and next solar event
    """
    events = [
        pair
        for days in [-1, 0, 1]
        for pair in tuple(
            get_sun_events(now + timedelta(days=days), manual_config_times).items()
        )
    ]
    events.sort(key=lambda pair: pair[1])
    index_now = bisect(events, now, key=lambda pair: pair[1])
    return events[index_now - 1 : index_now + 1]


@callback
def get_sun_events(day: date, manual_config_times: ManualConfigTimes) -> SunEvents:
    try:
        dawn = datetime.combine(day, manual_config_times["dawn"])
        sunrise = datetime.combine(day, manual_config_times["sunrise"])
        sunset = datetime.combine(day, manual_config_times["sunset"])
        dusk = datetime.combine(day, manual_config_times["dusk"])
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


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    hour = 3600
    sunrise, sunset = 6 * hour, 20 * hour
    manual_config_times: ManualConfigTimes = {
        "dawn": time(hour=6),
        "sunrise": time(hour=7),
        "sunset": time(hour=20),
        "dusk": time(hour=21),
    }
    options: dict[str, int] = {
        Conf.MIN_BRIGHTNESS: 1,
        Conf.MAX_BRIGHTNESS: 100,
        Conf.MIN_COLOR_TEMP: 2000,
        Conf.MAX_COLOR_TEMP: 5000,
    }

    sub1 = plt.subplot(2, 1, 1)
    sub2 = plt.subplot(2, 1, 2)

    percent = []
    rgb = []
    for now in (minute * 60 + 30 for minute in range(24 * 60)):
        (_, light_state) = calculate_state(datetime.fromtimestamp(now), options, manual_config_times)
        assert light_state is not None
        percent.append(light_state.brightness)
        rgb.append(
            [
                int(x)
                for x in color_temperature_to_rgb(
                    light_state.temperature
                )
            ]
        )

    sub1.plot(percent)
    sub2.imshow([rgb], aspect="auto")
    plt.show()
