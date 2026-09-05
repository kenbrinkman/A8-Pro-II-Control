# A8 Pro II — Control Protocol Reference

*Reverse-engineered from AIPAI Android app v3.1.82.*

> **Redacted public copy.** This document is generated from a private master by redaction only —
> fixture serials, LAN addresses, host names and Home Assistant device IDs are removed, as are three
> subsections of §13 that are pure repo housekeeping and private links (§13.6, §13.8, §13.9). The
> vendor's hardcoded broker credentials and the app's RC4 bundle key are also withheld: both are
> global to the product rather than secrets of this install, and both are recoverable from the APK
> with `tools/apicloud_decrypt.py` by the method in §0. **Nothing about the protocol itself has been
> removed.** Placeholders read `<like-this>`.

**Status (5 Sep 2026): Route A confirmed on hardware; three fixtures running under a custom
Home Assistant integration, `aipai_a8` v0.2.3.** The test fixtures (A8 Pro II, firmware model
`A8PRO6`) answer on port 80 in station mode. Installed via HACS, one device per fixture.
Public repo: https://github.com/kenbrinkman/A8-Pro-II-Control

### Document map

| Sections | What they are |
|---|---|
| §0–§8 | The protocol itself. Stable; changes only if firmware does. |
| §9–§12 | Build log, 3 Sep. Historic snapshots — each says what supersedes it. |
| §13 | The write path (4 Sep, late). Integration v0.2.3 + the dashboard save button. |
| §14 | Master vs Peak vs Schedule (4 Sep, **earlier** — §13 is its sequel). Out of chronological order so §13's published numbering stays put. |
| §15 | Consolidated current state and open items. **Supersedes every earlier "Still open" / "Next" list.** |

---

## 0. Executive summary

| Question | Answer |
|---|---|
| Is there a local (no-cloud) control path? | **Yes — confirmed.** An HTTP server on the light, port 80, alive in station mode on 2024 firmware. The app only *uses* it for ≤2023 firmware and in "direct link" AP mode, but it is always there. |
| Cloud transport | MQTT over **plain WebSocket**, `ws://mqtt.doseen.com:8083/mqtt` — **no TLS** |
| Cloud auth | A hardcoded global username/password pair, identical for every user of the app — values withheld here, see §7 |
| Per-device auth | **None.** Addressing is by serial number alone |
| Command grammar | Identical over both transports — a `key=value` query string |
| Channels | 8 on A8-PRO (`w b r g b2 p uv wm`). Live set 0–1023; config/schedule values 0–100 % |
| Per-channel HA control feasible? | **Done** — `custom_components/aipai_a8`, one device per fixture (§10) |
| What actually persists? | **Only `save=`.** Live `?w=`/`?b2=` sets are a preview the firmware discards at its next re-apply (§11, §14) |

The app is an APICloud/uzmap hybrid — all logic is HTML/JS, RC4-encrypted inside the APK with a key
statically recoverable from `lib/*/libsec.so` (the key for a given build is not reproduced here).
Method: `newdive/uzmap-resource-extractor`; a dependency-free reimplementation lives in `decrypt.py`.

**Vendor:** 济南海内无双科技有限公司 (Jinan Hainei Wushuang Technology Co., Ltd), Jinan, China.
App published as "darden inc."; backend `doseen.com` → `47.104.138.139` (Alibaba Cloud, Hangzhou).

---

## 1. Channel model

```js
roadName = ["w", "b", "r", "g", "b2", "p", "uv", "wm"]
```

| Idx | Key | Colour | A8-PRO / A8-SE (8-ch) |
|---|---|---|---|
| 0 | `w`  | White | ✓ |
| 1 | `b`  | Blue | ✓ |
| 2 | `r`  | Red | ✓ |
| 3 | `g`  | Green | ✓ |
| 4 | `b2` | Deep Blue | ✓ |
| 5 | `p`  | Purple | ✓ |
| 6 | `uv` | UV | ✓ |
| 7 | `wm` | Warm White | ✓ |

Channel count comes from the model string (`GetRoadsFromType`): 8 for
`A8-S5 A8-SE5 A8-SE8 A8-PRO5 A8-X5 A8-S6 A8-SE6 A8-PRO6 A8-X6 A8-HP6 A8-SEB A8-PROB A8-SE9 A8-PRO9 A8-SEB9 A8-PROB9`,
otherwise 6. The `B`-suffixed models (`A8-SEB`, `A8-PROB`, `A8-PROB9`) relabel the channels as
Blue1 / Blue2 / Warm / Olive / Blue3 / Purple / UV / White — same wire order, different LED binning.

> ⚠️ Confirm which `device.type` string your fixtures report before assuming a channel map. It
> decides both the channel count and the labelling.

### Scaling

```js
postVal = Math.round(1023 * percent / 100)
```

**Two scales.** The live single-channel command is 10-bit, 0–1023 (`b2=1023` = full; hardware-verified:
`b2=100` is visibly ~10 %). Everything else — levels and schedule rows in `read=config`, the `save=`
blob, and the multi-channel `preview=` command — is **0–100 %**.

---

## 2. Command grammar

One parser in firmware, two transports. The payload is always a query string.

### Live channel set

```
w=512        # white to 50 %
b2=1023      # deep blue to 100 %
uv=0         # UV off
```

⚠ Live sets are **not durable** — see §11 and §14.2. They are a preview until a `save=` follows.

### Other commands found in the app

| Command | Effect |
|---|---|
| `sta=getip` | Identity: `<ip>,<serial>,<flag>` — the app's own liveness check, works without an account |
| `preview=<hour>&w=<pct>&b=<pct>…` | Drive all channels at once, values 0–100 (untested on hardware — §15) |
| `sta=aplist` / `sta=apconnect&ssid=&pwd=` | Wi-Fi provisioning, served at `192.168.4.1` in AP mode |
| `read=config` | Dump full configuration (see §3) |
| `save=<blob>` | Write full configuration (see §4) |
| `reset=1` | Factory reset |
| `clock=<str>` | Set device clock |
| `version=<file>` | Trigger OTA firmware update |
| `node=restart` | Reboot the device |
| `mculed=on` / `mculed=off` | Status LED on the fixture |
| `turnoffset=0` / `turnoffset=1` | Fade behaviour toggle |

The integration never sends `reset=`, `version=` or `node=restart`.

---

## 3. `read=config` response format

A single `|`-delimited string:

