# AIPAI A8 Reef Light — Home Assistant integration

Local control of AIPAI / A+ Intelligent Control **A8** reef lights (A8 Pro II, A8 SE, A8 S, A8 X, A8 HP
and the A7 series) over their built-in HTTP server. No cloud, no vendor account, no YAML.

One **device** per fixture, added in the UI by IP address:

| Entity | What it does |
|---|---|
| `light.<name>_master` | Whole-fixture on/off and a proportional dimmer — scales every channel, like the app's intensity slider |
| `light.<name>_white` … `_warm_white` | One dimmer per LED channel (8 on A8 Pro/SE, 6 on older models; B models get Blue 1/2/3 etc.) |
| `sensor.<name>_temperature` | Heatsink temperature, polled every 60 s |
| `sensor.<name>_mode` | `manual` / `schedule` — keep it on **manual** so HA is in charge |
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
- **Lost power?** The fixture boots to its stored config. Press **Push levels to light**, or automate it
  on the temperature sensor coming back from `unavailable`.
- **Photoperiod.** Drive it from HA (a `time_pattern` automation setting the channel lights) in your
  own timezone with real DST. Leave the fixture in manual mode.

## Protocol

Documented in the [repository README](../../README.md). The client (`api.py`) has no Home Assistant
dependencies and doubles as a reference implementation.
