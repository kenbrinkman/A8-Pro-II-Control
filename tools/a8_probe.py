#!/usr/bin/env python3
"""A8 Pro II LAN probe — tests whether the lights expose their local HTTP API.

Stdlib only. Run on any machine on the same LAN as the lights.

    python3 a8_probe.py 192.168.1.71 192.168.1.72 192.168.1.73
    python3 a8_probe.py --scan 192.168.1.0/24

What it does, per host:
  1. checks a short list of likely HTTP ports
  2. issues  GET /?sta=getip      (cheap identity check: "<ip>,<serial>,<flag>")
  3. issues  GET /?read=config    and decodes the reply
  4. prints the channel map, current levels, temperature, clock, timer, serial

It only ever READS. Nothing here changes a light. To test writing, see --set / --raw.
"""
import argparse, concurrent.futures as cf, ipaddress, json, socket, sys
import urllib.request, urllib.error

PORTS = [80, 8080, 8000, 81, 8081, 88, 5000]
ROADS = ["w", "b", "r", "g", "b2", "p", "uv", "wm"]
NAMES = ["White", "Blue", "Red", "Green", "Deep Blue", "Purple", "UV", "Warm White"]
TIMEOUT = 3.0


def tcp_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def http_get(host, port, query, timeout=TIMEOUT):
    url = f"http://{host}:{port}/?{query}" if port != 80 else f"http://{host}/?{query}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace").strip()
    except (urllib.error.URLError, OSError, ValueError):
        return None


def parse_getip(raw):
    """sta=getip reply is "<ip>,<serial>,<flag>" (flag is a licence check result)."""
    if not raw or "," not in raw or raw == "false":
        return None
    p = [x.strip() for x in raw.split(",")]
    return {"ip": p[0], "sn": p[1] if len(p) > 1 else None,
            "flag": p[2] if len(p) > 2 else None}


def parse_config(raw):
    """Decode the |-delimited read=config reply. Returns a dict or None.

    Field layout (n = channel count, d = 2*(n-6)), as read by the app's deviceSyns():
      [0] switch  [1] mode  [2..4] fan-on / fan-off / cutoff temps
      [5 .. 5+n-1]       current level per channel, PERCENT 0-100
      [5+n .. 5+2n-1]    24-point daily schedule per channel, percent
      [17+d] temperature  [18+d] clock "H,M"  [19+d] timer-on hour  [20+d] timer-off hour
      [21+d] serial       [22+d] knob flag    [23+d] timezone       [24+d] model
    """
    if not raw or "|" not in raw:
        return None
    f = [x.strip() for x in raw.split("|")]
    n = 8 if len(f) > 28 else 6
    d = 2 * (n - 6)

    def fld(i):
        return f[i] if i < len(f) else None

    out = {
        "raw_fields": len(f),
        "channels": n,
        "switch": f[0],
        "mode": f[1],
        "temp_on": fld(2),
        "temp_off": fld(3),
        "temp_out": fld(4),
        "levels_pct": {},
        "schedule": {},
        "temperature": fld(17 + d),
        "clock": fld(18 + d),
        "timer_on": fld(19 + d),
        "timer_off": fld(20 + d),
        "serial": fld(21 + d),
        "knob_flag": fld(22 + d),
        "timezone": fld(23 + d),
        "model": fld(24 + d),
    }
    for i in range(n):
        try:
            v = int(float(f[5 + i]))
        except (ValueError, IndexError):
            v = None
        out["levels_pct"][ROADS[i]] = v
    for i in range(n):
        idx = 5 + n + i
        if idx < len(f) and "," in f[idx]:
            out["schedule"][ROADS[i]] = f[idx]
    return out


