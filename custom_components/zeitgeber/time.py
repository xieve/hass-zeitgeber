from datetime import time
import logging
import typing

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import STATE_UNKNOWN

from .calculate import SunEventsKey
from custom_components.zeitgeber.switch import RestoreEntity

from .entity import ZeitgeberEntity
from . import ZeitgeberCoordinator

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
        self._attr_unique_id = (
            f"{coordinator.config_entry.data["uuid"][-4:]}_{event}_time"
        )

    async def async_set_value(self, value: time) -> None:
        self._attr_native_value = value
        self.coordinator.data.manual_config_times[self._event] = value
        await self.coordinator.async_refresh()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state != STATE_UNKNOWN:
            await self.async_set_value(time.fromisoformat(last_state.state))
