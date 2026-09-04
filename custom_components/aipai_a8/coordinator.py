"""Polling coordinator + the in-memory light model.

The fixture does not report its live output (`read=config` returns the *stored*
levels). So this coordinator owns the model of what the light is doing:

  effective[ch] = setpoint[ch] * master_pct / 100   (0 when the master is off)

Channel entities edit `setpoint`, the master entity edits `master_pct` /
`master_on`, and both call `push_*` to send the effective values to the light.
Entities restore their last state on HA restart and write it back in here.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    A8Client,
    A8Config,
    A8ConnectionError,
    A8Error,
    blob_from_config,
    channel_names,
    tz_string,
)
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

    # ---- persistence (save= — flash writes, use sparingly) ----------------

    def _local_tz(self) -> str:
        offset = dt_util.now().utcoffset()
        return tz_string(offset.total_seconds() if offset else 0)

    async def _save(self, **overrides) -> None:
        """Rebuild the stored config from a fresh read=config, apply overrides, save.

        Reading first preserves what we don't manage (fan thresholds, timers).
        The fixture applies its timezone to the clock only when the clock is
        (re)sent, so the clock is always re-sent after a save.
        """
        try:
            cfg = await self.client.get_config()
        except A8Error as err:
            raise UpdateFailed(f"{self.client.host}: read before save failed: {err}") from err
        overrides.setdefault("timezone", self._local_tz())
        blob = blob_from_config(cfg, **overrides)
        try:
            await self.client.save_config(blob)
            await self.client.set_clock(int(time.time()))
        except A8Error as err:
            raise UpdateFailed(f"{self.client.host}: save failed: {err}") from err
        _LOGGER.info(
            "%s: saved mode=%s tz=%s", self.client.host, overrides.get("mode", cfg.mode), overrides["timezone"]
        )
        await self.async_request_refresh()

    async def save_schedule(self, points: dict[str, list[int]]) -> None:
        """Store a 24-point curve per channel and put the fixture in schedule mode.

        The fixture then runs the photoperiod itself (survives reboots, no
        polling needed). Channels not in `points` get a flat zero row.
        """
        rows = [list(points.get(k, [0] * 24)) for k in self.keys]
        await self._save(mode=1, schedule=rows)

    async def save_manual(self, levels: dict[str, int] | None = None) -> None:
        """Put the fixture in manual mode with these stored levels.

        `levels` omitted = HA's current effective levels (what the LEDs are
        doing now). All zeros = parked dark; the fixture stays dark through
        reboots and its own re-apply cycle.
        """
        if levels is None:
            levels = {k: self.effective_pct(k) for k in self.keys}
        lv = [int(levels.get(k, 0)) for k in self.keys]
        await self._save(mode=0, levels_pct=lv)

    async def sync_clock(self) -> None:
        await self.client.set_clock(int(time.time()))
        await self.async_request_refresh()

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

        # A reply that parses but carries the wrong serial is a misaligned or
        # half-written answer, not this fixture. Keep the last good data.
        if cfg.serial and self.serial and cfg.serial != self.serial:
            _LOGGER.debug(
                "%s: config reply has serial %s, expected %s; keeping last data",
                self.client.host, cfg.serial, self.serial,
            )
            return self.data

        # A dropped temperature reading (see _plausible_temp) should not blank
        # the sensor or land in history as a spike -- hold the previous value.
        if cfg.temperature is None and self.data is not None and self.data.temperature is not None:
            cfg = replace(cfg, temperature=self.data.temperature)

        if self._offline:
            # The fixture was unreachable and is back: it has almost certainly
            # rebooted, and a rebooted A8 comes up at its *stored* levels
            # (factory: everything 50 %, switch on). Re-assert what HA believes —
            # unless it is running its own stored schedule, which is exactly
            # what we want after a reboot.
            self._offline = False
            if cfg.mode == 1:
                return cfg
            _LOGGER.info("%s back online; re-sending channel levels", self.client.host)
            try:
                await self.client.set_channels_pct(
                    {k: self.effective_pct(k) for k in self.keys}
                )
            except A8Error as err:
                _LOGGER.warning("%s: re-send after reconnect failed: %s", self.client.host, err)
        return cfg
