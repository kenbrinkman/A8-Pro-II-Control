"""Local HTTP client for AIPAI A8 reef lights.

Protocol reference: https://github.com/kenbrinkman/A8-Pro-II-Control

Every command is `GET http://<ip>/?key=value`. The firmware answers a live
channel set with the literal string "A+". `read=config` returns a
`|`-delimited string; `sta=getip` returns "<ip>,<serial>,<flag>".

This module has no Home Assistant imports so it can be unit-tested directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging

import aiohttp

from .const import (
    CHANNEL_KEYS,
    CHANNEL_NAMES_BLUE,
    CHANNEL_NAMES_HP,
    CHANNEL_NAMES_STANDARD,
    RAW_MAX,
    REQUEST_TIMEOUT,
    WRITE_SPACING,
)

_LOGGER = logging.getLogger(__name__)


class A8Error(Exception):
    """Base error."""


class A8ConnectionError(A8Error):
    """Light unreachable."""


class A8ProtocolError(A8Error):
    """Light answered, but not with what we expected."""


@dataclass
class A8Config:
    """Decoded `read=config` reply."""

    raw: str
    channels: int
    switch: str  # "on" / "off"
    mode: int  # 0 manual, 1 schedule
    fan_on: float | None
    fan_off: float | None
    fan_cutoff: float | None
    levels_pct: list[int]  # stored level per channel, 0-100 (NOT live output)
    schedule: list[str]  # 24 comma-separated points per channel
    temperature: float | None
    clock: str | None  # "HH:MM"
    timer_on: int | None
    timer_off: int | None
    serial: str | None
    timezone: str | None
    model: str | None
    field_count: int = field(default=0)


def _f(fields: list[str], i: int) -> str | None:
    return fields[i] if i < len(fields) else None


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _int(v: str | None) -> int | None:
    fv = _float(v)
    return int(fv) if fv is not None else None


def parse_config(raw: str) -> A8Config:
    """Decode the `read=config` reply.

    Layout (n = channel count, d = 2*(n-6)), as read by the vendor app:
      [0] switch  [1] mode  [2..4] fan-on / fan-off / cutoff
      [5 .. 5+n-1]      stored level per channel, percent
      [5+n .. 5+2n-1]   24-point schedule per channel, percent
      [17+d] temperature  [18+d] clock "H,M"  [19+d] timer-on  [20+d] timer-off
      [21+d] serial  [22+d] knob flag  [23+d] timezone  [24+d] model
    """
    if not raw or "|" not in raw:
        raise A8ProtocolError(f"not a config string: {raw[:40]!r}")
    f = [x.strip() for x in raw.split("|")]
    n = 8 if len(f) > 28 else 6
    d = 2 * (n - 6)

    levels: list[int] = []
    for i in range(n):
        v = _int(_f(f, 5 + i))
        levels.append(max(0, min(100, v if v is not None else 0)))
    schedule = [(_f(f, 5 + n + i) or "") for i in range(n)]

    clock = None
    clock_raw = _f(f, 18 + d)
    if clock_raw and "," in clock_raw:
        h, m = clock_raw.split(",", 1)
        hi, mi = _int(h), _int(m)
        if hi is not None and mi is not None:
            clock = f"{hi:02d}:{mi:02d}"

    return A8Config(
        raw=raw,
        channels=n,
        switch=f[0],
        mode=_int(f[1]) or 0,
        fan_on=_float(_f(f, 2)),
        fan_off=_float(_f(f, 3)),
        fan_cutoff=_float(_f(f, 4)),
        levels_pct=levels,
        schedule=schedule,
        temperature=_float(_f(f, 17 + d)),
        clock=clock,
        timer_on=_int(_f(f, 19 + d)),
        timer_off=_int(_f(f, 20 + d)),
        serial=_f(f, 21 + d) or None,
        timezone=_f(f, 23 + d) or None,
        model=_f(f, 24 + d) or None,
        field_count=len(f),
    )


def channel_names(model: str | None, channels: int) -> tuple[str, ...]:
    """Pick the human channel names for a model string like 'A8PRO6' or 'A8-PROB9'."""
    m = (model or "").upper().replace("-", "")
    if m.startswith("A8HP"):
        return CHANNEL_NAMES_HP[:channels]
    # B-suffixed: A8SEB, A8PROB, A8SEB9, A8PROB9
    if m.startswith(("A8SEB", "A8PROB")):
        return CHANNEL_NAMES_BLUE[:channels]
    return CHANNEL_NAMES_STANDARD[:channels]


def pretty_model(model: str | None) -> str:
    """'A8PRO6' -> 'A8 Pro', 'A8PROB9' -> 'A8 Pro Blue Moon', 'A8SE8' -> 'A8 SE'."""
    m = (model or "").upper().replace("-", "")
    if not m.startswith(("A8", "A7")):
        return model or "A8 Reef Light"
    series = m[:2]
    rest = m[2:]
    fam = ""
    for cand, label in (("PRO", "Pro"), ("SE", "SE"), ("HP", "HP"), ("X", "X"), ("S", "S"), ("P", "P")):
        if rest.startswith(cand):
            fam = label
            rest = rest[len(cand):]
            break
    parts = [series, fam] if fam else [series]
    if "B" in rest:
        parts.append("Blue")
    if rest.endswith("9"):
        parts.append("Moon")
    return " ".join(parts)


def pct_to_raw(pct: float) -> int:
    """0-100 % -> 0-1023, same rounding as the vendor app."""
    pct = max(0.0, min(100.0, float(pct)))
    return int(round(RAW_MAX * pct / 100))


class A8Client:
    """Async HTTP client for one fixture."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        self._host = host
        self._session = session
        self._lock = asyncio.Lock()  # the firmware's HTTP server is single-threaded

    @property
    def host(self) -> str:
        return self._host

    @property
    def base_url(self) -> str:
        return f"http://{self._host}/"

    async def _get(self, query: str) -> str:
        url = f"{self.base_url}?{query}"
        async with self._lock:
            try:
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
                ) as resp:
                    text = await resp.text(errors="replace")
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
                raise A8ConnectionError(f"{url}: {err}") from err
        text = text.strip()
        _LOGGER.debug("%s -> %r", url, text[:120])
        return text

    async def get_identity(self) -> tuple[str, str | None]:
        """`sta=getip` -> (ip, serial)."""
        text = await self._get("sta=getip")
        if "," not in text:
            raise A8ProtocolError(f"unexpected sta=getip reply: {text[:40]!r}")
        parts = [p.strip() for p in text.split(",")]
        return parts[0], (parts[1] if len(parts) > 1 and parts[1] else None)

    async def get_config(self) -> A8Config:
        """`read=config` decoded."""
        text = await self._get("read=config")
        return parse_config(text)

    async def set_channel_raw(self, key: str, raw: int) -> None:
        """Live-set one channel, 0-1023."""
        if key not in CHANNEL_KEYS:
            raise ValueError(f"unknown channel {key}")
        raw = max(0, min(RAW_MAX, int(raw)))
        reply = await self._get(f"{key}={raw}")
        if reply not in ("A+", "true", ""):
            _LOGGER.warning("%s=%s got unexpected reply %r", key, raw, reply[:40])

    async def set_channel_pct(self, key: str, pct: float) -> None:
        await self.set_channel_raw(key, pct_to_raw(pct))

    async def set_channels_pct(self, values: dict[str, float]) -> None:
        """Live-set several channels with individual (hardware-verified) commands.

        Paced: a burst of back-to-back requests has been seen to reboot a
        fixture (which then comes up at its stored 50 % levels).
        """
        for i, (key, pct) in enumerate(values.items()):
            if i:
                await asyncio.sleep(WRITE_SPACING)
            await self.set_channel_pct(key, pct)

    async def set_clock(self, epoch: int) -> str:
        """Set the fixture clock. Note the fixture applies its own timezone (factory UTC+8)."""
        return await self._get(f"clock={int(epoch)}")