| Field | Meaning |
|---|---|
| `[0]` | Device switch — `on` / `off` |
| `[1]` | Mode (`0` = manual/professional, `1` = auto/schedule) |
| `[2]` | `TempOn` — fan-on temperature (app writes 35) |
| `[3]` | `TempOff` — fan-off temperature (app writes 30) |
| `[4]` | `TempOut` — thermal cutoff (app writes 80; **firmware hard limit 84 °C**) |
| `[5 .. 5+n-1]` | **Stored** level per channel, 0–100 % (NOT live output — a live `?b2=1023` does not change it) |
| `[5+n .. 5+2n-1]` | 24 comma-separated points per channel (0–100) — the daily schedule curve |
| `[17+d]` | Heatsink temperature, °C |
| `[18+d]` | Device clock `"H,M"` |
| `[19+d]` `[20+d]` | Timer on / off hour (0 = unset) |
| `[21+d]` | Serial number |
| `[22+d]` | Intensity-knob flag |
| `[23+d]` | Timezone, UTC offset (factory **+8**) |
| `[24+d]` | Model string, e.g. `A8PRO6` |

`n` = channel count, `d = 2·(n−6)`. 8-channel reply = 29 fields, 6-channel = 25.
**Discriminator: more than 28 fields ⇒ 8 channels, otherwise 6.** A reply of just `A+` means "device
alive, no config" — the firmware also answers `A+` to every accepted live-set command.

Each schedule row is 24 values — one per hour — which the app interpolates into the curve it draws.
This is the whole photoperiod, readable and writable.

---

## 4. `save=` blob format

Built by `DevicesSave()` in `public.js`. Fields joined with `x`; commas inside schedule rows are
replaced with `y` to keep it URL-safe:

```
on x <mode> x 35 x 30 x 80 x <roadVal ×n> x <roadData ×n> x <openValue> x <closeValue> x <timeZone>
```

- `roadVal` — n stored levels in **percent 0–100** (verified on hardware 3 Sep 2026; the app copies them straight from `read=config[5..]`), each `x`-terminated
- `roadData` — n schedule rows of 24 values, commas → `y`, each `x`-terminated
- All commas in the final string become `y`
- Hardware-verified 3 Sep 2026: reply `true`; fan 65/50/75 can be passed through unchanged; mode 1 + tz `-4` works; the new timezone applies on the next `clock=`, so always send `clock=` after a save

> ⚠️ The app **always writes `on`** for field 0, never the real switch state — a deliberate
> workaround noted in its own source ("手动定时关闭时保存到设备无反应"). Preserve that behaviour;
> writing `off` here appears not to work.

> ⚠️ A 6-channel blob sent to 8-channel firmware is padded with `0x0x` after the 6 values and two
> rows of 24 zeros after the 6 schedule rows. Get the channel count right or the fixture
> misinterprets every field after the padding point.

---

## 5. Three routes to Home Assistant

Listed best-first. **Route A won** (§9); B and C are kept for the record and for anyone whose
firmware has closed port 80.

### Route A — local HTTP (no cloud at all) ★ chosen

```
GET http://<light-ip>/?w=512
GET http://<light-ip>/?read=config
```

The app still computes `serverUrl = "http://" + device.ip + "/"` unconditionally, and only *chooses*
MQTT when `device.ver.substr(0,4) > 2023`. The HTTP server is still present in current firmware —
the app simply stopped calling it.

Fully local, no cloud, no vendor account, no broker. Matches the build's "no proprietary apps or
cloud" rule outright.

### Route B — DNS redirect to local Mosquitto ★★ fallback if A ever closes

The lights connect *out* to `mqtt.doseen.com`, so a broker already running on the LAN can stand in
for it.

1. Point `mqtt.doseen.com` at that local broker via a DNS override (Pi-hole / AdGuard /
   router-level rewrite / dnsmasq).
2. Accept the vendor's global credentials on the local broker.
3. Subscribe `light/+/dev`, publish to `light/<SN>/mob`.
4. Firewall the lights from the internet entirely.

The lights end up talking to a broker inside the house, believing it is the vendor's. Fully local,
no vendor cloud, and it keeps the schedule/OTA machinery intact.

> Unknown: the device-side port. The app uses WebSocket 8083; the firmware almost certainly uses
> plain MQTT **1883** or TLS **8883**. A pcap of a booting light settles it (§6.3). If the firmware
> pins a certificate this route fails — but given the app uses unencrypted `ws://`, certificate
> pinning is unlikely.

### Route C — vendor cloud broker ✓ works, but cloud-dependent

Connect HA's MQTT client to `ws://mqtt.doseen.com:8083/mqtt` with the vendor's global credentials, publish
to `light/<SN>/mob`:

```json
{"type": "w512", "msg": "w=512"}
```

`type` is the msg with the `=` stripped (`order.replace("=","")`) — odd, but that is what the
firmware expects. Subscribe `light/<SN>/dev` for replies.

Depends on a Chinese cloud service and violates the project's no-cloud rule. Useful only to *prove
the command grammar* without hardware access.

### Topic reference

| Topic | Direction |
|---|---|
| `light/<SN>/mob` | app → device (commands) |
| `light/<SN>/dev` | device → app (replies, `{type, msg}`) |
| `dev/<SN>` | newer generic device topic |
| `mob/<clientId>` | newer generic app-reply topic |
| `wave/<SN>/…`, `water/<SN>/…` | other product lines, same scheme |

---

## 6. Hardware test plan — protocol discovery

*Historic: all four steps are done. For the tests that are still open — the ones about firmware
**behaviour** rather than protocol — see §14.6 and §15.*

### 6.1 Does the local HTTP server still exist? — do this first

With the lights online, from any machine on the LAN:

```bash
curl -s -m 5 "http://<light-ip>/?read=config"
```

- **Pipe-delimited string back** → Route A is live. Stop here; this is the whole answer.
- **Connection refused / timeout** → try a port sweep before concluding (§6.2).

Then a harmless live-control test:

```bash
curl -s "http://<light-ip>/?b2=1023"   # deep blue to full
curl -s "http://<light-ip>/?b2=0"      # and back off
```

### 6.2 Port sweep

```bash
nmap -Pn -p- --open <light-ip>
nmap -Pn -sU -p 1900,5353,6666,8080,8888 <light-ip>
```

Also worth capturing: MAC OUI (identifies the WiFi module vendor) and any mDNS/SSDP advertisement.

### 6.3 Where does the light actually connect?

Mirror the lights' traffic, or watch at the router, and capture a boot:

```bash
tcpdump -n -i <iface> host <light-ip> and not port 22
```

Looking for: the DNS query for `mqtt.doseen.com`, and the destination port that follows
(1883 plain / 8883 TLS / 8083 WS). That single fact decides whether Route B is a one-evening job.
**Moot as long as Route A holds, and moot in practice since 4 Sep — the fixtures are firewalled off
the internet (§7).**

