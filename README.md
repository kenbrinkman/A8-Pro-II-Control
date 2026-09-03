# A8 Pro II — Control Protocol (reverse-engineered)

Native, local control of **A8 Pro II** reef lights (and their A8/A7 siblings) — no vendor cloud,
no AIPAI app account. This repo documents the control protocol recovered from static analysis of
the AIPAI Android app, plus a stdlib-only probe you can run against your own fixtures.

> **Goal:** drive these lights from Home Assistant, per channel, entirely on the LAN.
>
> **Status: Route A confirmed on hardware (3 Sep 2026).** An A8 Pro II (firmware model string `A8PRO6`,
> 2024 firmware) on home Wi-Fi answers `GET http://<ip>/?read=config` and drives its channels from
> `GET http://<ip>/?b2=1023` — no app, no account, no cloud. A ready-to-use Home Assistant package is in
> [`homeassistant/`](homeassistant/). Details in §8.

Vendor: 济南海内无双科技有限公司 (Jinan Hainei Wushuang Technology, Jinan, China). App published as
"darden inc."; backend `doseen.com` → Alibaba Cloud. Lights are marketed as Radion XR30 clones
(Cree LEDs, Meanwell drivers).

---

## TL;DR

| | |
|---|---|
| **Local control path** | An HTTP server **on the light itself**: `GET http://<ip>/?<cmd>` |
| **Channels (A8-PRO)** | 8 — `w b r g b2 p uv wm` |
| **Resolution** | Live set: 10-bit, **0–1023**. Config read/write and schedule: **0–100 %** |
| **Set a channel** | `GET http://<light-ip>/?b2=1023` |
| **Identify** | `GET http://<light-ip>/?sta=getip` → `<ip>,<serial>,<flag>` |
| **Read everything** | `GET http://<light-ip>/?read=config` |
| **Cloud transport** | MQTT (EMQX 5) over plain WebSocket, `ws://mqtt.doseen.com:8083/mqtt` (no TLS) |
| **Cloud auth** | One hardcoded username/password shared by every copy of the app; per-device addressing by serial only |

The command grammar is **identical** whether it travels over local HTTP or cloud MQTT — one firmware
parser, two transports. That is what makes fully-local control possible.

---

## Quick start

On any machine on the same LAN as the lights:

```bash
python3 tools/a8_probe.py 192.168.1.71 192.168.1.72 192.168.1.73
```

Read-only, stdlib only. If it prints **LOCAL HTTP API IS ALIVE** with a decoded channel table, the
local path is confirmed and Home Assistant integration is a handful of `rest_command` entries.

Optional live write test (sets one channel, then you set it back):

```bash
python3 tools/a8_probe.py 192.168.1.71 --set b2=1023
python3 tools/a8_probe.py 192.168.1.71 --set b2=0
```

---

## 1. Channel model

```js
roadName = ["w", "b", "r", "g", "b2", "p", "uv", "wm"]   // firmware channel order
postVal  = Math.round(1023 * percent / 100)              // live single-channel set: 0–1023
```

**Two scales.** A live `w=<v>` takes 0–1023. Everything else — the levels and schedule rows in `read=config`,
the `save=` blob, and the multi-channel `preview=` command — is **0–100 %** (schedule points are integers, the
app caps them at 98). Confirm on hardware: send `b2=1023`, then `read=config` and check the level reads 100.

| Idx | Key | Colour (A8-PRO / A8-SE, 8-ch) |
|---|---|---|
| 0 | `w`  | White |
| 1 | `b`  | Blue |
| 2 | `r`  | Red |
| 3 | `g`  | Green |
| 4 | `b2` | Deep Blue |
| 5 | `p`  | Purple |
| 6 | `uv` | UV |
| 7 | `wm` | Warm White |

