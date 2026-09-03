# A8 Pro II — Control Protocol (reverse-engineered)

Native, local control of **A8 Pro II** reef lights (and their A8/A7 siblings) — no vendor cloud,
no AIPAI app account. This repo documents the control protocol recovered from static analysis of
the AIPAI Android app, plus a stdlib-only probe you can run against your own fixtures.

> **Goal:** drive these lights from Home Assistant, per channel, entirely on the LAN.
>
> **Status:** protocol fully recovered from the app's own source. The local-HTTP path (§ Route A)
> needs a 10-second confirmation against real hardware — run [`tools/a8_probe.py`](tools/a8_probe.py).

Vendor: 济南海内无双科技有限公司 (Jinan Hainei Wushuang Technology, Jinan, China). App published as
"darden inc."; backend `doseen.com` → Alibaba Cloud. Lights are marketed as Radion XR30 clones
(Cree LEDs, Meanwell drivers).

---

## TL;DR

| | |
|---|---|
| **Local control path** | An HTTP server **on the light itself**: `GET http://<ip>/?<cmd>` |
| **Channels (A8-PRO)** | 8 — `w b r g b2 p uv wm` |
| **Resolution** | 10-bit PWM, **0–1023** (the app's slider is only 0–100%) |
| **Set a channel** | `GET http://<light-ip>/?b2=1023` |
| **Read everything** | `GET http://<light-ip>/?read=config` |
| **Cloud transport** | MQTT over plain WebSocket, `ws://mqtt.doseen.com:8083/mqtt` (no TLS) |
| **Cloud auth** | Hardcoded global `aplus` / `19491001`; per-device addressing by serial only |

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
postVal  = Math.round(1023 * percent / 100)              // 10-bit PWM, 0–1023
```

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
| `read=config` | Dump full configuration (§3) |
| `save=<blob>` | Write full configuration (§4) |
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
| `[5 .. 5+n-1]` | Current level per channel (0–1023), in `roadName` order |
| `[5+n .. ]` | 24 comma-separated points per channel — the daily schedule curve |
| `[24 + 2·(n−6)]` | Model string, e.g. `A8PRO9` |

`n` = channel count. **Discriminator: more than 28 fields ⇒ 8 channels, else 6.** Each schedule
row is 24 hourly points the firmware interpolates — the whole photoperiod, readable and writable.

---

## 4. `save=` blob

Fields joined with `x`; commas inside schedule rows become `y` (URL-safe):

```
on x <mode> x 35 x 30 x 80 x <roadVal ×n> x <roadData ×n> x <openValue> x <closeValue> x <timeZone>
```

- `roadVal` — n current values (0–1023)
- `roadData` — n schedule rows of 24 values (commas → `y`)

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
when firmware year > 2023. The HTTP server is very likely still listening on current firmware — the
app simply stopped calling it. **Confirm with the probe.** If it answers, HA control is pure
`rest_command` + a `rest` sensor. Fully local.

### Route B — DNS redirect to a local broker ★★ best if A fails
The lights dial out to `mqtt.doseen.com`. Point that hostname at your own Mosquitto via a local DNS
override, accept `aplus` / `19491001`, subscribe `light/+/dev`, publish `light/<SN>/mob`, and
firewall the lights from the internet. They talk to a broker in your house believing it's the
vendor's. (Device-side MQTT port — 1883/8883 — needs a one-line pcap to confirm; the app uses WS 8083.)

### Route C — vendor cloud broker ✓ works today, cloud-dependent
Connect an MQTT client to `ws://mqtt.doseen.com:8083/mqtt` (`aplus` / `19491001`) and publish to
`light/<SN>/mob`:
```json
{"type": "w512", "msg": "w=512"}
```
`type` is the msg with `=` stripped. Use it to validate the grammar without hardware access; avoid
it as a permanent solution (Chinese cloud dependency).

### Topics
| Topic | Direction |
|---|---|
| `light/<SN>/mob` | app → device (commands) |
| `light/<SN>/dev` | device → app (replies, `{type, msg}`) |
| `dev/<SN>` / `mob/<clientId>` | newer generic device/app topics |
| `wave/<SN>/…`, `water/<SN>/…` | sibling product lines, same scheme |

---

## 6. Hardware test plan

1. **Local API alive?** `python3 tools/a8_probe.py <ips>` — or `curl -m5 "http://<ip>/?read=config"`.
   Pipe-delimited string back → Route A is live.
2. **Port sweep** if it's quiet: `nmap -Pn -p- --open <ip>` and check the MAC OUI (WiFi module vendor).
3. **Where does it connect?** `tcpdump -n host <ip>` across a reboot — watch for the
   `mqtt.doseen.com` DNS query and the port that follows (1883/8883/8083). Decides Route B.
4. **Serial numbers** (for B/C) — in the app's device list and on the fixture label.

---

## 7. Security findings

These are properties of the product, worth acting on regardless of the integration:

1. **Global hardcoded credentials** `aplus` / `19491001`, compiled into every copy of the app. No
   per-user or per-device secret.
2. **No transport encryption** — `ws://` on 8083; commands and config cross the internet in clear text.
3. **No device-level authorization** — anyone who knows a serial number can control that fixture,
   including its schedule and OTA update. Serials appear sequential.
4. **Remote OTA on the same unauthenticated channel** (`version=<file>`).

**Recommendation:** put the fixtures on an IoT VLAN and firewall them from the internet. Routes A
and B both remove any need for outbound access.

---

## How the app was analysed

The AIPAI app (`com.doseen`-family, APICloud/uzmap hybrid) keeps all its logic as HTML/JS,
RC4-encrypted inside the APK. The key is statically recoverable from `lib/*/libsec.so`.
[`tools/apicloud_decrypt.py`](tools/apicloud_decrypt.py) is a dependency-free decryptor (method per
[newdive/uzmap-resource-extractor](https://github.com/newdive/uzmap-resource-extractor)). This repo
documents the recovered *protocol* for interoperability; it does not redistribute the vendor's app
or its decrypted source.

## Contents

| Path | What |
|---|---|
| [`tools/a8_probe.py`](tools/a8_probe.py) | Stdlib LAN probe — finds the local API and decodes `read=config` |
| [`tools/apicloud_decrypt.py`](tools/apicloud_decrypt.py) | Dependency-free APICloud/uzmap RC4 resource decryptor |
| [`docs/img/`](docs/img/) | Vendor manual pages (OEM + reset procedure) |

## Disclaimer

Independent interoperability research, not affiliated with or endorsed by the manufacturer.
Documented so owners can control hardware they bought, locally. Use at your own risk; OTA and
factory-reset commands can brick a fixture. No warranty.

## License

Code under [MIT](LICENSE). Protocol documentation under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
