"""Live sets must not go out while the fixture runs its own stored curve."""
import pathlib
HERE = pathlib.Path(__file__).resolve().parent
import asyncio, sys
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "stubs")); sys.path.insert(0, str(HERE.parent))
import fake_aiohttp
from custom_components.aipai_a8 import api, const
from custom_components.aipai_a8.coordinator import A8Coordinator

fails = passes = 0
def check(l, c):
    global fails, passes
    if c: passes += 1; print(f"  ok   {l}")
    else: fails += 1; print(f"  FAIL {l}")

BASE = ["on", "{mode}", "65", "50", "75"] + ["50"]*8 + [",".join(["0"]*24)]*8 \
     + ["28.5", "18,44", "0", "0", "1234567", "0", "-4", "A8PRO6"]

def cfg(mode): return api.parse_config("|".join(BASE).format(mode=mode))

def make(mode):
    s = fake_aiohttp.ClientSession(["A+"]*32)
    co = A8Coordinator.__new__(A8Coordinator)
    co.client = api.A8Client("192.168.1.71", s)
    co.keys = const.CHANNEL_KEYS[:8]
    co.setpoint = dict.fromkeys(co.keys, 50)
    co.last_nonzero = dict.fromkeys(co.keys, 50)
    co.master_pct = 100; co.master_on = True; co.data = cfg(mode)
    co.async_update_listeners = lambda: None
    return co, s

async def main():
    co, s = make(1)   # schedule mode
    await co.set_master(pct=25, on=True)
    check("schedule mode sends no live writes", len(s.calls) == 0)
    check("schedule mode still updates the model", co.master_pct == 25)

    co, s = make(0)   # manual mode
    await co.set_master(pct=25, on=True)
    check("manual mode writes all eight channels", len(s.calls) == 8)
    check("manual mode scales by the master", "?w=" in s.calls[0][0])

    co, s = make(1)
    await co.set_channel("b2", 80)
    check("schedule mode skips a single-channel write", len(s.calls) == 0)

    co, s = make(0)
    await co.set_channel("b2", 80)
    check("manual mode sends the single-channel write", len(s.calls) == 1)

    co, s = make(0); co.data = None
    await co.set_channel("b2", 80)
    check("unknown mode does not silently swallow writes", len(s.calls) == 1)

asyncio.run(main())
print(f"\n{passes} passed, {fails} failed")
sys.exit(1 if fails else 0)
