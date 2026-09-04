"""AIPAI A8 reef light — local HTTP control, no cloud."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import time as dt_time
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import A8Client, A8Error, photoperiod_points, scale_points
from .const import (
    ATTR_FULL_DAY,
    ATTR_LEVELS,
    ATTR_NIGHT,
    ATTR_OFF,
    ATTR_PEAK,
    ATTR_RATIOS,
    ATTR_SUNRISE,
    ATTR_SUNSET,
    CHANNEL_KEYS,
    CONF_HOST,
    DEVICE_SPACING,
    DOMAIN,
    SERVICE_SET_MANUAL,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import A8ConfigEntry, A8Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

_PCT = vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
_CHANNEL_MAP = vol.Schema({vol.In(CHANNEL_KEYS): _PCT})

SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_SUNRISE): cv.time,
        vol.Required(ATTR_FULL_DAY): cv.time,
        vol.Required(ATTR_SUNSET): cv.time,
        vol.Required(ATTR_NIGHT): cv.time,
        vol.Optional(ATTR_PEAK, default=100): _PCT,
        vol.Optional(ATTR_RATIOS): _CHANNEL_MAP,
    }
)
SET_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_LEVELS): _CHANNEL_MAP,
        vol.Optional(ATTR_OFF, default=False): cv.boolean,
    }
)


def _minutes(t: dt_time) -> int:
    return t.hour * 60 + t.minute


def _coordinators_for(hass: HomeAssistant, device_ids: list[str]) -> list[A8Coordinator]:
    registry = dr.async_get(hass)
    out: list[A8Coordinator] = []
    for device_id in device_ids:
        device = registry.async_get(device_id)
        if device is None:
            raise ServiceValidationError(f"unknown device {device_id}")
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
                out.append(entry.runtime_data)
                break
        else:
            raise ServiceValidationError(f"device {device_id} is not a loaded AIPAI A8 light")
    return out


async def _apply_each(
    coordinators: list[A8Coordinator],
    action: Callable[[A8Coordinator], Awaitable[None]],
    what: str,
) -> None:
    """Run `action` against every fixture, then report the ones that failed.

    These services take a list of devices, and the obvious loop -- raise on the
    first error -- means one flaky fixture silently cancels the write for every
    fixture after it. That is what happened on 04 Sep 2026: a single stalled
    `read=config` on Light 1 aborted the whole photoperiod write, so all three
    stayed parked dark while the dashboard showed the schedule running. Every
    fixture is independent hardware; treat it that way. Same reasoning as the
    `continue_on_error` already on `script.reef_spectrum_apply`.

    Writes are spaced: three back-to-back configuration writes across fixtures
    sharing one 2.4 GHz radio is the pattern behind both the timeouts and the
    burst reboot.
    """
    failures: list[str] = []
    for i, coordinator in enumerate(coordinators):
        if i:
            await asyncio.sleep(DEVICE_SPACING)
        try:
            await action(coordinator)
        except Exception as err:  # noqa: BLE001 -- UpdateFailed and friends
            _LOGGER.error("%s: %s failed: %s", coordinator.client.host, what, err)
            failures.append(f"{coordinator.client.host}: {err}")
    if failures:
        raise HomeAssistantError(
            f"{what} failed on {len(failures)} of {len(coordinators)} lights -- "
            + "; ".join(failures)
        )


async def _svc_set_schedule(call: ServiceCall) -> None:
    hass = call.hass
    try:
        master = photoperiod_points(
            _minutes(call.data[ATTR_SUNRISE]),
            _minutes(call.data[ATTR_FULL_DAY]),
            _minutes(call.data[ATTR_SUNSET]),
            _minutes(call.data[ATTR_NIGHT]),
            call.data[ATTR_PEAK],
        )
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    ratios: dict[str, float] | None = call.data.get(ATTR_RATIOS)

    async def _one(coordinator: A8Coordinator) -> None:
        # Default ratios: HA's current channel set points (the spectrum the user dialled in).
        r = ratios if ratios is not None else {k: coordinator.setpoint[k] for k in coordinator.keys}
        points = {k: scale_points(master, r.get(k, 0)) for k in coordinator.keys}
        await coordinator.save_schedule(points)

    await _apply_each(_coordinators_for(hass, call.data["device_id"]), _one, "set_schedule")


async def _svc_set_manual(call: ServiceCall) -> None:
    hass = call.hass

    async def _one(coordinator: A8Coordinator) -> None:
        if call.data[ATTR_OFF]:
            levels: dict[str, int] | None = {k: 0 for k in coordinator.keys}
        elif ATTR_LEVELS in call.data:
            levels = {k: int(v) for k, v in call.data[ATTR_LEVELS].items()}
        else:
            levels = None
        await coordinator.save_manual(levels)

    await _apply_each(_coordinators_for(hass, call.data["device_id"]), _one, "set_manual")


async def async_setup_entry(hass: HomeAssistant, entry: A8ConfigEntry) -> bool:
    client = A8Client(entry.data[CONF_HOST], async_get_clientsession(hass))
    try:
        _, serial = await client.get_identity()
        initial = await client.get_config()
    except A8Error as err:
        raise ConfigEntryNotReady(f"{entry.data[CONF_HOST]}: {err}") from err

    serial = serial or initial.serial or entry.unique_id or entry.data[CONF_HOST]
    coordinator = A8Coordinator(hass, entry, client, initial, str(serial))
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, _svc_set_schedule, SET_SCHEDULE_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_SET_MANUAL, _svc_set_manual, SET_MANUAL_SCHEMA)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: A8ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
