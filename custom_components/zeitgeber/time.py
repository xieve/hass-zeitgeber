from datetime import time
from typing import TYPE_CHECKING, Optional, cast
import typing

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZEITGEBER_UPDATE_TOPIC, DOMAIN

if TYPE_CHECKING:
    from . import Zeitgeber, SunEventsKey


def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
):
    zeitgeber = cast(Optional[Zeitgeber], hass.data.get(DOMAIN))
    if zeitgeber is not None:
        async_add_entities(
            ZeitgeberTime(zeitgeber, key)
            for key in typing.get_args(SunEventsKey)
        )


class ZeitgeberTime(TimeEntity):
    def __init__(
        self, zeitgeber: Zeitgeber, event: SunEventsKey
    ) -> None:
        super().__init__()
        self._zeitgeber: Zeitgeber = zeitgeber
        self._event: SunEventsKey = event

    async def async_set_value(self, value: time) -> None:
        self._zeitgeber._manual_config_times[self._event] = value
