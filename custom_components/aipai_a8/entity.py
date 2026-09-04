"""Shared base entity: attaches everything to one device per fixture."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import pretty_model
from .const import DOMAIN, MANUFACTURER
from .coordinator import A8Coordinator


class A8Entity(CoordinatorEntity[A8Coordinator]):
    """Base for all entities of one fixture."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: A8Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial)},
            name=pretty_model(coordinator.model),
            manufacturer=MANUFACTURER,
            model=coordinator.model,
            serial_number=coordinator.serial,
            configuration_url=coordinator.client.base_url,
        )
