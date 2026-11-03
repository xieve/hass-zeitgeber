from enum import StrEnum, auto
import logging
from typing import Any
from uuid import uuid4

from homeassistant.core import callback
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    FlowType,
    OptionsFlow,
)
from homeassistant.helpers.selector import NumberSelector, selector
from probatio import Required, Schema

from .const import Conf, DOMAIN

OPTIONS_SCHEMA = Schema(
    {
        Required(Conf.MANAGED_ENTITIES): selector(
            {
                "entity": {
                    "filter": {"domain": "light"},
                    "multiple": True,
                }
            }
        ),
        Required(Conf.DURATION, default={"minutes": 1}): selector({"duration": {}}),
        Required(Conf.MIN_COLOR_TEMP, default=2200): NumberSelector(
            {"min": 1000, "max": 10000}
        ),
        Required(Conf.MAX_COLOR_TEMP, default=2200): NumberSelector(
            {"min": 1000, "max": 10000}
        ),
        Required(Conf.MIN_BRIGHTNESS, default=1): NumberSelector(
            {"min": 1, "max": 100}
        ),
        Required(Conf.MAX_BRIGHTNESS, default=100): NumberSelector(
            {"min": 1, "max": 100}
        ),
    }
)
_LOGGER = logging.Logger(__file__)


class ZeitgeberConfigFlow(ConfigFlow, domain=DOMAIN):
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        _LOGGER.debug(user_input)
        return self.async_create_entry(title=DOMAIN, data={"uuid": str(uuid4())})

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        options_result = await self.hass.config_entries.options.async_init(
            result["result"].entry_id
        )
        result["next_flow"] = (FlowType.OPTIONS_FLOW, options_result["flow_id"])
        return result

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> ZeitgeberOptionsFlow:
        return ZeitgeberOptionsFlow()


class ZeitgeberOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
