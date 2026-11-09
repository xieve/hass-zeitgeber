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

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Iterable, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.light import is_on
try:
    from homeassistant.components.light.const import (
        ATTR_BRIGHTNESS,
        ATTR_COLOR_TEMP_KELVIN,
        ATTR_RGB_COLOR,
        ATTR_TRANSITION,
        ATTR_XY_COLOR,
        ATTR_HS_COLOR,
    )
except ImportError:
    from homeassistant.components.light import (
        ATTR_BRIGHTNESS,
        ATTR_COLOR_TEMP_KELVIN,
        ATTR_RGB_COLOR,
        ATTR_TRANSITION,
        ATTR_XY_COLOR,
        ATTR_HS_COLOR,
    )
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.const import Platform
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from packaging import version

from .calculate import ZeitgeberData, calculate_state

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

type ZeitgeberConfigEntry = ConfigEntry[ZeitgeberCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ZeitgeberConfigEntry) -> None:
    """Set up zeitgeber from a config entry"""
    coordinator = ZeitgeberCoordinator(
        hass,
        entry,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)


async def async_update_options(
    hass: HomeAssistant, entry: ZeitgeberConfigEntry
) -> None:
    """Apply new options"""
    entry.runtime_data._listen()
    await entry.runtime_data.async_refresh()


# TODO: remove refresh interval, i receive a state change thing whenever the lights are done updating afaict. also make sure the lights are only updated when they should be


class ZeitgeberCoordinator(DataUpdateCoordinator[ZeitgeberData]):
    """Calculate universal zeitgeber values."""

    brightness: float
    """Brightness in percent"""
    config_entry: ZeitgeberConfigEntry

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
        )
        self.data = ZeitgeberData(None, {})
        self._enabled = False
        self._listeners_stop: list[CALLBACK_TYPE] = []
        self._listen()
        self.config_entry.async_on_unload(self._stop_listeners)
        self._context = Context()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._stop_listeners()
        if enabled:
            self._listen()
        else:
            self.update_interval = None
        self.hass.add_job(self.async_refresh)

    @callback
    def _listen(self) -> None:
        """Register listener for state changes"""
        self._listeners_stop.append(
            async_track_state_change_event(
                self.hass,
                self.config_entry.options[Conf.MANAGED_ENTITIES],
                self._state_changed,
            )
        )

    @callback
    def _stop_listeners(self) -> None:
        """Stop all listeners. Deactivates entire integration."""
        for stop in self._listeners_stop:
            stop()
        self._listeners_stop = []

    async def _async_update_data(self) -> ZeitgeberData:
        """Update zeitgeber data and schedule next update"""
        if not self.enabled:
            return self.data

        wake_next, self.data.light_state = calculate_state(
            datetime.now(), self.config_entry.options, self.data.manual_config_times
        )

        async def refresh(*_):
            await self.async_refresh()

        if wake_next is None:
            # Update every minute
            self.update_interval = timedelta(minutes=1)
        else:
            # Stop polling
            self.update_interval = None
            # Wait until the next event
            self._listeners_stop.append(
                async_track_point_in_time(self.hass, refresh, wake_next)
            )
        self.hass.add_job(self.adjust_lights)

        return self.data

    async def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Called when any configured light entity changes state"""
        if (
            event.context != self._context
            and (new_state := event.data["new_state"]) is not None
            and new_state.state == STATE_ON
        ):
            await self.adjust_lights((new_state.entity_id,), 0)

    async def adjust_lights(
        self, lights: Optional[Iterable[str]] = None, transition=None
    ):
        """Apply current calculated state to light entities if they are on"""
        if transition is None:
            transition = (self.update_interval or timedelta(minutes=1)).seconds

        config_entry = self.config_entry

        light_state = self.data.light_state
        if light_state is None:
            self.logger.warning("No light state")
            return

        lights = lights or config_entry.options[Conf.MANAGED_ENTITIES]
        assert lights is not None

        tasks = []
        for light in lights:
            entity = self.hass.states.get(light)
            if entity is None:
                self.logger.warning(f"Entity {light} does not exist")
                continue
            if not is_on(self.hass, light):
                continue

            service_data = {ATTR_ENTITY_ID: light, ATTR_TRANSITION: transition}
            service_data[ATTR_BRIGHTNESS] = round((light_state.brightness / 100) * 255)

            preference = ("color_temp", "rgb", "xy", "hs")
            match next(
                (
                    mode
                    for mode in preference
                    if mode in entity.attributes["supported_color_modes"]
                ),
                None,
            ):
                case "color_temp":
                    service_data[ATTR_COLOR_TEMP_KELVIN] = light_state.temperature
                case "rgb":
                    service_data[ATTR_RGB_COLOR] = light_state.rgb
                case "xy":
                    service_data[ATTR_XY_COLOR] = light_state.xy
                case "hs":
                    service_data[ATTR_HS_COLOR] = light_state.hs
                case None:
                    self.logger.debug(
                        f"{light} does not have any supported color mode, only setting "
                        "brightness."
                    )

            self.logger.debug(
                "Scheduling 'light.turn_on' with the following 'service_data': %s",
                service_data,
            )
            tasks.append(
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        LIGHT_DOMAIN,
                        SERVICE_TURN_ON,
                        service_data,
                        context=self._context,
                    )
                )
            )
        if tasks:
            await asyncio.wait(tasks)
