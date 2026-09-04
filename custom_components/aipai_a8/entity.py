"""Shared base entity: attaches everything to one device per fixture."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import pretty_model
from .const import DOMAIN, MANUFACTURER
from .coordinator import A8Coordinator


def _device_name(model: str | None, serial: str | None) -> str:
    """Unique, stable device name: 'A8 Pro 3156988'."""
    base = pretty_model(model)
    return f"{base} {serial}" if serial else base


class A8Entity(CoordinatorEntity[A8Coordinator]):
    """Base for all entities of one fixture."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: A8Coordinator) -> None:
        super().__init__(coordinator)
        # The device name seeds every entity_id (has_entity_name = True), so it must be
        # unique per fixture: pretty_model() alone returns "A8 Pro" for every A8PRO6, and a
        # second fixture then collides into `_2`, a third into `_3`, in registration order
        # rather than in light order. Appending the serial keeps each fixture distinct at
        # birth. A user-assigned device name (name_by_user) still overrides this for display.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial)},
            name=_device_name(coordinator.model, coordinator.serial),
            manufacturer=MANUFACTURER,
            model=coordinator.model,
            serial_number=coordinator.serial,
            configuration_url=coordinator.client.base_url,
        )