### 6.4 Serial numbers

Needed for routes B and C. Visible in the AIPAI app's device list, and usually on the fixture label.

---

## 7. Security findings — worth acting on regardless

These are properties of the product, not of this build, but they bear on how the lights should be
treated on the network.

1. **Global hardcoded broker credentials.** One username/password pair is compiled into every copy
   of the app — recoverable in a few minutes from the decrypted bundle, and deliberately not
   reprinted here. There is no per-user or per-device secret.
2. **No transport encryption.** `ws://` on port 8083. Commands and configuration cross the internet
   in clear text.
3. **No device-level authorisation.** Anyone who knows a serial number can publish to
   `light/<SN>/mob` and control that fixture — including its schedule and OTA update command.
   Serial numbers appear to be sequential.
4. **Remote OTA is exposed on the same unauthenticated channel** (`version=<file>`).

**Recommendation — ✅ done 4 Sep 2026.** The three fixtures are firewalled off the internet
(pf block, alias `A8_Lights`; the already-established MQTT sessions had to be killed with
`pfctl -k` before the block took effect). Route A needs no outbound access at all. Given item 4,
this was worth doing independently of the HA integration.

---

## 8. Artefacts

| File | What it is |
|---|---|
| `3.1.82.apk` | AIPAI Android app, the analysis subject |
| `decrypt.py` | Dependency-free APICloud/uzmap RC4 decryptor |
| `dec/assets/widget/` | 136 decrypted app files — the readable source |
| `dec/assets/widget/script/public.js` | `SetDevOrder`, `DevicesSave`, MQTT connect — the core |
| `dec/assets/widget/ctrl-light.html` | Light UI: `deviceSyns` config parser, `mqttOrder`, channel map |
| `tools/a8_probe.py` | LAN probe — `sta=getip` + `read=config`, decodes all fields, `--set` / `--raw` / `--save-*` / `--dry-run`; refuses OTA/reset |
| `custom_components/aipai_a8/` | HA integration (§10, §11, §13.3) |
| `tests/run.py` | 39 assertions, no pytest, no network, no HA (§13.3) |
| `homeassistant/a8_lights.yaml` | YAML-package alternative (fallback, **not** installed — §10) |
| `homeassistant/reef_lights_2026-09-04.yaml` | The HA-side blocks from §13.5 |
| `REVIEW-2026-09-03.md` | Review of the original write-up — the corrections that went into the README (kept privately) |


Key source lines: `public.js:130` (broker + credentials), `public.js:442` (`SetDevOrder`, transport
switch), `public.js:538` (`DevicesSave`), `ctrl-light.html:410` (`serverUrl`), `:429` (`roadName`),
`:1391` (0–1023 scaling), `:1424` (`deviceSyns`).

---

## 9. Hardware confirmation (3 Sep 2026)

*Historic snapshot. Superseded in part by §11, §13 and §15.*

One fixture factory-reset, joined to the 2.4 GHz LAN, probed with `tools/a8_probe.py`:

```
LOCAL HTTP API IS ALIVE  →  http://<light-ip>:80/
sta=getip: ip=<light-ip> serial=<serial> flag=false
model=A8PRO6  serial=<serial>  channels=8  switch=on  mode=0 (manual)
temp=43.19°C  clock=7,14  timer on/off=0/0  tz=UTC8  fan on/off/cutoff=65/50/75
```

| Finding | Detail |
|---|---|
| Port 80 alive in station mode | On 2024 firmware. Route A is the answer; B and C are moot. |
| Live set scale | `b2=1023` bright, `b2=100` ≈ 10 %, `b2=512` half. 0–1023 as documented. |
| Reply to a set | `A+` — acknowledgement. |
| Read-back | `read=config` shows **stored** levels (50 after `b2=1023`). HA must own live state. |
| Factory defaults | tz UTC+8 (schedule would run on Beijing time), fan 65/50/75 (app overwrites with 35/30/80 on save), manual mode, all channels 50 %. |
| Heatsink temp | 43 → 50 °C over ~2 h at ≥50 %, no water under it. Fan on at 65. |
| Persistence | Live sets *appear* to hold, and a reboot restores stored levels. Light 3 rebooted at 21:13 on 3 Sep right after two presets fired 48 commands in 3 s → came on by itself at night. ⚠ **The "live sets hold" half of this was wrong** — see §11 and §14.2: the firmware re-applies its stored config on a timer, so they decay even without a reboot. |
| Lights 1 & 2 | Added later, by IP. |

Other LAN hosts may answer on port 80 with non-config pages — the probe only
counts a `|`-delimited reply.

---

## 10. Home Assistant — the first install (3 Sep 2026)

*Historic snapshot of v0.1.x. Superseded by §11 (v0.2.1), §13.3 (v0.2.3) and §15.*

**`custom_components/aipai_a8/`** (in the repo, HACS custom repository). Installed on HA 2026.9.0, added by IP,
first try — one device per fixture.

| Entity | Notes |
|---|---|
| `light.*_master` | Whole-fixture on/off + proportional dimmer. `effective = setpoint × master %`; sends one `?ch=` per channel. |
| `light.*_white … _warm_white` | 8 channel dimmers. Assumed state, restore on restart, seeded from stored config on first add (50 % each). |
| `sensor.*_temperature` | From `read=config` every 60 s; displays °F because HA is imperial (121.9 °F = 49.9 °C). |
| `sensor.*_mode` | `manual` / `schedule`. |
| `sensor.*_device_clock`, `_device_timezone`, fan thresholds | Diagnostic. |
| `button.*_push_levels_to_light` | Resend every channel — after a power loss. Inert in schedule mode since v0.2.3 (§13.3). |
| `button.*_sync_clock` | `clock=<epoch>`. |

Design notes: `api.py` has no HA imports (unit-tested against the real 29-field reply); coordinator
tolerates a transient `A+` to a poll by keeping last data instead of going unavailable; never sends
`reset=`, `version=`, `node=restart`.

The earlier YAML package (`homeassistant/a8_lights.yaml`, `rest_command` + template lights) also works
and is kept in the repo as a fallback; it was removed from `/config/packages/` once the integration
went in, so two controllers do not fight over one light. Lesson from that install: the legacy
`light: - platform: template` form was removed in current HA — template lights must live under
`template:`.

All three fixtures added, each by its own LAN address (entity prefix `<area>_a8_pro_light_N_`).

### Reef Command → Lighting tab (`/reef-command/lighting`)

