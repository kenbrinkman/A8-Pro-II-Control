# Home Assistant integration — A8 Pro II over local HTTP

Everything here talks to the light directly on your LAN (`http://<light-ip>/?…`). No cloud, no AIPAI
account, no MQTT broker. Requires only that the light is on the same network as Home Assistant and has a
stable IP.

Tested on Home Assistant 2026.9 with an A8 Pro II reporting model `A8PRO6` (8 channels, 2024 firmware).

## What you get

Per fixture, from [`a8_lights.yaml`](a8_lights.yaml):

| Entity | What it is |
|---|---|
| `light.a8_light3_white` … `light.a8_light3_warm_white` (8) | One dimmable light per LED channel. Brightness slider sends `?<ch>=<0–1023>` |
| `input_number.a8_light3_<ch>` (8) | The remembered level (0–100 %) behind each light — survives restarts |
| `sensor.a8_light3_temperature` | Heatsink temperature, °C, polled every 60 s |
| `sensor.a8_light3_serial`, `_model`, `_mode`, `_switch`, `_clock` | Identity and state from `read=config` |
| `rest_command.a8_set_channel` | Service: set one channel (`ip`, `channel`, `pct`) |
| `rest_command.a8_set_all` | Service: set all 8 channels in one call (`ip`, `w`, `b`, `r`, `g`, `b2`, `p`, `uv`, `wm` as 0–100) |
| `rest_command.a8_set_clock` | Service: sync the light's clock to HA's time |
| `automation.a8_light3_push_slider_to_light` | Pushes a directly-moved `input_number` slider to the light |

Channel order and colours (A8-PRO): `w` White · `b` Blue · `r` Red · `g` Green · `b2` Deep Blue · `p` Purple ·
`uv` UV · `wm` Warm White.

## Install

1. **Give the light a fixed IP** in your router (DHCP reservation). Find its current one with
   `python3 tools/a8_probe.py --scan 192.168.1.0/24` from the repo root.
2. **Enable packages** — open `configuration.yaml` in the File editor add-on and make sure it contains:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
   (If a `homeassistant:` key already exists, add the `packages:` line under it.)
3. **Create `packages/a8_lights.yaml`** next to `configuration.yaml` and paste in the contents of
   [`a8_lights.yaml`](a8_lights.yaml). Change `192.168.1.208` to your light's IP — it appears in the
   `rest:` resource line and in every `ip:` argument.
4. **Developer Tools → YAML → Check configuration**, then **Restart**.
5. Settings → Devices & services → Entities, search `A8 Light 3`. Drag a brightness slider; the light
   should change within a second.

## Adding more fixtures

The file is written for one light called "3". For each additional light, copy every block that contains
`light3` / `192.168.1.208` and change the number and IP:

- the 8 `input_number` entries
- the `rest:` resource block (sensors)
- the 8 template lights under `template:`
- the `automation` entry (update its `id`, `alias`, the 8 entity ids in `entity_id`, and `ip`)

A small Python generator that does this is at the bottom of this page.

## How it behaves — read before relying on it

**Assumed state.** The light does not report its live output. `read=config` returns the *stored* levels
(what the app last saved), not what the LEDs are doing now. So HA's sliders are the source of truth: what
you set in HA is what the light shows, and HA remembers it across restarts via the `input_number`s. If you
also change the light from the AIPAI app, HA won't know. Pick one controller.

**Two scales.** Live commands are 0–1023 (`?b2=1023` = 100 %). The package converts from percent for you.
`preview=` (used by `a8_set_all`) takes percent directly.

**The light's own schedule.** Out of the box the fixture is in manual mode with timezone UTC+8. If it is
ever switched to schedule mode (`mode=1`), its internal 24-point curve will override whatever HA sends, on
Beijing time. Keep it in manual mode and let HA drive the photoperiod.

**Persistence.** Not yet verified whether a live set survives the light's internal timer indefinitely. If
you see channels drift back after a while, add a periodic resend:

```yaml
automation:
  - alias: "A8 Light 3 - refresh every 5 min"
    triggers:
      - trigger: time_pattern
        minutes: "/5"
    actions:
      - action: rest_command.a8_set_all
        data:
          ip: "192.168.1.208"
          w:  "{{ states('input_number.a8_light3_w') }}"
          b:  "{{ states('input_number.a8_light3_b') }}"
          r:  "{{ states('input_number.a8_light3_r') }}"
          g:  "{{ states('input_number.a8_light3_g') }}"
          b2: "{{ states('input_number.a8_light3_b2') }}"
          p:  "{{ states('input_number.a8_light3_p') }}"
          uv: "{{ states('input_number.a8_light3_uv') }}"
          wm: "{{ states('input_number.a8_light3_wm') }}"
```

**Offline light.** The `rest` sensors go `unavailable` after a failed poll — a cheap "light is offline"
signal for an alert automation. Commands to an offline light fail silently in the log.

**Six-channel fixtures.** The sensor field indices in the package are for an 8-channel light. On a
6-channel model subtract 4 from each (temperature 17, clock 18, serial 21, model 24) and change the
`availability` guard from `> 28` to `> 20`. The channel list also drops to the first six.

**Safety.** The package never sends `save=`, `reset=`, `version=` (OTA) or `node=restart`. Those exist
in the protocol but can brick or wipe a fixture; they are deliberately left out.

## Next step: a photoperiod in HA

With `a8_set_all` a full sunrise → day → sunset → moonlight curve is one automation with a
`time_pattern` trigger and a template per channel — computed in your local timezone, with real DST, which
the vendor firmware can't do. Example skeleton (values are illustrative, not a reef recipe):

```yaml
automation:
  - alias: "A8 Light 3 - photoperiod"
    triggers:
      - trigger: time_pattern
        minutes: "/5"
    variables:
      # 0.0 at 09:00, 1.0 at 12:00–18:00, 0.0 at 21:00 — a simple trapezoid
      t: "{{ now().hour + now().minute / 60 }}"
      f: >-
        {% if t < 9 or t >= 21 %}0
        {% elif t < 12 %}{{ (t - 9) / 3 }}
        {% elif t < 18 %}1
        {% else %}{{ (21 - t) / 3 }}{% endif %}
    actions:
      - action: rest_command.a8_set_all
        data:
          ip: "192.168.1.208"
          w:  "{{ (40 * f) | round }}"
          b:  "{{ (90 * f) | round }}"
          r:  "{{ (10 * f) | round }}"
          g:  "{{ (10 * f) | round }}"
          b2: "{{ (100 * f) | round }}"
          p:  "{{ (60 * f) | round }}"
          uv: "{{ (60 * f) | round }}"
          wm: "{{ (20 * f) | round }}"
```

## Generator for extra fixtures

Run from the repo root; prints YAML for the fixtures you list. Paste the output into the package file,
merging under the existing top-level keys.

```python
CH = [("w","White"),("b","Blue"),("r","Red"),("g","Green"),
      ("b2","Deep Blue"),("p","Purple"),("uv","UV"),("wm","Warm White")]
LIGHTS = [("1","192.168.1.201"), ("2","192.168.1.202")]   # edit
src = open("homeassistant/a8_lights.yaml").read()
src = src[src.index("input_number:"):]        # skip the shared rest_command block
for n, ip in LIGHTS:
    print(src.replace("192.168.1.208", ip).replace("light3", f"light{n}")
             .replace("Light 3", f"Light {n}"))
```
