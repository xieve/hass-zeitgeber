"""
Zeitgeber Switch for Home-Assistant.
"""

import asyncio
from datetime import timedelta
from functools import cached_property
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.light import is_on
from homeassistant.components.light.const import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    ATTR_HS_COLOR,
)
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_ON,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity

from .const import Conf

from .entity import ZeitgeberEntity

from . import ZeitgeberCoordinator

_LOGGER = logging.getLogger(__name__)

ICON = "mdi:theme-light-dark"

CONF_LIGHTS_CT = "lights_ct"
CONF_LIGHTS_RGB = "lights_rgb"
CONF_LIGHTS_XY = "lights_xy"
CONF_LIGHTS_BRIGHT = "lights_brightness"
CONF_DISABLE_BRIGHTNESS_ADJUST = "disable_brightness_adjust"
CONF_SLEEP_ENTITY = "sleep_entity"
CONF_SLEEP_STATE = "sleep_state"
CONF_SLEEP_CT, DEFAULT_SLEEP_CT = "sleep_colortemp", 1000
CONF_SLEEP_BRIGHT, DEFAULT_SLEEP_BRIGHT = "sleep_brightness", 1
CONF_DISABLE_ENTITY = "disable_entity"
CONF_DISABLE_STATE = "disable_state"
CONF_INITIAL_TRANSITION, DEFAULT_INITIAL_TRANSITION = "initial_transition", 1
CONF_ONLY_ONCE = "only_once"
SLEEP_INCLUSIVE_MSG = f"{CONF_SLEEP_ENTITY} and {CONF_SLEEP_STATE} must be set together"
DISABLE_INCLUSIVE_MSG = (
    f"{CONF_DISABLE_ENTITY} and {CONF_DISABLE_STATE} must be set together"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ZeitgeberCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Zeitgeber sensor."""
    switch = ZeitgeberSwitch(entry.runtime_data)
    async_add_entities([switch])


def _difference_between_states(from_state, to_state):
    start = "Lights adjusting because "
    if from_state is None and to_state is None:
        return start + "both states None"
    if from_state is None:
        return start + f"from_state: None, to_state: {to_state}"
    if to_state is None:
        return start + f"from_state: {from_state}, to_state: None"

    changed_attrs = ", ".join(
        [
            f"{key}: {val}"
            for key, val in to_state.attributes.items()
            if from_state.attributes.get(key) != val
        ]
    )
    if from_state.state == to_state.state:
        return start + (
            f"{from_state.entity_id} is still {to_state.state} but"
            f" these attributes changes: {changed_attrs}."
        )
    elif changed_attrs != "":
        return start + (
            f"{from_state.entity_id} changed from {from_state.state} to"
            f" {to_state.state} and these attributes changes: {changed_attrs}."
        )
    else:
        return start + (
            f"{from_state.entity_id} changed from {from_state.state} to"
            f" {to_state.state} and no attributes changed."
        )


class ZeitgeberSwitch(  # pyright: ignore[reportIncompatibleVariableOverride]
    SwitchEntity, RestoreEntity, ZeitgeberEntity
):
    """Representation of a Zeitgeber switch."""

    def __init__(self, coordinator: ZeitgeberCoordinator) -> None:
        """Initialize the Zeitgeber switch."""
        super().__init__(coordinator)
        self._attr_icon = ICON
        self._attr_name = "switch"
        assert coordinator.config_entry is not None
        self._attr_unique_id = f"{coordinator.config_entry.data["uuid"][-4:]}_switch"

    @cached_property
    def extra_state_attributes(
        self,
    ) -> dict[str, Any]:
        """Return the attributes of the switch."""
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

    async def async_turn_on(self, **kwargs):
        """Turn on zeitgeber."""
        self._attr_is_on = True
        await self._adjust_lights()

    async def async_turn_off(self, **kwargs):
        """Turn off zeitgeber."""
        self._attr_is_on = False

    def _handle_coordinator_update(self) -> None:
        _LOGGER.debug("received update")
        self.hass.add_job(self._adjust_lights)
        return super()._handle_coordinator_update()

    async def _adjust_lights(self, lights=None, transition=None):
        if not self.is_on:
            return

        if transition is None:
            transition = (
                self.coordinator.update_interval or timedelta(minutes=1)
            ).seconds

        config_entry = self.coordinator.config_entry
        assert config_entry is not None

        light_state = self.coordinator.data.light_state
        if light_state is None:
            _LOGGER.warning("No light state")
            return

        lights = lights or config_entry.options[Conf.MANAGED_ENTITIES]

        tasks = []
        for light in lights:
            entity = self.hass.states.get(light)
            if entity is None:
                _LOGGER.warning(f"Entity {light} does not exist")
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
                    _LOGGER.info(
                        f"{light} does not have any supported color mode, only setting "
                        "brightness."
                    )

            _LOGGER.debug(
                "Scheduling 'light.turn_on' with the following 'service_data': %s",
                service_data,
            )
            tasks.append(
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        LIGHT_DOMAIN, SERVICE_TURN_ON, service_data
                    )
                )
            )
        if tasks:
            await asyncio.wait(tasks)

    async def _light_state_changed(self, event: Event[EventStateChangedData]):
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]

        if not new_state or new_state.state != "on":
            _LOGGER.debug(
                "Ignoring state change for %s: new state is %s",
                entity_id,
                new_state.state if new_state else "None",
            )
            return  # Exit early if new_state is None or not "on"

        if old_state is None or old_state.state != "on":
            _LOGGER.debug(_difference_between_states(old_state, new_state))
            await self._adjust_lights(lights=[entity_id])

    async def _state_changed(self, event: Event[EventStateChangedData]):
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]

        _LOGGER.debug(_difference_between_states(old_state, new_state))
        await self._adjust_lights()
