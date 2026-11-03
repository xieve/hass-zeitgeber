from datetime import time
from typing import TYPE_CHECKING, Optional, cast
import typing

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.circadian_lighting import CircadianLighting

from . import CIRCADIAN_LIGHTING_UPDATE_TOPIC, DOMAIN

if TYPE_CHECKING:
    from . import CircadianLighting, SunEventsKey


def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
):
    circadian_lighting = cast(Optional[CircadianLighting], hass.data.get(DOMAIN))
    if circadian_lighting is not None:
        async_add_entities(
            CircadianTime(circadian_lighting, key)
            for key in typing.get_args(SunEventsKey)
        )


class CircadianTime(TimeEntity):
    def __init__(
        self, circadian_lighting: CircadianLighting, event: SunEventsKey
    ) -> None:
        super().__init__()
        self._circadian_lighting: CircadianLighting = circadian_lighting
        self._event: SunEventsKey = event

    async def async_set_value(self, value: time) -> None:
        self._circadian_lighting._manual_config_times[self._event] = value