| Section | Contents |
|---|---|
| Day Cycle | `input_boolean.reef_lights_schedule`, `input_number.reef_lights_peak_intensity`, `input_datetime.reef_lights_{sunrise,full_day,sunset,night}`, template sensors `reef_lights_{phase,next_change,day_length,full_intensity_hours}`, 24 h intensity graph |
| Spectrum Presets | Tiles → `script.reef_spectrum_apply` with channel ratios; `input_select.reef_spectrum_preset` records the active one |
| Light 1 / 2 / 3 | Master + 8 colour-matched inline sliders + Push button; temp/mode badges. Compact rows for portrait iPad |
| Spectrum — 24 h | Three history-graphs (one per light) of `sensor.reef_light_N_<channel>` template helpers (effective %) |

### Automation `automation.reef_lights_photoperiod` (v0.1.x form — superseded)
Every 5 min + on any Day Cycle helper change, if schedule on: master target = linear ramp
sunrise→full (0→peak), flat peak full→sunset, linear sunset→night (peak→0), off outside. Drives the
three masters only; channel ratios are the spectrum.

### Script `script.reef_spectrum_apply` (fields preset, w b r g b2 p uv wm)
Sets channel set points on all three lights. **Original preset list, superseded by §12:**
AB+ 24/100/24/24/100/100/100/24 · PHX14 24/100/30/18/100/100/100/24 · LPS 15/100/25/20/100/100/100/15 ·
Color 55/100/40/23/100/100/100/55 · Full Spectrum all 100 · Moonlight 0/10/0/0/30/10/0/0.

Gotcha: the HA dashboard editor saves its whole stale copy on exit — close the editor before agent
writes, or they get reverted.

> The "Next:" list that stood here (verify persistence across a day; Custom detection; finer ramp)
> is resolved — persistence turned out to be the §11/§14 re-apply finding, Custom detection shipped
> in §12, and the ramp question died with the 5-minute polling. Live open items are in §15 only.

---

## 11. `save=` verified; the light runs its own photoperiod (3 Sep 2026, late)

*Supersedes the v0.1.x parts of §9–§10. Integration state here is v0.2.1; see §13.3 for v0.2.3.*

Blob format exactly as §4. Reply `true`. Fan thresholds pass through unchanged. Mode 1 with tz `-4`
works, and **the timezone only takes effect on the next `clock=`**, so the integration always sends
`clock=<epoch>` immediately after a save. A light parked in mode 0 with all channels 0 stayed dark for
more than 10 minutes with no HA nagging — the crutch is gone.

The finding that forced this: **live sets are temporary.** The firmware re-applies its stored config
every few minutes, so anything sent with `?w=`/`?b2=` is a preview. Only `save=` persists. The
one-minute "hold levels" automation that papered over this has been deleted. The consequences for the
master slider are worked out in §14.

### Integration v0.2.1

- `api.py`: `build_save_blob`, `blob_from_config`, `photoperiod_points`, `scale_points`, `tz_string`,
  `A8Client.save_config`.
- `coordinator.py`: `save_schedule`, `save_manual`, `sync_clock`; the reconnect re-send is skipped when
  the light is in schedule mode (it is already doing the right thing).
