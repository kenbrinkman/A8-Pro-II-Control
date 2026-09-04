"""Polling coordinator + the in-memory light model.

The fixture does not report its live output (`read=config` returns the *stored*
levels). So this coordinator owns the model of what the light is doing:

  effective[ch] = setpoint[ch] * master_pct / 100   (0 when the master is off)

Channel entities edit `setpoint`, the master entity edits `master_pct` /
`master_on`, and both call `push_*` to send the effective values to the light.
Entities restore their last state on HA restart and write it back in here.
"""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import A8Client, A8Config, A8ConnectionError, A8Error, channel_names
from .const import CHANNEL_KEYS, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

A8ConfigEntry = ConfigEntry["A8Coordinator"]


class A8Coordinator(DataUpdateCoordinator[A8Config]):
    """Polls read=config and holds the channel model."""

    config_entry: A8ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: A8ConfigEntry,
        client: A8Client,
        initial: A8Config,
        serial: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.serial = serial
        self.channels = initial.channels
        self.model = initial.model
        self.keys: tuple[str, ...] = CHANNEL_KEYS[: self.channels]
        self.names: tuple[str, ...] = channel_names(initial.model, self.channels)

        # Model of the light's live output. Seeded from the stored config so a
        # fresh install starts in agreement with the fixture.
        self.setpoint: dict[str, int] = {
            k: initial.levels_pct[i] for i, k in enumerate(self.keys)
        }
        self.last_nonzero: dict[str, int] = {
            k: (v if v > 0 else 50) for k, v in self.setpoint.items()
        }
        self.master_pct: int = 100
        self.master_on: bool = True
        self.data = initial
        self._offline = False

    # ---- model -----------------------------------------------------------

    def effective_pct(self, key: str) -> int:
        if not self.master_on:
            return 0
        return int(round(self.setpoint[key] * self.master_pct / 100))

    # ---- writes ----------------------------------------------------------

    async def push_channel(self, key: str) -> None:
        """Send one channel's effective level."""
        try:
            await self.client.set_channel_pct(key, self.effective_pct(key))
        except A8Error as err:
            raise UpdateFailed(f"set {key} failed: {err}") from err
        self.async_update_listeners()

    async def push_all(self) -> None:
        """Send every channel's effective level (master changes, sync)."""
        try:
            await self.client.set_channels_pct(
                {k: self.effective_pct(k) for k in self.keys}
            )
        except A8Error as err:
            raise UpdateFailed(f"set all failed: {err}") from err
        self.async_update_listeners()

    async def set_channel(self, key: str, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        self.setpoint[key] = pct
        if pct > 0:
            self.last_nonzero[key] = pct
        await self.push_channel(key)

    async def channel_on(self, key: str) -> None:
        await self.set_channel(key, self.last_nonzero[key])

    async def channel_off(self, key: str) -> None:
        await self.set_channel(key, 0)

    async def set_master(self, pct: int | None = None, on: bool | None = None) -> None:
        if pct is not None:
            self.master_pct = max(0, min(100, int(pct)))
        if on is not None:
            self.master_on = on
        await self.push_all()

    # ---- polling ---------------------------------------------------------

    async def _async_update_data(self) -> A8Config:
        try:
            cfg = await self.client.get_config()
        except A8ConnectionError as err:
            self._offline = True
            raise UpdateFailed(f"{self.client.host} unreachable: {err}") from err
        except A8Error as err:
            # The firmware occasionally answers "A+" instead of a config string.
            # The light is clearly alive, so keep the last good data.
            _LOGGER.debug("%s: transient non-config reply (%s), keeping last data", self.client.host, err)
            return self.data

        if self._offline:
            # The fixture was unreachable and is back: it has almost certainly
            # rebooted, and a rebooted A8 comes up at its *stored* levels
            # (factory: everything 50 %, switch on). Re-assert what HA believes.
            self._offline = False
            _LOGGER.info("%s back online; re-sending channel levels", self.client.host)
            try:
                await self.client.set_channels_pct(
                    {k: self.effective_pct(k) for k in self.keys}
                )
            except A8Error as err:
                _LOGGER.warning("%s: re-send after reconnect failed: %s", self.client.host, err)
        return cfg