Channel count is derived from the model string: **8** for
`A8-S5 A8-SE5 A8-SE8 A8-PRO5 A8-X5 A8-S6 A8-SE6 A8-PRO6 A8-X6 A8-HP6 A8-SEB A8-PROB A8-SE9 A8-PRO9 A8-SEB9 A8-PROB9`,
otherwise 6. `B`-suffixed models relabel channels (Blue1/Blue2/Warm/Olive/Blue3/Purple/UV/White) —
same wire order, different LED binning. **Confirm your fixture's `type` string before assuming a map.**

---

## 2. Command grammar

The payload is always a `key=value` query string, over either transport.

```
w=512        # white to 50%
b2=1023      # deep blue to full
uv=0         # UV off
```

| Command | Effect |
|---|---|
| `sta=getip` | Identity: `<ip>,<serial>,<flag>` — the app's own liveness check, no account needed |
| `read=config` | Dump full configuration (§3) |
| `save=<blob>` | Write full configuration (§4) |
| `preview=<hour>&w=<pct>&b=<pct>…` | Drive all channels at once (values 0–100) |
| `sta=aplist` / `sta=apconnect&ssid=&pwd=` | Wi-Fi provisioning, served at `192.168.4.1` in AP mode |
| `reset=1` | Factory reset |
| `clock=<str>` | Set device clock |
| `version=<file>` | Trigger OTA firmware update |
| `node=restart` | Reboot |
| `mculed=on` / `mculed=off` | Fixture status LED |
| `turnoffset=0` / `turnoffset=1` | Fade behaviour toggle |

---

## 3. `read=config` response

A single `|`-delimited string:

| Field | Meaning |
|---|---|
| `[0]` | Switch — `on` / `off` |
| `[1]` | Mode — `0` manual, `1` schedule |
| `[2]` `[3]` `[4]` | Fan on / fan off / thermal cutoff (°C; firmware hard limit 84) |
| `[5 .. 5+n-1]` | Current level per channel (**0–100 %**), in `roadName` order |
| `[5+n .. 5+2n-1]` | 24 comma-separated points per channel (0–100) — the daily schedule curve |
| `[17+d]` | Heatsink temperature, °C |
| `[18+d]` | Device clock, `"H,M"` |
| `[19+d]` `[20+d]` | Timer on / off hour (0 = unset) |
| `[21+d]` | Serial number |
| `[22+d]` | Intensity-knob flag |
| `[23+d]` | Timezone, UTC offset |
| `[24+d]` | Model string, e.g. `A8PRO9` |

`n` = channel count, `d = 2·(n−6)`. An 8-channel reply has 29 fields, a 6-channel reply 25.
**Discriminator: more than 28 fields ⇒ 8 channels, else 6.** Each schedule row is 24 hourly points the
firmware interpolates — the whole photoperiod, readable and writable. A reply of just `A+` means the device
answered but did not return a config (the app treats it as "not directly connected").

---

## 4. `save=` blob

Fields joined with `x`; commas inside schedule rows become `y` (URL-safe):

```
on x <mode> x 35 x 30 x 80 x <roadVal ×n> x <roadData ×n> x <openValue> x <closeValue> x <timeZone>
```

- `roadVal` — n current values (0–100)
- `roadData` — n schedule rows of 24 integer values 0–100 (commas → `y`)

> The app **always writes `on`** for field 0 regardless of real state — a documented firmware
> workaround. Sending a 6-channel blob to 8-channel firmware requires `0x0x` padding after the 6
> values and two zero rows after the 6 schedule rows. Match the channel count exactly.

---

## 5. Three routes to Home Assistant

Best-first. Not mutually exclusive — A is the goal, C is the guaranteed fallback.

