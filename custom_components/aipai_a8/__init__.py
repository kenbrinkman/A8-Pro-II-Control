"""AIPAI A8 reef light — local HTTP control, no cloud."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import A8Client, A8Error
from .const import CONF_HOST
from .coordinator import A8ConfigEntry, A8Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SENSOR, Platform.BUTTON]


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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: A8ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