- Services: `aipai_a8.set_schedule` (device_id, sunrise/full_day/sunset/night, peak, optional ratios —
  default = HA's channel set points) and `aipai_a8.set_manual` (device_id, levels | off: true).
- `tools/a8_probe.py`: `--save-level CH=PCT`, `--save-mode`, `--save-tz`, `--save-schedule CH=24pts`,
  `--dry-run`; asks before writing.
- **v0.2.1 (reply sanity checks).** Two lights each answered one poll with the temperature field
  zeroed, seconds apart, and it landed in HA history as a 32 °F spike. The client now rejects a config
  string with fewer than 25 fields (parsing a truncated reply shifts every field after the schedule
  block), discards a heatsink reading outside 1–120 °C and holds the previous one, and ignores a reply
  whose serial does not match the fixture. Last good data stands until the next poll.

### Home Assistant objects introduced here

- Day cycle helpers: schedule toggle, peak intensity, sunrise / full day / sunset / night.
- `script.reef_lights_save_schedule` — calls `set_schedule` on all three devices from those helpers.
- `automation.reef_lights_photoperiod` — no more 5-minute polling; re-saves on schedule→on, on any
  helper change, on HA start, and daily at 03:30 (DST).
- `automation.reef_lights_schedule_off` — masters off + `set_manual off`.
- `automation.reef_spectrum_detect_custom` — sets `input_select.reef_spectrum_preset` to Custom when a
  channel set point is changed by hand. (The context test described here was wrong; see §12.)
- Lighting tab: the Day Cycle graph is an apexcharts card rendering the **saved curve** — a smooth
  "Planned (HA)" area plus the 24 hourly points the firmware actually stores, which shows how much the
  hourly quantisation rounds off an 11:45 sunrise. The old history graph of HA's master intensity was
  meaningless in schedule mode, since HA never sees the light's own ramp.


> The helper values and "physical state" recorded here (peak 70, spectrum AB+) are a 3 Sep snapshot
> and no longer hold. Current values are in §15.1 only.

---

## 12. Spectrum presets — Custom button, highlight, and one HA lesson

### Objects

| Object | Role |
|---|---|
| `input_select.reef_spectrum_preset` | The active preset name — **4 options: Default, 100% White, Moonlight, Custom** |
| `input_text.reef_spectrum_default` | The Default ratios, editable at runtime |
| `input_text.reef_spectrum_custom` | Last hand-tuned spectrum, 8 comma-separated percentages |
| `input_boolean.reef_spectrum_applying` | On while a preset script writes set points; suppresses the detector |
| `script.reef_spectrum_apply` | Writes the 8 ratios to all three lights, records the preset, re-saves the schedule if it is on. `continue_on_error` on the light calls so one unreachable fixture does not abort the other two |
| `script.reef_spectrum_apply_default` / `_save_default` | Apply the Default helper / write Light 1's current set points into it |
| `script.reef_spectrum_recall_custom` | Re-applies the stored custom string; notifies if none saved |
| `automation.reef_spectrum_detect_custom` | Hand edit → snapshot that light's 8 set points + flag Custom |
| `automation.reef_spectrum_clear_stuck_applying_flag` | Clears the guard flag if it sticks on for 5 min |

Lighting tab: preset tiles on the section's 36-column grid, each with a card-mod style that draws a
border and tint on the tile matching the active preset. Inactive tiles are left completely alone — a
dimmed/greyed treatment was tried on 3 Sep and rejected for draining the colour out of the row.

### Lesson: HA context does not distinguish a script's writes from a user's

A script invoked by a user service call runs **in that user's context** and passes the same
`{id, user_id, parent_id}` into every service call it makes. So
`trigger.to_state.context.parent_id is none` is true for both a hand slider move and a preset script's
writes — it cannot be used to tell them apart. `parent_id` is only set for automation/trigger-spawned
contexts. The working pattern is an explicit guard boolean held on for the duration of the writing
script, checked by the detector both at trigger time and again after its debounce delay, plus a
watchdog automation so a crashed writer cannot leave the guard stuck on.

### Hardware: the burst reboot reproduced

Light 3 dropped out again during this session after several `reef_spectrum_apply` runs in quick
succession (each 24 paced writes across three fixtures), and returned about two minutes later dark
and correct from its stored manual/all-zero config. The 150 ms intra-run pacing does not protect
against stacked runs — **leave a minute or two between full preset applies.**

### The preset set (supersedes the ratio lists in §10)

Four presets, one row: **Default** · **100% White** (all 100, the former Full Spectrum) ·
**Moonlight** `0,10,0,0,30,10,0,0` · **Custom** (recalled from `input_text.reef_spectrum_custom`).
AB+, PHX14, LPS and Color were removed from both the tiles and the `input_select` options.

⚠ **Default's ratios live in a helper, not in this document.** Verified live 5 Sep 2026,
`input_text.reef_spectrum_default` = `35,100,10,20,100,100,90,15`, and Light 1's white set point
reads 35 to match. **`script.reef_spectrum_apply_default` still carries `25,100,10,20,100,100,90,15`
as its hardcoded fallback** — a stale literal that only shows up if the helper is ever emptied.
Worth correcting in code; tracked in §15.2.

Adding a preset is three edits: the name into `input_select.reef_spectrum_preset`'s options, a tile
whose `tap_action` calls `script.reef_spectrum_apply` with the eight ratios in `data`, and a copy of
the card-mod highlight style with that name substituted.

Dashboard tab order changed on 3 Sep: the Lighting view is `views[3]`. Locate cards by search rather
than by a remembered index.

### Editable Default, and the native-types gotcha

Default's ratios moved out of the dashboard tile into `input_text.reef_spectrum_default`, so they can
be re-saved at runtime: `script.reef_spectrum_apply_default` reads the helper, and
`script.reef_spectrum_save_default` writes Light 1's current set points into it. The Default tile taps
to apply and **holds** to save, behind a confirmation dialog. Same shape as Custom — a preset is a
helper plus two scripts plus a tile.

**HA gotcha worth remembering:** a `variables:` block renders templates to *native Python types*, so a
template producing `"35,100,10,..."` comes back as a tuple and `.split(',')` raises
`'TupleWrapper' object has no attribute 'split'` — inside an `if` condition that failure is silent and
the else branch runs. Service-call `data:` fields keep the string. Keep such a value as a list in
variables and `| join(',')` only where it is consumed.

The four Day Cycle time tiles also highlight the active phase from `sensor.reef_lights_phase`
(states: `Sunrise` / `Day` / `Sunset` / `Night` — the "Full day" tile matches `Day`).

The Default slot is two tiles in one grid position, switched by HA's native per-card `visibility`
conditions: "Default" when the preset is anything but Custom, "Hold to save as Default" when it is
Custom. Same tap/hold actions on both. `visibility` is core HA and works on any card in a sections
view — the cheap way to make a card state-dependent without a templating custom card.

### Two dashboard caveats that will look like bugs

**Card-mod needs a refresh after a config write.** Card-mod attaches its styles when a card is built,
so pushing a new dashboard config into an already-open tab can leave the preset/phase borders (and the
centred chart title) missing. The styles are intact in storage; Cmd/Ctrl+Shift+R restores them. The
tell is that *all* card-mod styling is absent at once. This is accepted, not outstanding: the
alternative (native visibility pairs that grey out inactive tiles) was built and reverted because it
drained the colour out of the row.

**ApexCharts measures its container once.** With `grid_options: {rows: auto}` the grid cell has no
definite size at render time and Firefox resolves that differently from WebKit, so the chart can latch
onto ~40 % width and never re-measure. Fixed `rows: 4` plus `width: "100%"`,
`redrawOnParentResize` and `redrawOnWindowResize` in `apex_config.chart` settles it.

Also: apexcharts-card has no top-level `title:` key (that errors as extraneous). The card heading is
`header.title`, centred with card-mod on `#header` / `#header__title`; ApexCharts' own
`title: {text, align}` lives under `apex_config` and draws inside the plot area instead.
---

## 13. The write path — how a healthy fixture stayed dark (4 Sep 2026, late)

Raised as "the lights are still a little weird", investigated from live HA state and the automation
traces. It is a *fourth* failure mode, independent of the three in §14.1, and it is the one that was
actually biting.

### 13.1 What happened

| Time | Event |
|---|---|
| 13:01 | `automation.reef_lights_schedule_off` ran → all three fixtures manual, saved 0 %, masters off |
| 14:12 | Masters turned on 100 % in HA (a live set — never reached flash) |
| 18:39:38 | `input_boolean.reef_lights_schedule` → **on** |
| 18:39:41 | `automation.reef_lights_photoperiod` fired, waited 3 s, called `script.reef_lights_save_schedule` |
| 18:39:47 | Script **errored**: `<light-1-ip>: read before save failed: http://<light-1-ip>/?read=config:` |
| 18:44 | All three fixtures still `manual`, stored 0 %; heatsinks 80–81 °F. Tank dark. Dashboard: schedule on, phase `Day`, peak 25 %, masters on 100 % |

A retry at 18:48 failed the same way — but on the second fixture, having got past the first. Light 1 came up in
schedule mode; lights 2 and 3 did not. Calling `aipai_a8.set_schedule` once per device, spaced,
wrote all three.

### 13.2 Two causes, both in the write path

**A stalled request is fatal.** `A8Client._get` had a 5 s timeout and no retry. `read=config` and
`save=` carry the whole configuration and the firmware's single-threaded HTTP server is visibly
slower over them than over a live set, so under any concurrent load — a poll landing on one fixture
while another is being written — the read times out. The give-away in the log is a message ending in
a bare colon: `asyncio.TimeoutError` stringifies to `""`. Same class of bug as the NaN masking in
the build's private master reference (NaN-masking lesson) and the zeroed-temperature spike in v0.2.1 — the failure was real,
the report was useless.

**One fixture's failure cancelled the others.** `set_schedule` and `set_manual` take a device list,
and `_svc_*` looped and raised on the first error. Everything after the failing fixture was silently
skipped. `script.reef_spectrum_apply` had already learned this lesson and carries
`continue_on_error`; the schedule path had not.

The two compound: a one-in-ten stall on any one of three fixtures becomes a coin flip on the whole
photoperiod write, and the only visible symptom is a dark tank with a dashboard insisting otherwise.

### 13.3 Integration v0.2.3

- **Retry.** `_get` retries a connection failure once (`RETRY_ATTEMPTS = 2`, `RETRY_BACKOFF = 0.8 s`),
  inside the per-host lock so a poll cannot slip between the attempts. Every command in this protocol
  is idempotent by content — the same channel value, the same `save=` blob, the same clock — so a
  repeat is safe; a retried `save=` that had actually landed costs one extra flash write, not a wrong
  configuration.
- **`CONFIG_TIMEOUT = 12 s`** for `read=config` and `save=`; short commands keep the 5 s budget.
- **Error messages that say something.** Timeouts read `timed out after 12s`; exception classes that
  stringify to `""` (`ServerDisconnectedError` among them) are named.
- **Per-fixture isolation.** `_apply_each` runs the action against every fixture, collects failures
  and raises one error at the end naming the hosts that failed and the tally. `DEVICE_SPACING = 1.0 s`
  between fixtures — three back-to-back configuration writes over one 2.4 GHz radio is the pattern
  behind both the timeouts and the burst reboot.
- **A failed pre-save read no longer aborts the save.** `_save` falls back to the last good poll. The
  only fields it supplies are ones the integration does not change (fan thresholds, timers, and
  whichever of levels/schedule is not being written), at most one poll interval stale. It still
  refuses if there is no cached config at all.
- **Live sets are suppressed in schedule mode.** The firmware ignores them while running its stored
  curve, so `push_channel` / `push_all` update the model and send nothing — 24 pointless requests
  removed from every master move and from `reef_lights_schedule_off`. `button.*_push_levels_to_light`
  now says so instead of looking like it worked.
- **`binary_sensor.*_stored_config_differs`** (diagnostic, device class `problem`) — §14.7 option 2.
  On when the fixture's stored levels disagree with HA's believed effective levels by more than 2
  points, in manual mode. Attributes carry `mode`, `believed_pct`, `stored_pct`, `differing_channels`,
  `worst_gap_pct`. It reads `unknown` in schedule mode, where HA's live model does not apply.
  **It will come on the moment a master moves in manual mode — that is the finding, not a false
  positive.** A live set never reaches flash, so the fixture will revert at its next re-apply.
- **`tests/`** — 39 assertions, no pytest, no network, no Home Assistant. `tests/stubs/` holds just
  enough of `homeassistant` and `voluptuous` to import the modules; `fake_aiohttp.py` replays scripted
  outcomes so the stalled read and the empty-message disconnect reproduce deterministically. Run with
  `python3 tests/run.py`.

### 13.4 What this does *not* fix

§14.7 option 1 — making a manual master persist by routing it through `save=` — is still open, and is
still the user-visible bug. Deliberately deferred: it would put a debounced flash write on top of a
write path that was, until v0.2.3, losing whole requests. Fix the transport, watch the new mismatch
sensor for a day, then decide. §14.6 test C (does `set_manual` with levels survive the re-apply timer
and a reboot?) is what gates it.

Also unchanged: the re-apply interval is still unmeasured (§14.6 test A), and `preview=` is still
untested (§14.6 test B) — it would make a master change one request instead of eight, which matters
more now that the burst pattern has been implicated twice.

### 13.5 Dashboard and wording

`homeassistant/reef_lights_2026-09-04.yaml` carries the HA-side blocks: `continue_on_error` on the
photoperiod's save, masters set to peak on schedule→on (free in v0.2.3, since it sends nothing on the
wire — do **not** backport it, it would have been 24 inert writes), native `visibility:` so the peak
slider shows only in schedule mode and the masters only in manual, and a mismatch card that appears
only when something is wrong.