### Route A — local HTTP (no cloud) ★ preferred
```
GET http://<light-ip>/?w=512
GET http://<light-ip>/?read=config
```
The app computes `serverUrl = "http://" + device.ip + "/"` unconditionally and only *chooses* MQTT
when firmware year > 2023 (the MQTT path arrived in the app's May 2024 release). But the current app
still drives **every** light over HTTP in its "direct link" mode (phone joined to the light's own `ALight…`
AP, `http://192.168.4.1/?read=config`, per-channel `?w=…`) and provisions over `?sta=…` — so the HTTP server
and the `key=value` parser are present in 2024+ firmware. The only open question is whether it keeps
listening once the light is on your Wi-Fi. **Confirm with the probe.** If it answers, HA control is pure
`rest_command` + a `rest` sensor. Fully local.

### Route B — DNS redirect to a local broker ★★ best if A fails
The lights dial out to `mqtt.doseen.com`. Point that hostname at your own Mosquitto via a local DNS
override, accept the app's hardcoded username/password (or allow anonymous), subscribe `light/+/dev`,
publish `light/<SN>/mob`, and firewall the lights from the internet. They talk to a broker in your house
believing it's the vendor's. Expect the light to connect as client ID `<TYPE>-<SN>-DEV` with the dash removed
from the type, e.g. `A8PRO9-12345678-DEV`. The vendor broker is EMQX 5, whose default plain-MQTT listener is
1883 — a one-line pcap of a booting light confirms the port.

### Route C — vendor cloud broker ✓ works today, cloud-dependent
Connect an MQTT client to `ws://mqtt.doseen.com:8083/mqtt` with the app's credentials and publish to
`light/<SN>/mob`:
```json
{"type": "w512", "msg": "w=512"}
```
For channel sets `type` is the msg with `=` stripped. For the others it is fixed: `readconfig`
(`read=config`), `saveconfig` (`save=…`), `clock`, `version`, `reset`. Moonlight (`moonRead`, `moonSet`)
and `timeZoneSet` are pure JSON on 2026 "moon" models. Replies arrive on `light/<SN>/dev` as `{type, msg}`.
Use this to validate the grammar without hardware access; avoid it as a permanent solution (Chinese cloud
dependency).

### Topics
| Topic | Direction |
|---|---|
| `light/<SN>/mob` | app → device (commands) |
| `light/<SN>/dev` | device → app (replies, `{type, msg}`) |
| `dev/<SN>` / `mob/<clientId>` | newer generic device/app topics |
| `wave/<SN>/…`, `water/<SN>/…` | sibling product lines, same scheme |

---

## 6. Hardware test plan

1. **Local API alive?** `python3 tools/a8_probe.py <ips>` — or `curl -m5 "http://<ip>/?sta=getip"` then
   `curl -m5 "http://<ip>/?read=config"`. Pipe-delimited string back → Route A is live.
   Then the scale test: `?b2=1023`, re-read config, expect level 100; `?b2=512` → 50; restore.
   Then check whether a live set survives the next schedule tick, or whether HA must write the schedule.
2. **Port sweep** if it's quiet: `nmap -Pn -p- --open <ip>` and check the MAC OUI (WiFi module vendor).
3. **Where does it connect?** `tcpdump -n host <ip>` across a reboot — watch for the
   `mqtt.doseen.com` DNS query and the port that follows (1883/8883/8083). Decides Route B.
4. **Serial numbers** (for B/C) — in the app's device list and on the fixture label.

---

## 7. Security findings

These are properties of the product, worth acting on regardless of the integration:

1. **Global hardcoded broker credentials**, compiled into every copy of the app. No per-user or
   per-device secret. (Deliberately not reproduced here; they are one grep away after decryption.)
2. **No transport encryption** — `ws://` on 8083; commands and config cross the internet in clear text.
3. **No device-level authorization** — anyone who knows a serial number can control that fixture,
   including its schedule and OTA update. Serials appear sequential.
4. **Remote OTA on the same unauthenticated channel** (`version=<file>`).
5. The app also embeds a broker management-API key and sends raw SQL to the vendor's device API.
   Neither is reproduced here.

**Recommendation:** put the fixtures on an IoT VLAN and firewall them from the internet. Routes A
and B both remove any need for outbound access.

---

## 8. Hardware confirmation — what the light actually does

Tested against one A8 Pro II, station mode, factory-reset, joined to a 2.4 GHz home network.
Probe output, verbatim:

```
LOCAL HTTP API IS ALIVE  →  http://192.168.1.208:80/
sta=getip: ip=192.168.1.208 serial=XXXXXXX flag=false
model=A8PRO6  serial=XXXXXXX  channels=8  switch=on  mode=0 (manual)
temp=43.19°C  clock=7,14  timer on/off=0/0  tz=UTC8  fan on/off/cutoff=65/50/75
```

Findings:

| | |
|---|---|
| **HTTP server** | Listening on port 80 in station mode on 2024 firmware. Route A works. |
| **`read=config`** | 29 fields, layout exactly as §3. Field 25 is the serial, 28 the model. |
| **Live set** | `?b2=1023` / `?b2=100` / `?b2=512` — LEDs respond immediately; scale is **0–1023** as documented (100 ≈ 10 %). |
| **Reply to a set** | The literal string `A+` — an acknowledgement, not an error. |
| **Read-back** | `read=config` reports the **stored** level, not the live one — after `?b2=1023` it still says 50. Live state is tracked client-side (as the app does); treat sliders in HA as assumed-state. |
| **Factory defaults** | Timezone **UTC+8**, so the light's own schedule runs on Beijing time until you set it. Fan thresholds 65/50/75 (the app overwrites these with 35/30/80 on every save). Manual mode, all channels 50 %. |
| **Persistence** | Not yet tested — whether a live set survives the light's internal timer. The HA package can add a periodic resend if it doesn't. |

Two other devices on the network answered on port 80 with something other than a config string (a
router page and an unrelated device) — the probe handles that; only a `|`-delimited reply counts.

### Home Assistant

[`homeassistant/a8_lights.yaml`](homeassistant/a8_lights.yaml) is a package that gives you, per fixture:

- eight `light.*` entities (one per channel, brightness slider → `?<ch>=<0–1023>`),
- sensors for temperature, serial, model, mode and the light's clock (polled from `read=config` every 60 s),
- services `rest_command.a8_set_channel`, `a8_set_all` (all channels in one `preview=` call — use it for
  sunrise/sunset scenes) and `a8_set_clock`.

Install: enable packages in `configuration.yaml` (`homeassistant: packages: !include_dir_named packages`),
save the file as `packages/a8_lights.yaml`, check config, restart. Edit the IP at the top for your light;
duplicate the blocks for additional fixtures. Every template in it was verified against the real reply above.

---

## How the app was analysed

The AIPAI app (`com.darden.hnws`, APICloud/uzmap hybrid) keeps all its logic as HTML/JS,
RC4-encrypted inside the APK. The key is statically recoverable from `lib/*/libsec.so`.
[`tools/apicloud_decrypt.py`](tools/apicloud_decrypt.py) is a dependency-free decryptor (method per
[newdive/uzmap-resource-extractor](https://github.com/newdive/uzmap-resource-extractor)). This repo
documents the recovered *protocol* for interoperability; it does not redistribute the vendor's app
or its decrypted source.

## Contents

| Path | What |
|---|---|
| [`tools/a8_probe.py`](tools/a8_probe.py) | Stdlib LAN probe — finds the local API, decodes `sta=getip` and `read=config`; `--set` / `--raw` for write tests (refuses OTA/reset/save) |
| [`tools/apicloud_decrypt.py`](tools/apicloud_decrypt.py) | Dependency-free APICloud/uzmap RC4 resource decryptor |
| [`homeassistant/a8_lights.yaml`](homeassistant/a8_lights.yaml) | Home Assistant package — per-channel lights, sensors, services |
| [`docs/img/`](docs/img/) | Vendor manual pages (OEM + reset procedure) |

## Disclaimer

Independent interoperability research, not affiliated with or endorsed by the manufacturer.
Documented so owners can control hardware they bought, locally. Use at your own risk; OTA and
factory-reset commands can brick a fixture. No warranty.

## License

Code under [MIT](LICENSE). Protocol documentation under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
