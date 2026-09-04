"""Diagnostics: does the fixture agree with Home Assistant?

The lights are `assumed_state` -- they cannot report their live output, so HA
owns the model and nothing checks it. That is fine right up until the two
diverge, and then HA reports a confident wrong value, which is worse than
reporting nothing (the same lesson as the zeroed-temperature spike in v0.2.1).

There is one readback that *is* trustworthy: `read=config` returns the levels
stored in flash, and in manual mode those are exactly what the firmware
re-applies on its own timer and after a reboot. Comparing them against what HA
believes it is sending turns an invisible failure into an entity.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import A8ConfigEntry, A8Coordinator
from .entity import A8Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: A8ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([A8StoredMismatch(entry.runtime_data)])


class A8StoredMismatch(A8Entity, BinarySensorEntity):
    """On when the fixture's saved configuration contradicts HA's model.

    Expect this to come on the moment a master or channel slider is moved in
    manual mode -- that is not a false positive, it is the finding: a live set
    never reaches flash, so the fixture will revert to the stored levels at its
    next re-apply. It clears when a `save=` puts the two back in agreement
    (`aipai_a8.set_manual`, `aipai_a8.set_schedule`), and reads off in schedule
    mode, where the fixture is running its own stored curve and HA's live model
    does not apply.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "stored_mismatch"

    def __init__(self, coordinator: A8Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_stored_mismatch"

    @property
    def is_on(self) -> bool | None:
        diff = self.coordinator.level_mismatch()
        if diff is None:
            return None  # schedule mode, or nothing polled yet: not applicable
        return bool(diff)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        co = self.coordinator
        mode = None if co.data is None else ("schedule" if co.data.mode == 1 else "manual")
        attrs: dict[str, Any] = {
            "mode": mode,
            "believed_pct": co.believed_levels(),
            "stored_pct": co.stored_levels(),
        }
        diff = co.level_mismatch()
        if diff:
            attrs["differing_channels"] = sorted(diff)
            attrs["worst_gap_pct"] = max(abs(b - s) for b, s in diff.values())
        return attrs
