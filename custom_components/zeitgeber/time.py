from datetime import time
import logging
from typing import TYPE_CHECKING, Optional, cast
import typing

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.zeitgeber.switch import RestoreEntity

from .entity import ZeitgeberEntity
from . import SunEventsKey, ZeitgeberCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ZeitgeberCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        ZeitgeberTime(entry.runtime_data, key)
        for key in typing.get_args(SunEventsKey.__value__)
    )


class ZeitgeberTime(TimeEntity, RestoreEntity, ZeitgeberEntity):
    def __init__(self, coordinator: ZeitgeberCoordinator, event: SunEventsKey) -> None:
        super().__init__(coordinator)
        self._event: SunEventsKey = event
        self._attr_name = event
        assert coordinator.config_entry is not None
        self._attr_unique_id = (
            f"{coordinator.config_entry.data["uuid"][-4:]}_{event}_time"
        )
        _LOGGER.debug(self._attr_unique_id)

    async def async_set_value(self, value: time) -> None:
        self._attr_native_value = value
        _LOGGER.debug(value)
        _LOGGER.debug(self.native_value)
        _LOGGER.debug(self.state)
        self.coordinator.data.manual_config_times[self._event] = value
        await self.coordinator.async_refresh()
