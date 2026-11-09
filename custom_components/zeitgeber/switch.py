"""
Zeitgeber Switch for Home-Assistant.
"""

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import ZeitgeberEntity

if TYPE_CHECKING:
    from . import ZeitgeberCoordinator

_LOGGER = logging.getLogger(__name__)

ICON = "mdi:theme-light-dark"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ZeitgeberCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Zeitgeber sensor."""
    switch = ZeitgeberSwitch(entry.runtime_data)
    async_add_entities([switch])


class ZeitgeberSwitch(  # pyright: ignore[reportIncompatibleVariableOverride]
    SwitchEntity, RestoreEntity, ZeitgeberEntity
):
    """Representation of a Zeitgeber switch."""

    def __init__(self, coordinator: ZeitgeberCoordinator) -> None:
        """Initialize the Zeitgeber switch."""
        super().__init__(coordinator)
        self._attr_icon = ICON
        self._attr_name = "switch"
        self._attr_unique_id = f"{coordinator.config_entry.data["uuid"][-4:]}_switch"

    async def async_turn_on(self, **kwargs):
        """Turn on zeitgeber."""
        self.coordinator.enabled = True

    async def async_turn_off(self, **kwargs):
        """Turn off zeitgeber."""
        self.coordinator.enabled = False

    @property
    def is_on(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        return self.coordinator.enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self.coordinator.enabled = last_state.state == "on"
