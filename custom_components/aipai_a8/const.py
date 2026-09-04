"""Constants for the AIPAI A8 reef light integration."""

from __future__ import annotations

DOMAIN = "aipai_a8"
MANUFACTURER = "AIPAI (Jinan Hainei Wushuang Technology)"

DEFAULT_SCAN_INTERVAL = 60  # seconds between read=config polls
REQUEST_TIMEOUT = 5  # seconds, for the short commands (live sets, clock=)
# read=config and save= carry the whole configuration -- a 29-field string in,
# ~1.5 kB out -- and the firmware's single-threaded HTTP server takes visibly
# longer over them than over a live set. Timing those out at 5 s is what made a
# schedule write fail on a healthy fixture (04 Sep 2026); give them their own,
# longer budget.
CONFIG_TIMEOUT = 12  # seconds, for read=config and save=
# Every command in this protocol is idempotent by content -- setting a channel
# to the value it already holds, re-saving the same blob, re-sending the clock
# -- so a failed request can simply be repeated. One retry converts the common
# single-request stall into a non-event.
RETRY_ATTEMPTS = 2  # total attempts per request, including the first
RETRY_BACKOFF = 0.8  # seconds to wait before the retry
# Seconds between fixtures inside one multi-device service call. These are
# cheap 2.4 GHz modules on a shared radio; back-to-back configuration writes
# across three of them is the pattern that has produced both timeouts and the
# burst reboot.
DEVICE_SPACING = 1.0
WRITE_SPACING = 0.15  # seconds between consecutive channel commands to one fixture
RAW_MAX = 1023  # live channel command is 10-bit

# How far the fixture's stored levels may sit from what Home Assistant believes
# it is sending before that counts as a disagreement. Stored levels are whole
# percent and HA's effective value is rounded, so allow a point of slack.
MISMATCH_TOLERANCE_PCT = 2

# Sanity bounds for a read=config reply. A 6-channel fixture answers with 25
# fields, an 8-channel one with 29; anything shorter is a truncated/transient
# reply. The heatsink thermistor reads room temperature at rest and the
# firmware's own thermal cutoff tops out in the 80s, so a value outside this
# range (notably a zeroed field) is bad data, not a measurement.
MIN_CONFIG_FIELDS = 25
TEMP_MIN_C = 1.0
TEMP_MAX_C = 120.0

# Firmware channel order. Wire keys are identical on every model.
CHANNEL_KEYS: tuple[str, ...] = ("w", "b", "r", "g", "b2", "p", "uv", "wm")

# Human names per model family. Wire order is the same; the LED binning differs.
CHANNEL_NAMES_STANDARD: tuple[str, ...] = (
    "White",
    "Blue",
    "Red",
    "Green",
    "Deep Blue",
    "Purple",
    "UV",
    "Warm White",
)
# B-suffixed models (A8-SEB, A8-PROB, A8-SEB9, A8-PROB9)
CHANNEL_NAMES_BLUE: tuple[str, ...] = (
    "Blue 1",
    "Blue 2",
    "Warm",
    "Olive",
    "Blue 3",
    "Purple",
    "UV",
    "White",
)
# A8-HP / A8-HP6 (6 channels)
CHANNEL_NAMES_HP: tuple[str, ...] = (
    "White",
    "Blue",
    "Red",
    "UV",
    "Blue 3",
    "Purple",
)

CONF_HOST = "host"

ATTR_RAW = "raw_value"

# Services
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_SET_MANUAL = "set_manual"
ATTR_SUNRISE = "sunrise"
ATTR_FULL_DAY = "full_day"
ATTR_SUNSET = "sunset"
ATTR_NIGHT = "night"
ATTR_PEAK = "peak"
ATTR_RATIOS = "ratios"
ATTR_LEVELS = "levels"
ATTR_OFF = "off"
