"""Buttons: push HA's levels to the light, sync the light's clock.

Deliberately absent: factory reset, OTA update, reboot. Those exist in the
protocol and can brick a fixture; they will not be exposed here.
"""

from __future__ import annotations

import time

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import A8ConfigEntry, A8Coordinator
from .entity import A8Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: A8ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([A8PushLevelsButton(coordinator), A8SyncClockButton(coordinator)])


class A8PushLevelsButton(A8Entity, ButtonEntity):
    """Resend every channel's current level. Use after the fixture lost power."""

    _attr_translation_key = "push_levels"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: A8Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_push_levels"

    async def async_press(self) -> None:
        await self.coordinator.push_all()


class A8SyncClockButton(A8Entity, ButtonEntity):
    """Set the fixture clock from the HA host clock (fixture applies its own timezone)."""

    _attr_translation_key = "sync_clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: A8Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_sync_clock"

    async def async_press(self) -> None:
        await self.coordinator.client.set_clock(int(time.time()))
        await self.coordinator.async_request_refresh()