def report(host, port, cfg, raw, ident):
    print(f"\n  \033[1mLOCAL HTTP API IS ALIVE\033[0m  →  http://{host}:{port}/")
    if ident:
        print(f"  sta=getip: ip={ident['ip']} serial={ident['sn']} flag={ident['flag']}")
    print(f"  model={cfg.get('model') or '?'}  serial={cfg.get('serial') or '?'}  "
          f"channels={cfg['channels']}  switch={cfg['switch']}  mode={cfg['mode']} "
          f"({'schedule' if cfg['mode'] == '1' else 'manual'})")
    print(f"  temp={cfg.get('temperature')}°C  clock={cfg.get('clock')}  "
          f"timer on/off={cfg.get('timer_on')}/{cfg.get('timer_off')}  tz=UTC{cfg.get('timezone')}  "
          f"fan on/off/cutoff={cfg['temp_on']}/{cfg['temp_off']}/{cfg['temp_out']}")
    print("\n  channel    %     name")
    for i, k in enumerate(ROADS[:cfg["channels"]]):
        v = cfg["levels_pct"].get(k)
        bar = "█" * int((v or 0) * 24 / 100)
        print(f"  {k:<8} {str(v):>4}    {NAMES[i]:<12} {bar}")
    if cfg["schedule"]:
        k0 = next(iter(cfg["schedule"]))
        print(f"\n  schedule present: {len(cfg['schedule'])} rows x 24 pts "
              f"(e.g. {k0} = {cfg['schedule'][k0][:60]}...)")
    print(f"\n  raw reply ({len(raw)} bytes):\n  {raw[:400]}")


def probe(host):
    """Returns (host, port, cfg, raw, open_ports, ident, note)."""
    found = [p for p in PORTS if tcp_open(host, p)]
    if not found:
        return host, None, None, None, [], None, None
    for p in found:
        ident = parse_getip(http_get(host, p, "sta=getip"))
        raw = http_get(host, p, "read=config")
        cfg = parse_config(raw) if raw else None
        if cfg:
            return host, p, cfg, raw, found, ident, None
        if raw == "A+" or ident:
            note = f"device answered (read=config -> {raw!r}) but gave no config string"
            return host, p, None, raw, found, ident, note
    return host, None, None, None, found, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hosts", nargs="*", help="light IP addresses")
    ap.add_argument("--scan", metavar="CIDR", help="sweep a subnet instead")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--set", metavar="CH=VAL",
                    help="WRITE TEST: set one channel, e.g. b2=1023 (needs exactly one host)")
    ap.add_argument("--raw", metavar="QUERY",
                    help="send an arbitrary query string, e.g. 'preview=12&w=50&b=50' (one host)")
    a = ap.parse_args()

    hosts = list(a.hosts)
    if a.scan:
        hosts += [str(h) for h in ipaddress.ip_network(a.scan, strict=False).hosts()]
    if not hosts:
        ap.error("give one or more IPs, or --scan CIDR")

    if a.set or a.raw:
        if len(hosts) != 1:
            ap.error("--set/--raw needs exactly one host")
        q = a.set or a.raw
        if q.split("=")[0] in ("version", "reset", "save"):
            ap.error(f"refusing to send '{q}' — OTA/reset/save can brick a fixture; use curl if you mean it")
        h = hosts[0]
        _, port, _, _, _, _, _ = probe(h)
        if not port:
            print(f"{h}: no local API, cannot write"); return
        print(f"sending {q} to {h}:{port} ...")
        print("reply:", repr(http_get(h, port, q)))
        return

    results = []
    workers = min(64, max(4, len(hosts)))
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(probe, hosts):
            if not r[4] and len(hosts) > 8:
                continue
            results.append(r)

    if a.json:
        print(json.dumps([{"host": h, "port": p, "open_ports": o, "identity": i, "config": c}
                          for h, p, c, _, o, i, _ in results], indent=2))
        return

    if not results:
        print("no hosts responded on any candidate HTTP port")
    for host, port, cfg, raw, open_ports, ident, note in results:
        print(f"\n=== {host} ===")
        print(f"  open TCP (of {PORTS}): {open_ports or 'none'}")
        if cfg:
            report(host, port, cfg, raw, ident)
        elif note:
            print(f"  {note}")
            if ident:
                print(f"  sta=getip: ip={ident['ip']} serial={ident['sn']} flag={ident['flag']}")
        elif open_ports:
            print("  HTTP port(s) open but ?read=config did not return a config string.")
            for p in open_ports:
                r = http_get(host, p, "")
                print(f"    GET http://{host}:{p}/  ->  {repr(r)[:200] if r else 'no reply'}")
        else:
            print("  closed / unreachable — the local HTTP server is not listening here")

    print("\nIf every light shows 'LOCAL HTTP API IS ALIVE', Route A is confirmed:")
    print("full local control, no cloud, no vendor account.")


if __name__ == "__main__":
    main()
