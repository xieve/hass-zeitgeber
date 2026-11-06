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

from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.const import Platform
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers.event import (
    async_track_point_in_time,
)
from packaging import version

from .calculate import ZeitgeberData, calculate_state

from .const import DOMAIN

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
    """Set up the zeitgeber platform."""
    coordinator = ZeitgeberCoordinator(
        hass,
        entry,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)


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
        )
        self.data = ZeitgeberData(None, {})

    @callback
    async def _async_update_data(self) -> ZeitgeberData:
        """Update zeitgeber data and schedule next update"""
        assert self.config_entry is not None
        (wake_next, self.data.light_state) = calculate_state(
            datetime.now(), self.config_entry.options, self.data.manual_config_times
        )

        async def refresh(*_):
            await self.async_refresh()

        if wake_next is None:
            self.update_interval = timedelta(minutes=1)
        else:
            async_track_point_in_time(self.hass, refresh, wake_next)

        return self.data
