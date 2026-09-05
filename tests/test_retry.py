import pathlib
HERE = pathlib.Path(__file__).resolve().parent
import asyncio, sys, time
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "stubs"))
sys.path.insert(0, str(HERE.parent))
import fake_aiohttp  # installs the stub into sys.modules
from fake_aiohttp import ClientSession, ServerDisconnectedError
from custom_components.aipai_a8 import api
from custom_components.aipai_a8.const import CONFIG_TIMEOUT, REQUEST_TIMEOUT

CONFIG = "|".join(
    ["on", "0", "65", "50", "75"]
    + ["0"] * 8
    + [",".join(["0"] * 24)] * 8
    + ["28.5", "18,44", "0", "0", "1234567", "0", "-4", "A8PRO6"]
)

fails = 0
passes = 0
def check(label, cond):
    global fails, passes
    if cond: passes += 1; print(f"  ok   {label}")
    else:    fails += 1; print(f"  FAIL {label}")

async def main():
    api.RETRY_BACKOFF = 0.01  # keep the test quick

    # 1. a stalled read is retried and succeeds -- the 04 Sep failure
    s = ClientSession([asyncio.TimeoutError(), CONFIG])
    c = api.A8Client("192.168.1.71", s)
    cfg = await c.get_config()
    check("timeout on read=config is retried and recovers", cfg.serial == "1234567")
    check("read=config uses the long timeout", s.calls[0][1] == CONFIG_TIMEOUT)
    check("retry re-sent the same request", s.calls[0][0] == s.calls[1][0] and len(s.calls) == 2)

    # 2. two failures in a row still raise, with a message that says something
    s = ClientSession([asyncio.TimeoutError(), asyncio.TimeoutError()])
    c = api.A8Client("192.168.1.71", s)
    try:
        await c.get_config()
        check("two failures raise", False)
    except api.A8ConnectionError as e:
        msg = str(e)
        check("two failures raise A8ConnectionError", True)
        check("message names the timeout, not a bare colon", "timed out after" in msg)
        check("message does not end in ': '", not msg.rstrip().endswith(":"))

    # 3. the empty-str error class is named rather than logged blank
    s = ClientSession([ServerDisconnectedError(), ServerDisconnectedError()])
    c = api.A8Client("192.168.1.71", s)
    try:
        await c.get_config()
    except api.A8ConnectionError as e:
        check("empty-message error names its class", "ServerDisconnectedError" in str(e))

    # 4. a live set still uses the short timeout, and is retried too
    s = ClientSession([asyncio.TimeoutError(), "A+"])
    c = api.A8Client("192.168.1.71", s)
    await c.set_channel_pct("b2", 100)
    check("live set uses the short timeout", s.calls[0][1] == REQUEST_TIMEOUT)
    check("live set recovers after a retry", len(s.calls) == 2)

    # 5. save= retries, uses the long timeout, and re-sends an identical blob
    blob = api.build_save_blob(
        channels=8, mode=1, levels_pct=[0] * 8, schedule=[[0] * 24] * 8, timezone="-4"
    )
    s = ClientSession([asyncio.TimeoutError(), "true"])
    c = api.A8Client("192.168.1.71", s)
    await c.save_config(blob)
    check("save= uses the long timeout", s.calls[0][1] == CONFIG_TIMEOUT)
    check("save= retry is byte-identical", s.calls[0][0] == s.calls[1][0])

    # 6. no regression: a clean call makes exactly one request
    s = ClientSession([CONFIG])
    c = api.A8Client("192.168.1.71", s)
    await c.get_config()
    check("a healthy request is not retried", len(s.calls) == 1)

    # 7. the backoff is actually awaited
    api.RETRY_BACKOFF = 0.25
    s = ClientSession([asyncio.TimeoutError(), CONFIG])
    c = api.A8Client("192.168.1.71", s)
    t0 = time.monotonic()
    await c.get_config()
    check("retry waits for the backoff", time.monotonic() - t0 >= 0.24)

asyncio.run(main())
print(f"\n{passes} passed, {fails} failed")
sys.exit(1 if fails else 0)
