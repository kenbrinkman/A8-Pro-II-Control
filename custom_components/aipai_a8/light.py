"""Light entities: one per LED channel, plus a master for the whole fixture.

All lights are assumed-state: the fixture cannot report its live output, so
Home Assistant is the source of truth. State survives restarts via RestoreEntity.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import ATTR_RAW
from .api import pct_to_raw
from .coordinator import A8ConfigEntry, A8Coordinator
from .entity import A8Entity

_LOGGER = logging.getLogger(__name__)


def _pct_to_brightness(pct: int) -> int:
    return int(round(pct * 255 / 100))


def _brightness_to_pct(b: int) -> int:
    return int(round(b * 100 / 255))


async def async_setup_entry(
    hass: HomeAssistant, entry: A8ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[LightEntity] = [A8MasterLight(coordinator)]
    entities += [
        A8ChannelLight(coordinator, key, name)
        for key, name in zip(coordinator.keys, coordinator.names, strict=True)
    ]
    async_add_entities(entities)


class _A8LightBase(A8Entity, LightEntity, RestoreEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_assumed_state = True


class A8ChannelLight(_A8LightBase):
    """One LED channel (e.g. Deep Blue)."""

    def __init__(self, coordinator: A8Coordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.serial}_{key}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in ("unknown", "unavailable"):
            return  # keep the value seeded from the fixture's stored config
        co = self.coordinator
        if last.state == "off":
            co.setpoint[self._key] = 0
        else:
            b = last.attributes.get(ATTR_BRIGHTNESS)
            if b is not None:
                pct = _brightness_to_pct(int(b))
                co.setpoint[self._key] = pct
                if pct > 0:
                    co.last_nonzero[self._key] = pct

    @property
    def is_on(self) -> bool:
        return self.coordinator.setpoint[self._key] > 0

    @property
    def brightness(self) -> int:
        return _pct_to_brightness(self.coordinator.setpoint[self._key])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        co = self.coordinator
        return {
            "channel": self._key,
            "setpoint_pct": co.setpoint[self._key],
            "effective_pct": co.effective_pct(self._key),
            ATTR_RAW: pct_to_raw(co.effective_pct(self._key)),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        co = self.coordinator
        if ATTR_BRIGHTNESS in kwargs:
            await co.set_channel(self._key, _brightness_to_pct(kwargs[ATTR_BRIGHTNESS]))
        else:
            await co.channel_on(self._key)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.channel_off(self._key)
        self.async_write_ha_state()


class A8MasterLight(_A8LightBase):
    """Whole-fixture on/off and proportional intensity (like the app's slider)."""

    _attr_name = "Master"
    _attr_translation_key = "master"

    def __init__(self, coordinator: A8Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_master"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in ("unknown", "unavailable"):
            return
        co = self.coordinator
        co.master_on = last.state == "on"
        b = last.attributes.get(ATTR_BRIGHTNESS)
        if b is not None:
            co.master_pct = max(1, _brightness_to_pct(int(b)))

    @property
    def is_on(self) -> bool:
        return self.coordinator.master_on

    @property
    def brightness(self) -> int:
        return _pct_to_brightness(self.coordinator.master_pct)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        co = self.coordinator
        return {
            "master_pct": co.master_pct,
            "channels": {k: co.effective_pct(k) for k in co.keys},
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        pct = None
        if ATTR_BRIGHTNESS in kwargs:
            pct = max(1, _brightness_to_pct(kwargs[ATTR_BRIGHTNESS]))
        await self.coordinator.set_master(pct=pct, on=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_master(on=False)
        self.async_write_ha_state()