And retire "freeze": `input_boolean.reef_lights_schedule` off is **manual, saved dark**.
`automation.reef_lights_schedule_off` has parked the fixtures dark since it was written; the
"freeze" language predates it.

### 13.7 The dashboard now saves, and says whether it worked

*(§13.6, §13.8 and §13.9 of the master are omitted here — repo housekeeping, a git-history
cleanup, and a private link. No protocol content.)*

The gap v0.2.3 left behind: nothing on the dashboard could make a manual look permanent, and a
hand-moved colour slider in schedule mode never triggered a re-save. Both needed a service call from
Developer Tools, which is how a step gets skipped.

**`script.reef_lights_save_to_lights`** — one button, mode-aware, self-verifying.

- Schedule **on** → `script.reef_lights_save_schedule` (rewrites curve + current spectrum)
- Schedule **off** → `aipai_a8.set_manual` on all three, no levels (stores what HA is showing)
- Then `delay: 12 s` and a native state condition against the roll-up sensor below, so a save that
  reached only some of the three is reported rather than assumed. The failure notification names the
  fixtures still in the wrong state. **This is the check that would have caught §13.1 in one press.**
- Both service calls carry `continue_on_error: true` so the verification branch always runs.

Two roll-up helpers, both created through the config flow (not YAML), so they stay UI-editable:

| Entity | Type | Reads |
|---|---|---|
| `binary_sensor.reef_lights_unsaved` | group of the three `*_stored_config_differs`, any-on | `OK` / `Problem` (device class `problem`) |
| `binary_sensor.reef_lights_curve_loaded` | template, all three `*_mode` sensors equal `schedule` | `Running` / `Not running` (device class `running`) |

Both needed an explicit `device_class` set through the entity registry — a bare binary sensor renders
`On`/`Off`, which reads as nonsense on a status tile.

⚠ `reef_lights_unsaved` is `unknown` in schedule mode, because the per-fixture mismatch sensor
returns None there. That is why the dashboard pairs it with `curve_loaded` by mode rather than
showing one status everywhere.

#### Lighting tab, Spectrum Presets section (`views[3].sections[1]`)

Final shape after a compaction pass — **one heading, one row of tiles**:

- Heading `Spectrum Presets`, badges: active preset, plus a mode-switched status badge
  (`unsaved` when schedule off, `curve_loaded` when on)
- Five tiles filling the 36-column grid: four presets at `columns: 7` + the Save tile at `columns: 8`
- The Save tile is a `visibility` pair on `input_boolean.reef_lights_schedule` — *Save curve to
  lights* / *Save levels to lights* — with a per-mode confirmation dialog, and a card-mod amber
  border while a save is outstanding

The first version used a `Save to the Lights` subtitle heading and two 18-column status tiles on
their own row. That was three rows for what one row now carries: **the status belongs on the heading
as a badge, not as a tile.** Worth remembering for the next section that wants a state readout.

