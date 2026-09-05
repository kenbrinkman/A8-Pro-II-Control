"""Exercise the real _apply_each and the real coordinator save/mismatch paths."""
import pathlib
HERE = pathlib.Path(__file__).resolve().parent
import asyncio, sys, types
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "stubs"))
sys.path.insert(0, str(HERE.parent))
import fake_aiohttp

# custom_components is a namespace package; give aipai_a8's own __init__ a chance to load.
from custom_components.aipai_a8 import _apply_each
from custom_components.aipai_a8 import const, api
from custom_components.aipai_a8.coordinator import A8Coordinator
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

fails = passes = 0
def check(label, cond):
    global fails, passes
    if cond: passes += 1; print(f"  ok   {label}")
    else:    fails += 1; print(f"  FAIL {label}")

const.DEVICE_SPACING = 0.01
import custom_components.aipai_a8 as pkg
pkg.DEVICE_SPACING = 0.01

class FakeCo:
    def __init__(self, host, ok=True):
        self.client = types.SimpleNamespace(host=host)
        self.ok = ok
        self.ran = False
    async def act(self):
        self.ran = True
        if not self.ok:
            raise UpdateFailed(f"{self.client.host}: read before save failed")

async def main():
    # The 04 Sep shape: light 1 fails, lights 2 and 3 must still be written.
    cos = [FakeCo("192.168.1.71", ok=False), FakeCo("192.168.1.72"), FakeCo("192.168.1.73")]
    try:
        await _apply_each(cos, lambda c: c.act(), "set_schedule")
        check("a failure still raises", False)
    except HomeAssistantError as e:
        check("a failure still raises", True)
        check("lights after the failure were written", cos[1].ran and cos[2].ran)
        check("error names the failing host", "192.168.1.71" in str(e))
        check("error reports the tally", "1 of 3" in str(e))
        check("error does not name the healthy hosts", "192.168.1.73" not in str(e))

    # All healthy: no raise, all written.
    cos = [FakeCo("a"), FakeCo("b"), FakeCo("c")]
    await _apply_each(cos, lambda c: c.act(), "set_manual")
    check("all-healthy run raises nothing", all(c.ran for c in cos))

    # All failing: every one attempted, all reported.
    cos = [FakeCo("a", ok=False), FakeCo("b", ok=False)]
    try:
        await _apply_each(cos, lambda c: c.act(), "set_manual")
        check("all-failing raises", False)
    except HomeAssistantError as e:
        check("all-failing raises", True)
        check("all-failing attempts every light", all(c.ran for c in cos))
        check("all-failing reports both", "2 of 2" in str(e))

    # ---- coordinator: save survives a stalled pre-save read -------------
    CONFIG = "|".join(["on", "0", "65", "50", "75"] + ["0"]*8
                      + [",".join(["0"]*24)]*8
                      + ["28.5", "18,44", "0", "0", "1234567", "0", "-4", "A8PRO6"])
    initial = api.parse_config(CONFIG)

    def make(outcomes):
        s = fake_aiohttp.ClientSession(outcomes)
        c = api.A8Client("192.168.1.71", s)
        co = A8Coordinator.__new__(A8Coordinator)
        co.client = c; co.serial = "1234567"; co.channels = 8
        co.model = "A8PRO6"; co.keys = const.CHANNEL_KEYS[:8]
        co.setpoint = {k: initial.levels_pct[i] for i, k in enumerate(co.keys)}
        co.master_pct = 100; co.master_on = True; co.data = initial
        co.async_request_refresh = lambda: asyncio.sleep(0)
        return co, s

    api.RETRY_BACKOFF = 0.01
    # read stalls on both attempts, then save= and clock= succeed
    co, s = make([asyncio.TimeoutError(), asyncio.TimeoutError(), "true", "A+"])
    await co.save_manual({k: 0 for k in co.keys})
    saved = [u for u, _ in s.calls if "save=" in u]
    check("save proceeds from cached config when the read stalls", len(saved) == 1)
    check("the fallback save is a well-formed blob", "?save=onx0x" in saved[0])

    # no cached config at all -> must still refuse rather than write a guess
    co, s = make([asyncio.TimeoutError(), asyncio.TimeoutError()])
    co.data = None
    try:
        await co.save_manual({k: 0 for k in co.keys})
        check("no cached config refuses the save", False)
    except UpdateFailed as e:
        check("no cached config refuses the save", "no cached config" in str(e))
        check("nothing was written without a config", not any("save=" in u for u, _ in s.calls))

    # ---- mismatch -------------------------------------------------------
    co, _ = make(["true"])
    co.master_on = True; co.master_pct = 100
    co.setpoint = dict.fromkeys(co.keys, 0)
    check("agreeing levels report no mismatch", co.level_mismatch() == {})

    co.setpoint = {k: (100 if k == "b2" else 0) for k in co.keys}
    d = co.level_mismatch()
    check("a live-only change is flagged", list(d) == ["b2"] and d["b2"] == (100, 0))

    co.data = api.parse_config(CONFIG.replace("|0|65", "|1|65", 1))
    check("schedule mode reports not-applicable", co.level_mismatch() is None)

    # tolerance: rounding slack must not trip it
    co.data = initial
    co.setpoint = dict.fromkeys(co.keys, 0); co.master_pct = 100
    co.setpoint["w"] = 2
    check("a 2-point gap is within tolerance", co.level_mismatch() == {})
    co.setpoint["w"] = 3
    check("a 3-point gap is a mismatch", "w" in co.level_mismatch())

    # a channel missing from the stored side is skipped, not read as zero
    check("missing stored channel is skipped",
          api.level_mismatch({"w": 50, "b": 50}, {"w": 50}) == {})

asyncio.run(main())
print(f"\n{passes} passed, {fails} failed")
sys.exit(1 if fails else 0)
