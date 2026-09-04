# A8 Pro II — Control Protocol Reference

*Reverse-engineered from AIPAI Android app v3.1.82. Companion to `AquaPiMasterReference.md` §13.2 / §13.7
("Lighting is not yet in HA").*

Status (3 Sep 2026): **Route A confirmed on hardware and running in Home Assistant.**
Light 3 (A8 Pro II, firmware model `A8PRO6`, serial 3156988, 192.168.1.208) answers on port 80 in
station mode. A custom integration (`aipai_a8`) is installed via HACS and shows as one device,
"A8 Pro Light 3". See §9 for what was learned on hardware and §10 for the HA integration.
Public repo: https://github.com/kenbrinkman/A8-Pro-II-Control

---

## 0. Executive summary

| Question | Answer |
|---|---|
| Is there a local (no-cloud) control path? | **Yes — confirmed.** An HTTP server on the light, port 80, alive in station mode on 2024 firmware. The app only *uses* it for ≤2023 firmware and in "direct link" AP mode, but it is always there. |
| Cloud transport | MQTT over **plain WebSocket**, `ws://mqtt.doseen.com:8083/mqtt` — **no TLS** |
| Cloud auth | Hardcoded global credentials `aplus` / `19491001`, identical for every user of the app |
| Per-device auth | **None.** Addressing is by serial number alone |
| Command grammar | Identical over both transports — a `key=value` query string |
| Channels | 8 on A8-PRO (`w b r g b2 p uv wm`). Live set 0–1023; config/schedule values 0–100 % |
| Per-channel HA control feasible? | **Done** — `custom_components/aipai_a8`, one device per fixture (§10) |

The app is an APICloud/uzmap hybrid — all logic is HTML/JS, RC4-encrypted inside the APK with a key
statically recoverable from `lib/*/libsec.so`. For this build the key is `0059be11662664f80e9b`.
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

### Other commands found in the app

| Command | Effect |
|---|---|
| `sta=getip` | Identity: `<ip>,<serial>,<flag>` — the app's own liveness check, works without an account |
| `preview=<hour>&w=<pct>&b=<pct>…` | Drive all channels at once, values 0–100 (untested on hardware) |
| `sta=aplist` / `sta=apconnect&ssid=&pwd=` | Wi-Fi provisioning, served at `192.168.4.1` in AP mode |
| `read=config` | Dump full configuration (see §3) |
| `save=<blob>` | Write full configuration (see §4) |
| `reset=1` | Factory reset |
| `clock=<str>` | Set device clock |
| `version=<file>` | Trigger OTA firmware update |
| `node=restart` | Reboot the device |
| `mculed=on` / `mculed=off` | Status LED on the fixture |
| `turnoffset=0` / `turnoffset=1` | Fade behaviour toggle |

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

Listed best-first. They are not mutually exclusive — route A is the goal, route C is the guaranteed fallback.

### Route A — local HTTP (no cloud at all) ★ preferred

```
GET http://<light-ip>/?w=512
GET http://<light-ip>/?read=config
```

The app still computes `serverUrl = "http://" + device.ip + "/"` unconditionally, and only *chooses*
MQTT when `device.ver.substr(0,4) > 2023`. The HTTP server is very likely still present in current
firmware — the app simply stopped calling it. **This is the first thing to test (§6.1).**

If it answers: HA integration is a handful of `rest_command:` entries plus a `rest:` sensor, or a
small `light` platform. Fully local, no cloud, no vendor account, no broker. Matches the
build's "no proprietary apps or cloud" rule outright.

### Route B — DNS redirect to local Mosquitto ★★ best if A fails

The lights connect *out* to `mqtt.doseen.com`. Tower already runs Mosquitto (`AquaPiMasterReference.md` §6.2).

1. Point `mqtt.doseen.com` at Tower's Mosquitto via a local DNS override (Pi-hole / AdGuard /
   router-level rewrite / dnsmasq).
2. Accept `aplus` / `19491001` on the local broker.
3. Subscribe `light/+/dev`, publish to `light/<SN>/mob`.
4. Firewall the lights from the internet entirely.

The lights end up talking to a broker inside the house, believing it is the vendor's. Fully local,
no vendor cloud, and it keeps the schedule/OTA machinery intact.

> Unknown: the device-side port. The app uses WebSocket 8083; the firmware almost certainly uses
> plain MQTT **1883** or TLS **8883**. A pcap of a booting light settles it (§6.3). If the firmware
> pins a certificate this route fails — but given the app uses unencrypted `ws://`, certificate
> pinning is unlikely.

### Route C — vendor cloud broker ✓ guaranteed, but cloud-dependent

Connect HA's MQTT client to `ws://mqtt.doseen.com:8083/mqtt` with `aplus` / `19491001`, publish
to `light/<SN>/mob`:

```json
{"type": "w512", "msg": "w=512"}
```

`type` is the msg with the `=` stripped (`order.replace("=","")`) — odd, but that is what the
firmware expects. Subscribe `light/<SN>/dev` for replies.

Works today, needs no hardware access — but it depends on a Chinese cloud service and violates the
project's no-cloud rule. Use it to *prove the command grammar* while working out A or B.

### Topic reference

| Topic | Direction |
|---|---|
| `light/<SN>/mob` | app → device (commands) |
| `light/<SN>/dev` | device → app (replies, `{type, msg}`) |
| `dev/<SN>` | newer generic device topic |
| `mob/<clientId>` | newer generic app-reply topic |
| `wave/<SN>/…`, `water/<SN>/…` | other product lines, same scheme |

---

## 6. Hardware test plan

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

### 6.4 Serial numbers

Needed for routes B and C. Visible in the AIPAI app's device list, and usually on the fixture label.

---

## 7. Security findings — worth acting on regardless

These are properties of the product, not of this build, but they bear on how the lights should be
treated on the network.

1. **Global hardcoded broker credentials.** `aplus` / `19491001` are compiled into every copy of the
   app. There is no per-user or per-device secret.
2. **No transport encryption.** `ws://` on port 8083. Commands and configuration cross the internet
   in clear text.
3. **No device-level authorisation.** Anyone who knows a serial number can publish to
   `light/<SN>/mob` and control that fixture — including its schedule and OTA update command.
   Serial numbers appear to be sequential.
4. **Remote OTA is exposed on the same unauthenticated channel** (`version=<file>`).

**Recommendation:** put the three fixtures on the IoT VLAN and firewall them from the internet
regardless of which control route wins. Route A or Route B both make outbound internet access
unnecessary. Given item 4, this is worth doing whether or not the HA integration ever happens.

---

## 8. Artefacts

| File | What it is |
|---|---|
| `3.1.82.apk` | AIPAI Android app, the analysis subject |
| `decrypt.py` | Dependency-free APICloud/uzmap RC4 decryptor |
| `dec/assets/widget/` | 136 decrypted app files — the readable source |
| `dec/assets/widget/script/public.js` | `SetDevOrder`, `DevicesSave`, MQTT connect — the core |
| `dec/assets/widget/ctrl-light.html` | Light UI: `deviceSyns` config parser, `mqttOrder`, channel map |
| `a8_probe.py` | LAN probe — `sta=getip` + `read=config`, decodes all fields, `--set` / `--raw`, refuses OTA/reset/save |
| `custom_components/aipai_a8/` | HA integration (§10) |
| `homeassistant/a8_lights.yaml` | YAML-package alternative (fallback) |
| `REVIEW-2026-09-03.md` | Review of the original write-up — the corrections that went into the README |

Key source lines: `public.js:130` (broker + credentials), `public.js:442` (`SetDevOrder`, transport
switch), `public.js:538` (`DevicesSave`), `ctrl-light.html:410` (`serverUrl`), `:429` (`roadName`),
`:1391` (0–1023 scaling), `:1424` (`deviceSyns`).

---

## 9. Hardware confirmation (3 Sep 2026)

Light 3 factory-reset, joined to the 2.4 GHz LAN, probed from the MacBook with `tools/a8_probe.py`:

```
LOCAL HTTP API IS ALIVE  →  http://192.168.1.208:80/
sta=getip: ip=192.168.1.208 serial=3156988 flag=false
model=A8PRO6  serial=3156988  channels=8  switch=on  mode=0 (manual)
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
| Persistence | Live sets hold. **But a reboot restores stored levels** (50 % all channels, switch on). Light 3 rebooted at 21:13 on 3 Sep right after two presets fired 48 commands in 3 s → came on by itself at night. Fix: integration v0.1.1 re-pushes on reconnect + paces writes 150 ms; photoperiod re-pushes every 5 min while on. |
| Lights 1 & 2 | Not yet reset; add later by IP. |

Two other LAN hosts answer on port 80 with non-config pages (192.168.1.183, .197) — the probe only
counts a `|`-delimited reply.

---

## 10. Home Assistant — installed and working

**`custom_components/aipai_a8/`** (in the repo, HACS custom repository). Installed on HA 2026.9.0
(`homeassistant.local`), added by IP, first try. Device "A8 Pro Light 3", area Living Room.

| Entity | Notes |
|---|---|
| `light.*_master` | Whole-fixture on/off + proportional dimmer. `effective = setpoint × master %`; sends one `?ch=` per channel. |
| `light.*_white … _warm_white` | 8 channel dimmers. Assumed state, restore on restart, seeded from stored config on first add (50 % each). |
| `sensor.*_temperature` | From `read=config` every 60 s; displays °F because HA is imperial (121.9 °F = 49.9 °C). |
| `sensor.*_mode` | `manual` / `schedule`. Keep manual. |
| `sensor.*_device_clock`, `_device_timezone`, fan thresholds | Diagnostic. |
| `button.*_push_levels_to_light` | Resend every channel — after a power loss. |
| `button.*_sync_clock` | `clock=<epoch>`. |

Design notes: `api.py` has no HA imports (unit-tested against the real 29-field reply); coordinator
tolerates a transient `A+` to a poll by keeping last data instead of going unavailable; never sends
`reset=`, `version=`, `node=restart`. (`save=` was added in v0.2.0 — see §11, which supersedes the
v0.1.x parts of §9 and §10.)

The earlier YAML package (`homeassistant/a8_lights.yaml`, `rest_command` + template lights) also works
and is kept in the repo as a fallback; it should be removed from `/config/packages/` now that the
integration is in so two controllers don't fight over one light. Lesson from that install: the legacy
`light: - platform: template` form was removed in current HA — template lights must live under
`template:`.

All three fixtures added: Light 1 = 192.168.1.155, Light 2 = 192.168.1.165, Light 3 = 192.168.1.208
(entity prefix `living_room_a8_pro_light_N_`).

### Reef Command → Lighting tab (`/reef-command/lighting`)

| Section | Contents |
|---|---|
| Day Cycle | `input_boolean.reef_lights_schedule`, `input_number.reef_lights_peak_intensity` (70), `input_datetime.reef_lights_{sunrise,full_day,sunset,night}` (now 11:45/15:45/20:45/00:45), template sensors `reef_lights_{phase,next_change,day_length,full_intensity_hours}`, 24 h intensity graph (3 masters) |
| Spectrum Presets | Tiles → `script.reef_spectrum_apply` with channel ratios; `input_select.reef_spectrum_preset` records the active one |
| Light 1 / 2 / 3 | Master + 8 colour-matched inline sliders + Push button; temp/mode badges. Compact rows for portrait iPad |
| Spectrum — 24 h | Three history-graphs (one per light) of `sensor.reef_light_N_<channel>` template helpers (effective %) |

### Automation `automation.reef_lights_photoperiod`
Every 5 min + on any Day Cycle helper change, if schedule on: master target = linear ramp
sunrise→full (0→peak), flat peak full→sunset, linear sunset→night (peak→0), off outside. Drives the
three masters only; channel ratios are the spectrum. Schedule off = freeze (no off branch).

### Script `script.reef_spectrum_apply` (fields preset, w b r g b2 p uv wm)
Sets channel set points on all three lights. Presets (app's A8 values ×1.25, normalised to 100):
AB+ 24/100/24/24/100/100/100/24 · PHX14 24/100/30/18/100/100/100/24 · LPS 15/100/25/20/100/100/100/15 ·
Color 55/100/40/23/100/100/100/55 · Full Spectrum all 100 · Moonlight 0/10/0/0/30/10/0/0.

Gotcha: the HA dashboard editor saves its whole stale copy on exit — close the editor before agent
writes, or they get reverted.

**Next:** verify persistence across a full day (does a live set drift back between 5-min ticks);
"Custom" detection on manual slider moves; finer ramp (`/1`) if 2 % steps look coarse.

---

---

## 11. Current state (3 Sep 2026, late) — supersedes the v0.1.x parts of §9–§10

### `save=` is verified; the light runs its own photoperiod

Blob format exactly as §4. Reply `true`. Fan thresholds pass through unchanged. Mode 1 with tz `-4`
works, and **the timezone only takes effect on the next `clock=`**, so the integration always sends
`clock=<epoch>` immediately after a save. A light parked in mode 0 with all channels 0 stayed dark for
more than 10 minutes with no HA nagging — the crutch is gone.

The finding that forced this: **live sets are temporary.** The firmware re-applies its stored config
every few minutes, so anything sent with `?w=`/`?b2=` is a preview. Only `save=` persists. The
one-minute "hold levels" automation that papered over this has been deleted.

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

### Home Assistant objects (current)

- Day cycle helpers: schedule toggle (**off** — tank still in assembly), peak 70,
  sunrise 11:45 · full day 15:45 · sunset 20:45 · night 00:45 (13 h photoperiod, 5 h at peak).
- `script.reef_lights_save_schedule` — calls `set_schedule` on all three devices from those helpers.
- `automation.reef_lights_photoperiod` — no more 5-minute polling; re-saves on schedule→on, on any
  helper change, on HA start, and daily at 03:30 (DST).
- `automation.reef_lights_schedule_off` — masters off + `set_manual off`.
- `automation.reef_spectrum_detect_custom` — sets `input_select.reef_spectrum_preset` to Custom when a
  channel set point is changed by hand. Fires only when the change has a user and no parent context,
  so `script.reef_spectrum_apply` and restored-state-on-restart do not trip it. Verified both ways.
- Lighting tab: the Day Cycle graph is now an apexcharts card rendering the **saved curve** — a smooth
  "Planned (HA)" area plus the 24 hourly points the firmware actually stores, which is what shows how
  much the hourly quantisation rounds off a 11:45 sunrise. The old history graph of HA's master
  intensity was meaningless in schedule mode, since HA never sees the light's own ramp.
- Device IDs: Light 1 `035ceaf2a508529fd15533315c19f4f2`, Light 2 `8e3bc4f2195510962cbf37561dc93c9e`,
  Light 3 `6a236d62b2ebc95ba2369bf957e25bee`.

### Physical state

All three lights **manual, all channels 0, tz −4, clock local** — parked dark while the tank is
plumbed. Masters off in HA, schedule toggle off, spectrum AB+ sitting in the set points.

### Still open

- DHCP reservations for .155 / .165 / .208.
- Test `preview=` (would make a master change one call instead of eight).
- The Lighting tab's "Spectrum — last 24 h" history graphs are still HA's model; in schedule mode they
  only reflect what HA sent, not what the light ran.

---

## 12. Spectrum presets — Custom button, highlight, and one HA lesson

### Objects

| Object | Role |
|---|---|
| `input_select.reef_spectrum_preset` | The active preset name (7 options incl. Custom) |
| `input_text.reef_spectrum_custom` | Last hand-tuned spectrum, 8 comma-separated percentages |
| `input_boolean.reef_spectrum_applying` | On while a preset script writes set points; suppresses the detector |
| `script.reef_spectrum_apply` | Writes the 8 ratios to all three lights, records the preset, re-saves the schedule if it is on. `continue_on_error` on the light calls so one unreachable fixture does not abort the other two |
| `script.reef_spectrum_recall_custom` | Re-applies the stored custom string; notifies if none saved |
| `automation.reef_spectrum_detect_custom` | Hand edit -> snapshot that light's 8 set points + flag Custom |
| `automation.reef_spectrum_clear_stuck_applying_flag` | Clears the guard flag if it sticks on for 5 min |

Lighting tab: four preset tiles, `columns: 9` of the section's 36-column grid, `rows: 1`, each with a
card-mod style that draws a border and tint on the tile matching the active preset. Inactive tiles are
left completely alone - a dimmed/greyed treatment was tried on 3 Sep and rejected for draining the
colour out of the row.

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
against stacked runs — leave a minute or two between full preset applies.

### Preset set as of late 3 Sep (supersedes the ratio lists in sections 10 and 11)

Four presets, one row: **Default** 25/100/10/20/100/100/90/15 - **100% White** all 100 (the former
Full Spectrum) - **Moonlight** 0/10/0/0/30/10/0/0 - **Custom** (recalled from
`input_text.reef_spectrum_custom`). AB+, PHX14, LPS and Color were removed from both the tiles and the
input_select options. Tiles are `columns: 9` of the 36-column section, `rows: 1`.

Adding a preset is three edits: the name into `input_select.reef_spectrum_preset`'s options, a tile
whose `tap_action` calls `script.reef_spectrum_apply` with the eight ratios in `data`, and a copy of
the card-mod highlight style with that name substituted.

Dashboard tab order changed on 3 Sep: the Lighting view is `views[3]`. Locate cards by search rather
than by a remembered index.

### Editable Default, and the native-types gotcha (late 3 Sep)

Default's ratios moved out of the dashboard tile into `input_text.reef_spectrum_default`, so they can
be re-saved at runtime: `script.reef_spectrum_apply_default` reads the helper (falling back to
`25,100,10,20,100,100,90,15`), and `script.reef_spectrum_save_default` writes Light 1's current set
points into it. The Default tile taps to apply and **holds** to save, behind a confirmation dialog.
Same shape as Custom — a preset is a helper plus two scripts plus a tile.

**HA gotcha worth remembering:** a `variables:` block renders templates to *native Python types*, so a
template producing `"25,100,10,..."` comes back as a tuple and `.split(',')` raises
`'TupleWrapper' object has no attribute 'split'` — inside an `if` condition that failure is silent and
the else branch runs. Service-call `data:` fields keep the string. Keep such a value as a list in
variables and `| join(',')` only where it is consumed.

The four Day Cycle time tiles also highlight the active phase from `sensor.reef_lights_phase`
(states: `Sunrise` / `Day` / `Sunset` / `Night` — the "Full day" tile matches `Day`).

The Default slot is two tiles in one grid position, switched by HA's native per-card `visibility`
conditions: "Default" when the preset is anything but Custom, "Hold to save as Default" when it is
Custom. Same tap/hold actions on both. `visibility` is core HA and works on any card in a sections
view - the cheap way to make a card state-dependent without a templating custom card.

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
