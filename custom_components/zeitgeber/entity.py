from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

from . import ZeitgeberCoordinator


class ZeitgeberEntity(CoordinatorEntity[ZeitgeberCoordinator]):
    """Base class for zeitgeber entities"""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZeitgeberCoordinator) -> None:
        super().__init__(coordinator)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.config_entry.data["uuid"]))},
            name="zeitgeber",
        )
