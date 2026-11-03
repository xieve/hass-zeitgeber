"""
Zeitgeber Sensor for Home-Assistant.
"""

from typing import TYPE_CHECKING, Optional, cast

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType

from . import ZEITGEBER_UPDATE_TOPIC, DOMAIN

if TYPE_CHECKING:
    from . import Zeitgeber

ICON = "mdi:theme-light-dark"


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info=None,
) -> None:
    """Set up the Zeitgeber sensor."""
    zeitgeber = cast(Optional[Zeitgeber], hass.data.get(DOMAIN))
    if zeitgeber is not None:
        sensor = ZeitgeberSensor(hass, zeitgeber)
        async_add_entities([sensor])

        async def async_update(call=None) -> None:
            """Update component."""
            await zeitgeber.async_loop()

        service_name = "values_update"
        hass.services.async_register(DOMAIN, service_name, async_update)


class ZeitgeberSensor(Entity):
    """Representation of a Zeitgeber sensor."""

    def __init__(self, hass, zeitgeber):
        """Initialize the Zeitgeber sensor."""
        self._zeitgeber: Zeitgeber = zeitgeber
        self._name = "Zeitgeber Values"
        self._entity_id = "sensor.zeitgeber_values"
        self._unit_of_measurement = "%"
        self._icon = ICON

    @property
    def entity_id(self):
        """Return the entity ID of the sensor."""
        return self._entity_id

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._zeitgeber._brightness

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self._icon

    @property
    def hs_color(self):
        return self._zeitgeber._hs_color

    @property
    def extra_state_attributes(self):
        """Return the attributes of the sensor."""
        return {
            "colortemp": self._zeitgeber._colortemp,
            "rgb_color": self._zeitgeber._rgb_color,
            "xy_color": self._zeitgeber._xy_color,
        }

    @property
    def should_poll(self) -> bool:
        """Disable polling."""
        return False

    async def async_added_to_hass(self) -> None:
        """Connect dispatcher to signal from Zeitgeber object."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, ZEITGEBER_UPDATE_TOPIC, self._update_callback
            )
        )

    @callback
    def _update_callback(self) -> None:
        """Triggers update of properties."""
        self.async_schedule_update_ha_state(force_refresh=False)
