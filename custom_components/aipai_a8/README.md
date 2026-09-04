# AIPAI A8 Reef Light — Home Assistant integration

**Status: installed and working on Home Assistant 2026.9 with an A8 Pro II (`A8PRO6`).**

Local control of AIPAI / A+ Intelligent Control **A8** reef lights (A8 Pro II, A8 SE, A8 S, A8 X, A8 HP
and the A7 series) over their built-in HTTP server. No cloud, no vendor account, no YAML.

One **device** per fixture, added in the UI by IP address:

| Entity | What it does |
|---|---|
| `light.<name>_master` | Whole-fixture on/off and a proportional dimmer — scales every channel, like the app's intensity slider |
| `light.<name>_white` … `_warm_white` | One dimmer per LED channel (8 on A8 Pro/SE, 6 on older models; B models get Blue 1/2/3 etc.) |
| `sensor.<name>_temperature` | Heatsink temperature, polled every 60 s |
| `sensor.<name>_mode` | `manual` / `schedule` — which one the fixture is running (see services below) |
| `sensor.<name>_device_clock`, `_device_timezone` | Diagnostic — the fixture's own clock (factory timezone is UTC+8) |
| `sensor.<name>_fan_on` / `_fan_off` / `_thermal_cutoff` | Diagnostic, disabled by default |
| `button.<name>_push_levels_to_light` | Resend every channel's level — use after the fixture lost power |
| `button.<name>_sync_clock` | Set the fixture clock from HA |

Serial number and model appear on the device card. Factory reset, firmware update and reboot are
deliberately **not** exposed; they can brick a fixture.

## Install

**HACS (recommended)** — HACS → ⋮ → *Custom repositories* → add
`https://github.com/kenbrinkman/A8-Pro-II-Control`, type *Integration* → *Download* → restart HA.

**Manual** — copy `custom_components/aipai_a8/` into your `/config/custom_components/` and restart.

Then **Settings → Devices & services → Add integration → "AIPAI A8 Reef Light"**, enter the light's IP.
Give the light a DHCP reservation in your router first so the IP doesn't change.

## How it behaves

- **Assumed state.** The fixture cannot report its live output — `read=config` returns the *stored*
  levels, not what the LEDs are doing. Home Assistant is therefore the source of truth: the UI shows
  separate on/off buttons, levels are remembered across restarts, and on a fresh add the channels are
  seeded from the fixture's stored config so they start out matching. Don't also drive the light from
  the AIPAI app; HA won't see those changes.
- **Master × channel.** Each channel has a set point (0–100 %). What the light receives is
  `set point × master %`. Master off sends 0 to every channel; master on restores them. Changing a
  channel sends one HTTP call; changing the master sends one per channel (all hardware-verified
  commands, no `preview=`).
- **Reboots.** A fixture that loses power or crashes boots to its *stored* config — factory: switch on,
  every channel 50 % — i.e. it lights itself up. The integration detects the light coming back from
  unavailable and immediately re-sends HA's levels (v0.1.1). **Push levels to light** does the same by hand.
- **Don't flood it.** A burst of back-to-back commands has been seen to reboot a fixture. The client
  paces consecutive channel writes (150 ms); keep that in mind if you script direct HTTP calls.
- **Live sets are temporary.** Anything sent with the sliders is a preview: every few minutes (and
  after any reboot) the firmware re-applies its *stored* config. What persists is what `save=` wrote.
  The two services below are the only things that write it (one flash write per call — don't call
  them every minute).

- **Bad replies are dropped, not shown.** The firmware occasionally answers with a truncated config
  string or a zeroed temperature field. A reply with fewer than 25 fields is rejected outright (parsing
  it would shift every later field), a heatsink reading outside 1–120 °C is discarded and the previous
  value held, and a reply carrying a different serial is ignored. In every case the last good data
  stands until the next poll (v0.2.1).

## Services (v0.2.0)

- **`aipai_a8.set_schedule`** — `sunrise`, `full_day`, `sunset`, `night`, `peak`, optional
  `ratios` (per-channel % of the master curve; default = HA's current channel set points). Computes
  24 hourly points per channel, stores them with the fixture in **schedule** mode, sets its timezone to
  HA's current UTC offset and syncs its clock. The light then runs the day cycle on its own: no
  polling, survives reboots. Call it again whenever a time, peak or spectrum changes — and after a
  DST change (an automation on `homeassistant.start` + a daily check is enough). Firmware
  interpolates between hour points, so 11:45 becomes a ramp anchored on the 11:00 and 12:00 points.
- **`aipai_a8.set_manual`** — stores fixed levels in **manual** mode. `off: true` parks the light dark
  (stays dark through reboots); `levels` sets explicit values; omitting both stores what HA is
  currently sending. Use this when the tank is not running.

While in schedule mode the sliders still work as short-lived overrides (a few minutes, until the
firmware's next re-apply).

## Protocol

Documented in the [repository README](../../README.md). The client (`api.py`) has no Home Assistant
dependencies and doubles as a reference implementation.
