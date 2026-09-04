"""Sensors polled from read=config."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import A8Config
from .coordinator import A8ConfigEntry, A8Coordinator
from .entity import A8Entity


@dataclass(frozen=True, kw_only=True)
class A8SensorDescription(SensorEntityDescription):
    value_fn: Callable[[A8Config], float | int | str | None]


def _tz(tz: str | None) -> str | None:
    if not tz:
        return None
    return f"UTC{tz}" if tz.startswith(("-", "+")) else f"UTC+{tz}"


SENSORS: tuple[A8SensorDescription, ...] = (
    A8SensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda c: c.temperature,
    ),
    A8SensorDescription(
        key="mode",
        translation_key="mode",
        device_class=SensorDeviceClass.ENUM,
        options=["manual", "schedule"],
        value_fn=lambda c: "schedule" if c.mode == 1 else "manual",
    ),
    A8SensorDescription(
        key="clock",
        translation_key="clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.clock,
    ),
    A8SensorDescription(
        key="timezone",
        translation_key="timezone",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _tz(c.timezone),
    ),
    A8SensorDescription(
        key="fan_on",
        translation_key="fan_on",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.fan_on,
    ),
    A8SensorDescription(
        key="fan_off",
        translation_key="fan_off",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.fan_off,
    ),
    A8SensorDescription(
        key="thermal_cutoff",
        translation_key="thermal_cutoff",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.fan_cutoff,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: A8ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(A8Sensor(coordinator, d) for d in SENSORS)


class A8Sensor(A8Entity, SensorEntity):
    entity_description: A8SensorDescription

    def __init__(self, coordinator: A8Coordinator, description: A8SensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self.coordinator.data)