Edits were made with `ha_config_set_dashboard(python_transform=...)` addressing
`config['views'][3]['sections'][1]`, which is additive and surgical — no full-config replacement, and
the dashboard editor was closed throughout (§12's stale-copy gotcha).

⚠ The config hash moved between two of those writes without anyone editing on purpose — same
unidentified writer noted against the repo. Always re-fetch the hash immediately before a transform.


---

## 14. Master vs Peak vs Schedule: how they actually interact (4 Sep 2026, earlier)

*Written from live HA state and the integration/automation configs, after "we need to check Master
switch behavior — not what I expected". This section is the finding; §13 is the sequel that fixed the
transport underneath it. Numbered §14 rather than §13 so the already-published §13 numbering does not
move. Background lives in the build's private notes.*

### 14.1 The three findings

**1. HA's master slider is a belief, not a readback, and in manual mode the fixture silently walks
away from it within about 5–10 minutes.** Turn a master on, the light comes on, then goes dark by
itself while HA still reads 100 %. That is the firmware re-applying its **stored** config — and the
stored config was 0 %, because the last `set_manual off` saved it dark.

**2. Peak intensity and the master never both apply.** Peak governs schedule mode only; the master
governs manual mode only. Nothing on the dashboard said so — fixed in §13.5 with native `visibility:`.

**3. The schedule toggle is asymmetric.** Off → masters off *and* fixture saved dark. On → the curve
is written, but the masters are left wherever they were. So off→on left HA showing masters off while
the tank was lit — fixed in §13.5 by setting the masters to peak on schedule→on.

§13 is a **fourth**, independent failure mode: the write itself could be lost.

### 14.2 The three controls, precisely

| Control | Entity | What it governs | When it does nothing |
|---|---|---|---|
| **Master** | `light.<area>_a8_pro_light_{1,2,3}_master` | Live multiplier — `effective = setpoint × master %`, written as per-channel 0–1023 **live** sets. `assumed_state: true`, attributes `master_pct`, `channels` | In schedule mode (firmware runs its stored curve and ignores live sets). In manual mode it **decays** — see §14.3 |
| **Peak intensity** | `input_number.reef_lights_peak_intensity` | The ceiling of the 24-point curve that `aipai_a8.set_schedule` writes into the fixture | Whenever `input_boolean.reef_lights_schedule` is off. **No effect at all** in manual mode |
| **Schedule** | `input_boolean.reef_lights_schedule` | On → `automation.reef_lights_photoperiod` waits 3 s, runs `script.reef_lights_save_schedule` → `set_schedule` → fixture mode 1, runs the curve itself. Off → `automation.reef_lights_schedule_off` | — |

Supporting mechanics already established on hardware:

- **Two scales.** Live single-channel set is `0–1023`; everything *stored* (levels, the 24 hourly
  points, the `save=` blob) is `0–100 %`. (§1)
- 🔑 **Only `save=` persists.** `?w=` and friends are a preview. The firmware re-applies its stored
  config on its own timer — observed twice on 09/03, lights set to 0 came back on by themselves
  after ~5–10 min with no reboot.
- **`read=config` returns stored levels, not live output.** After `b2=1023` it still read 50.
- A reboot also restores stored levels.

### 14.3 The master decays — evidence, 4 Sep 2026

| Time | Observation |
|---|---|
| 13:00 / 13:01 | `script.reef_lights_save_schedule` then `automation.reef_lights_schedule_off` both ran → fixtures left **manual, saved at 0 %**, masters off. Heatsinks ~79 °F (room temp) |
| 14:12 | Masters turned **on, 100 %** (`light.*_master` last_changed 14:12:29). Channel set points hold Default `35,100,10,20,100,100,90,15`; `light…_blue` and `…_deep_blue` report `setpoint_pct: 100`, `effective_pct: 100`, `raw_value: 1023` |
| 17:40 | Dashboard screenshot: heatsinks **86.5 / 86.9 / 86.5 °F** — the fixtures were lit and warming |
| ~18:00 | Heatsinks **82.85 / 83.93 / 83.71 °F** — falling, while HA still reads master on / 100 % and every channel `effective_pct: 100` |

Heatsinks rising ~7 °F after the masters went on and then falling again with no HA-side change is
the fixtures reverting to their stored (dark) config. **HA's state never moved, because the master
light is `assumed_state` and nothing reads the fixture back.**

⚠ This is not the same as "lights are off." It is worse: **HA and the fixture disagree and neither
side reports it.** Same family as the NaN-masking lesson (the build's private master reference (NaN-masking lesson)) and the
v0.2.1 reply sanity checks — a wrong-but-confident value is more dangerous than a missing one.
`binary_sensor.*_stored_config_differs` (§13.3) is the answer to the reporting half.

**Confidence:** high on the mechanism (it matches the §9 persistence finding, reproduced twice on
09/03, plus the thermal curve here); **not yet reproduced under controlled timing** — §14.6 test A.

### 14.4 The schedule toggle is asymmetric

```
automation.reef_lights_schedule_off   (trigger: schedule -> off)
  1. light.turn_off  on all three masters
  2. aipai_a8.set_manual  device_id: [1,2,3]  off: true     # saves the fixture dark, mode 0

automation.reef_lights_photoperiod    (trigger: schedule -> on, any helper change, HA start, 03:30)
  condition: schedule is on
  1. delay 3 s
  2. script.reef_lights_save_schedule                        # writes curve + mode 1
     # masters were NOT touched  -- fixed in §13.5
```

Consequences:

1. **off → on**: the fixture starts running the curve and lights up; HA's masters were still off from
   the last schedule-off. The dashboard read dark, the tank was lit. Nothing wrong on the light — the
   HA model was just stale. **Fixed in §13.5**: photoperiod now sets the masters to peak on
   schedule→on, which is free because live sets are suppressed in schedule mode.
2. **on → off**: correct and deliberate — parks the fixture dark through reboots with no polling.
3. Moving the master while the schedule is **on** does nothing durable: the fixture is in mode 1 and
   re-applies the curve. The coordinator already skips its reconnect re-send in schedule mode
   (correct); the master slider is simply live in the UI and inert on the hardware. Since v0.2.3 it
   does not even reach the wire.
4. `input_boolean.reef_lights_schedule` off is documented as **freeze, not off** — but
   `reef_lights_schedule_off` does in fact park the lights dark. The "freeze" language predates that
   automation and is retired (§13.5): **schedule off = manual, saved dark**.

### 14.5 What is wrong, ranked

1. 🔻 **The master does not persist.** A manual master change is a live set only, so it is undone by
   the firmware's own re-apply timer. **Still open** — this is the user-visible bug. §14.7 option 1.
2. ✅ **Nothing detects HA/fixture disagreement.** Fixed by `binary_sensor.*_stored_config_differs`
   and the two roll-ups (§13.3, §13.7).
3. ✅ **Peak and master indistinguishable on the dashboard.** Fixed by native `visibility:` (§13.5).
4. ✅ **off → on leaves the masters stale.** Fixed (§13.5).
5. ✅ **Docs say "freeze"** where the behaviour is "park dark". Retired (§13.5).

### 14.6 Tests to run on hardware (in order)

**A. Confirm the decay, with timing.** Schedule off, mode manual. Set master 1 → 100 %. Sample every
2 min for 20 min: `read=config[5..12]` (stored levels), the channels' `raw_value`, and the heatsink.
Expect stored levels to stay 0 and the fixture to go dark at the first re-apply. **Record the
re-apply interval** — it is the number that decides the §14.7 design.
⚠ One fixture at a time, and leave a minute or two between full preset applies (burst writes reboot
a fixture — reproduced twice on 09/03, §12).

**B. `preview=` on hardware.** Still untested. `preview=<hour>&w=<0-100>&b=…` sets all channels in
one call instead of eight — directly relevant to the burst-reboot problem, and it would make a
master change one HTTP request. Test on Light 3 first (the one that has already rebooted once).

**C. Does `set_manual` with levels persist a master?** `aipai_a8.set_manual` already takes
`levels`. Verify that a save-backed manual write survives the re-apply timer and a reboot. If it
does, §14.7 option 1 is a small change. **This test gates option 1** (§13.4).

**D. off → on with masters off.** Confirm §14.4.1 end to end. *Largely obsolete since §13.5 sets the
masters on schedule→on, but still worth one pass to confirm the display now matches the tank.*

### 14.7 Proposed fixes (decide after tests A and C)

**Option 1 — make manual persist (recommended, still open).** Route master and channel writes through
`save=`/`set_manual` rather than live sets, debounced ~2–3 s so a slider drag is one flash write,
not thirty. Cost: flash writes on manual changes only; manual is an override mode, not the running
state, so volume is low. This makes HA's master mean what the UI implies.
⚠ Reuse the existing `input_boolean.reef_spectrum_applying` guard pattern — **HA context cannot
distinguish a script's writes from a hand edit** (§12), so any new writer of set points needs the
same flag or `automation.reef_spectrum_detect_custom` will fire on it.

**Option 2 — surface the disagreement. ✅ shipped in v0.2.3** as
`binary_sensor.*_stored_config_differs` plus the two roll-ups (§13.3, §13.7). Keep it even after
option 1 lands: it is the check that proves option 1 kept working.

**Option 3 — dashboard only, no code. ✅ shipped** (§13.5): native `visibility:` on
`input_boolean.reef_lights_schedule` hides the master in schedule mode and peak in manual. Documents
the trap rather than fixing it, which is why option 1 is still open.

**Also ✅ done:** `reef_lights_photoperiod` sets the masters to peak on schedule→on (§13.5), and
"freeze" is corrected to "manual, saved dark" everywhere.

### 14.8 Standing facts

- `effective = setpoint × master %`. **A dark fixture still reads "channels on"** — the eight channel
  entities sit at `on` with a set point while `effective_pct` is 0. Judge dark-or-lit by the master,
  and after the §14.3 finding, by the heatsink trend rather than by HA alone.
- ✅ DHCP reservations made for all three fixtures 09/04, and ✅ firewalled off the internet the
  same day (pf block; existing MQTT sessions had to be killed first).
- Never send `reset=1`, `version=`, `node=restart`.
- ✅ HACS now resolves a Release, not a commit hash — v0.2.2 and v0.2.3 both published (§13.6). A tag
  alone does nothing.

---

## 15. Current state and open items

**Supersedes every earlier "Still open" / "Next" / "Physical state" list in this document.**

### 15.1 Live state — read from Home Assistant 5 Sep 2026, 00:40 ET

| | |
|---|---|
| Integration | `aipai_a8` v0.2.3, HA 2026.9.0, three devices |
| Fixtures | Three, each addressed by its own LAN address |
| Mode | All three **manual** |
| Masters | All three **off**, `master_pct` 50, every channel `effective_pct: 0` / `raw_value: 0` |
| Stored levels | All channels 0 on all three — **parked dark**, tank still being plumbed |
| Heatsinks | 81.6 / 82.0 / 81.7 °F — room temperature, confirming dark |
| Device clock / tz | 00:36 · 00:36 · 00:37, all `UTC-4` — in sync with local time |
| Schedule toggle | **off** |
| Peak intensity | **25 %** (was 70 on 3 Sep) |
| Day cycle | sunrise 11:45 · full day 15:45 · sunset 20:45 · night 00:45 → 13 h photoperiod, 5 h at peak. `sensor.reef_lights_phase` = `Sunset` |
| Preset | **Default** = `35,100,10,20,100,100,90,15` (helper `input_text.reef_spectrum_default`) |
| Custom slot | `input_text.reef_spectrum_custom` = `100,1,1,1,1,1,1,100` |
| `binary_sensor.reef_lights_unsaved` | **off** — HA and all three fixtures agree |
| `binary_sensor.reef_lights_curve_loaded` | **off** — expected, schedule is off |
| Per-fixture `*_stored_config_differs` | all **off** (believed 0, stored 0) |

### 15.2 Open

| # | Item | Where |
|---|---|---|
| 1 | 🔻 **A manual master still does not persist.** Route it through `save=`, debounced. Gated on test C. | §14.7 opt 1, §13.4 |
| 2 | **Test A — measure the re-apply interval.** The number that decides the option 1 design. | §14.6 A |
| 3 | **Test B — `preview=` on hardware.** One request instead of eight; the burst pattern has been implicated twice. | §14.6 B |
| 4 | **Test C — does `set_manual` with levels survive the re-apply timer and a reboot?** | §14.6 C |
| 5 | **Test D — off→on display honesty**, one confirming pass now that §13.5 sets the masters. | §14.6 D |
| 6 | `script.reef_spectrum_apply_default` hardcodes `25,100,10,20,100,100,90,15` as its fallback; the helper holds `35,…`. Stale literal. | §12 |
| 7 | "Spectrum — last 24 h" history graphs still plot HA's model; in schedule mode they show what HA sent, not what the light ran. | §11 |
| 8 | An unidentified writer moves the dashboard config hash. Always re-fetch immediately before a transform. | §13.7 |

### 15.3 Standing rules

- **Only `save=` persists.** Live sets are a preview.
- **Never** send `reset=1`, `version=`, `node=restart`.
- **Leave a minute or two between full preset applies** — stacked bursts reboot a fixture (twice).
- **Close the HA dashboard editor before any agent write**, or it saves its stale copy over the top.
