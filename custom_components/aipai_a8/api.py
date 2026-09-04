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
    MIN_CONFIG_FIELDS,
    RAW_MAX,
    REQUEST_TIMEOUT,
    TEMP_MAX_C,
    TEMP_MIN_C,
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


def _plausible_temp(v: float | None) -> float | None:
    """Discard an obviously wrong heatsink reading.

    The fixture sometimes answers with the temperature field zeroed (seen on
    two lights within seconds of each other, one poll each). 0 degrees C is not
    a heatsink temperature in a living room -- it lands in HA history as a 32 F
    spike. Out-of-range becomes None and the coordinator carries the previous
    reading forward.
    """
    if v is None or not (TEMP_MIN_C <= v <= TEMP_MAX_C):
        if v is not None:
            _LOGGER.debug("discarding implausible temperature %.1f C", v)
        return None
    return v


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
    # A short reply is a truncated/transient answer, not a 6-channel light.
    # Parsing it anyway reads the wrong field for everything after the
    # schedule block, which is how a bogus temperature gets through.
    if len(f) < MIN_CONFIG_FIELDS:
        raise A8ProtocolError(
            f"config string has {len(f)} fields, expected at least {MIN_CONFIG_FIELDS}"
        )
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
        temperature=_plausible_temp(_float(_f(f, 17 + d))),
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


def _pct(v: float) -> int:
    return max(0, min(100, int(v)))


def build_save_blob(
    *,
    channels: int,
    mode: int,
    levels_pct: list[int],
    schedule: list[list[int]],
    fan_on: float | None = None,
    fan_off: float | None = None,
    fan_cutoff: float | None = None,
    timer_on: int = 0,
    timer_off: int = 0,
    timezone: str = "8",
) -> str:
    """Build the `save=` payload exactly as the vendor app's DevicesSave() does.

    Layout, fields joined with `x`, every `,` replaced by `y`:
        on x <mode> x <fan_on> x <fan_off> x <fan_cutoff>
           x <level×n> x <24-point row×n> x <timer_on> x <timer_off> x <tz>

    - Field 0 is always the literal `on`: the app never writes `off` (its own
      comment says the device ignores a save while switched off).
    - The app hard-codes fan 35/30/80; here the caller passes the fixture's own
      values (read from `read=config`) so a save does not silently change them.
      The app warns the firmware ignores a cutoff above ~84 °C, so cap at 80.
    - Levels and schedule points are 0-100 percent (NOT the 0-1023 live scale).
    - The channel count must match the fixture: a 6-channel blob on 8-channel
      firmware shifts every field after the padding point.
    """
    if channels not in (6, 8):
        raise ValueError(f"channels must be 6 or 8, got {channels}")
    if len(levels_pct) != channels:
        raise ValueError(f"need {channels} levels, got {len(levels_pct)}")
    if len(schedule) != channels:
        raise ValueError(f"need {channels} schedule rows, got {len(schedule)}")
    for i, row in enumerate(schedule):
        if len(row) != 24:
            raise ValueError(f"schedule row {i} has {len(row)} points, need 24")

    def _fan(v: float | None, default: int, hi: int = 80) -> str:
        if v is None:
            return str(default)
        return str(int(min(hi, max(0, v))))

    parts: list[str] = [
        "on",
        str(1 if int(mode) == 1 else 0),
        _fan(fan_on, 35),
        _fan(fan_off, 30),
        _fan(fan_cutoff, 80),
    ]
    parts += [str(_pct(v)) for v in levels_pct]
    parts += [",".join(str(_pct(p)) for p in row) for row in schedule]
    parts += [str(int(timer_on)), str(int(timer_off)), str(timezone)]
    return "x".join(parts).replace(",", "y")


def photoperiod_points(
    sunrise: int, full_day: int, sunset: int, night: int, peak: float
) -> list[float]:
    """Master intensity (0-100) at each of the 24 hour marks.

    Times are minutes after midnight. The cycle may cross midnight (e.g.
    11:45 -> 15:45 -> 20:45 -> 00:45): everything is measured as minutes
    since sunrise, modulo 24 h. Ramps are linear: 0 -> peak from sunrise to
    full_day, peak until sunset, peak -> 0 until night, then 0.
    """
    day = 1440
    up = (full_day - sunrise) % day
    hold = (sunset - sunrise) % day
    end = (night - sunrise) % day
    if not (0 < up <= hold <= end):
        raise ValueError("times must be ordered sunrise < full_day <= sunset <= night (mod 24 h)")
    out: list[float] = []
    for h in range(24):
        m = (h * 60 - sunrise) % day
        if m < up:
            v = peak * m / up
        elif m < hold:
            v = peak
        elif m < end and end > hold:
            v = peak * (1 - (m - hold) / (end - hold))
        else:
            v = 0.0
        out.append(max(0.0, min(100.0, v)))
    return out


def scale_points(master: list[float], ratio_pct: float) -> list[int]:
    """Apply a channel's spectrum ratio (0-100 %) to the master curve, rounding to ints.

    The vendor app floors and caps at 98; we round and cap at 100, the range
    the firmware accepts for stored levels.
    """
    r = max(0.0, min(100.0, float(ratio_pct))) / 100
    return [max(0, min(100, int(round(v * r)))) for v in master]


def tz_string(utc_offset_seconds: int | float) -> str:
    """HA's UTC offset -> the fixture's timezone field ('8', '-4', '5.5')."""
    hours = utc_offset_seconds / 3600
    return str(int(hours)) if float(hours).is_integer() else f"{hours:g}"


def blob_from_config(cfg: A8Config, **overrides) -> str:
    """Rebuild a save blob from a decoded `read=config`, with optional overrides.

    Overrides accept the same keyword names as build_save_blob(). Used to make
    minimal, hardware-safe changes (e.g. one stored level) and by the
    integration to preserve fan thresholds and timers it does not manage.
    """
    schedule: list[list[int]] = []
    for row in cfg.schedule:
        pts = [_int(p) or 0 for p in row.split(",")] if row else []
        if len(pts) != 24:
            pts = [0] * 24
        schedule.append(pts)
    kwargs = dict(
        channels=cfg.channels,
        mode=cfg.mode,
        levels_pct=list(cfg.levels_pct),
        schedule=schedule,
        fan_on=cfg.fan_on,
        fan_off=cfg.fan_off,
        fan_cutoff=cfg.fan_cutoff,
        timer_on=cfg.timer_on or 0,
        timer_off=cfg.timer_off or 0,
        timezone=cfg.timezone or "8",
    )
    kwargs.update(overrides)
    return build_save_blob(**kwargs)


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

    async def save_config(self, blob: str) -> None:
        """Write the stored configuration (`save=<blob>`). This is a flash write.

        Build `blob` with build_save_blob() / blob_from_config(). The firmware
        answers the literal `true` on success.
        """
        if not blob.startswith("onx"):
            raise ValueError("save blob must start with 'onx'")
        reply = await self._get(f"save={blob}")
        if reply != "true":
            raise A8ProtocolError(f"save= answered {reply[:40]!r}, expected 'true'")
