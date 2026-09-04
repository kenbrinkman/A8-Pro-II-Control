"""Buttons: push HA's levels to the light, sync the light's clock.

Deliberately absent: factory reset, OTA update, reboot. Those exist in the
protocol and can brick a fixture; they will not be exposed here.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
        # push_all() is a deliberate no-op in schedule mode. Say so rather than
        # letting the button look like it worked.
        if not self.coordinator._live_sets_reach_the_led():
            raise HomeAssistantError(
                f"{self.coordinator.client.host} is in schedule mode and ignores live "
                "levels. Switch it to manual (aipai_a8.set_manual) first."
            )
        await self.coordinator.push_all()


class A8SyncClockButton(A8Entity, ButtonEntity):
    """Set the fixture clock from the HA host clock (fixture applies its own timezone)."""

    _attr_translation_key = "sync_clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: A8Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_sync_clock"

    async def async_press(self) -> None:
        await self.coordinator.sync_clock()
