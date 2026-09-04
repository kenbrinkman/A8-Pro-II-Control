# Tests

```bash
python3 tests/run.py
```

No pytest, no network, no Home Assistant install. Python 3.11+ and nothing else.

- `stubs/` — just enough of `homeassistant` and `voluptuous` for the integration modules to import.
  **Do not copy this directory into a Home Assistant config.** It exists only so the tests can run
  anywhere; the test files put it on `sys.path` themselves. HACS installs `custom_components/aipai_a8`
  only, so it never ships to an HA instance.
- `fake_aiohttp.py` — replays a scripted list of HTTP outcomes and records every request, so the
  failures seen on hardware reproduce deterministically: a stalled `read=config`, and a
  `ServerDisconnectedError` whose message is the empty string.

| File | Covers |
|---|---|
| `test_retry.py` | `A8Client._get`: retry on a stalled request, the longer `read=config` / `save=` timeout, byte-identical retries, error messages that name the failure instead of ending in a colon |
| `test_service.py` | `_apply_each` (one failing fixture must not cancel the others), `_save` falling back to the last good poll, and the stored-vs-believed mismatch comparison |
| `test_push.py` | Live sets suppressed in schedule mode, still sent in manual mode |

The point of `test_service.py` is the 4 Sep 2026 shape specifically: light 1 fails, lights 2 and 3
must still be written, and the error must name the light that failed. See reference §13.
