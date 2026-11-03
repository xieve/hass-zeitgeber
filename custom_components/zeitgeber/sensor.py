"""
Zeitgeber Sensor for Home-Assistant.
"""

from functools import cached_property
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.components.sensor import SensorEntity
from .entity import ZeitgeberEntity

from . import ZeitgeberCoordinator

ICON = "mdi:theme-light-dark"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ZeitgeberCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Zeitgeber sensor."""
    sensor = ZeitgeberSensor(entry.runtime_data)
    async_add_entities([sensor])


class ZeitgeberSensor(SensorEntity, ZeitgeberEntity):
    """Representation of a Zeitgeber sensor."""

    def __init__(self, coordinator: ZeitgeberCoordinator) -> None:
        """Initialize the Zeitgeber sensor."""
        super().__init__(coordinator)
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = ICON
        self._attr_name = "sensor"
        assert coordinator.config_entry is not None
        self._attr_unique_id = f"{coordinator.config_entry.data["uuid"][-4:]}_sensor"

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data.light_state is None:
            return None
        return self.coordinator.data.light_state.brightness

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes of the sensor."""
        light_state = self.coordinator.data.light_state
        if not light_state:
            return {}
        return {
            "brightness": light_state.brightness,
            "color_temp_kelvin": light_state.temperature,
            "rgb_color": light_state.rgb,
            "xy_color": light_state.xy,
            "hs_color": light_state.hs,
        }

    @callback
    def _update_callback(self) -> None:
        """Triggers update of properties."""
        self.async_schedule_update_ha_state(force_refresh=False)
