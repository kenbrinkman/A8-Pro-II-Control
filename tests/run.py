#!/usr/bin/env python3
"""Run every test in this directory. No pytest, no network, no Home Assistant.

`stubs/` holds just enough of homeassistant and voluptuous for the integration
modules to import; `fake_aiohttp.py` replays scripted HTTP outcomes so the
failure modes seen on hardware (a stalled read=config, a ServerDisconnectedError
whose message is empty) can be reproduced deterministically.

    python3 tests/run.py
"""
import pathlib, subprocess, sys

here = pathlib.Path(__file__).resolve().parent
rc = 0
for path in sorted(here.glob("test_*.py")):
    print(f"== {path.name}")
    r = subprocess.run([sys.executable, str(path)])
    rc |= r.returncode
print("\nALL PASSED" if rc == 0 else "\nFAILURES")
sys.exit(rc)
