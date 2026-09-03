#!/usr/bin/env python3
"""A8 Pro II LAN probe — tests whether the lights still expose their local HTTP API.

Stdlib only. Run on any machine on the same LAN as the lights.

    python3 a8_probe.py 192.168.1.71 192.168.1.72 192.168.1.73
    python3 a8_probe.py --scan 192.168.1.0/24

What it does, per host:
  1. checks a short list of likely HTTP ports
  2. issues  GET /?read=config  and decodes the reply
  3. prints the channel map and current levels

It only ever READS. Nothing here changes a light. To test writing, see --set at the bottom.
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
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None


def parse_config(raw):
    """Decode the |-delimited read=config reply. Returns a dict or None."""
    if not raw or "|" not in raw:
        return None
    f = [x.strip() for x in raw.split("|")]
    n = 8 if len(f) > 28 else 6
    out = {
        "raw_fields": len(f),
        "channels": n,
        "switch": f[0],
        "mode": f[1],
        "temp_on": f[2],
        "temp_off": f[3],
        "temp_out": f[4],
        "levels": {},
        "schedule": {},
    }
    for i in range(n):
        try:
            v = int(float(f[5 + i]))
        except (ValueError, IndexError):
            v = None
        out["levels"][ROADS[i]] = v
    for i in range(n):
        idx = 5 + n + i
        if idx < len(f) and "," in f[idx]:
            out["schedule"][ROADS[i]] = f[idx]
    model_idx = 24 + 2 * (n - 6)
    if model_idx < len(f):
        out["model"] = f[model_idx]
    return out


def report(host, port, cfg, raw):
    print(f"\n  \033[1mLOCAL HTTP API IS ALIVE\033[0m  →  http://{host}:{port}/")
    print(f"  model={cfg.get('model','?')}  channels={cfg['channels']}  "
          f"switch={cfg['switch']}  mode={cfg['mode']}  "
          f"fan on/off/cutoff={cfg['temp_on']}/{cfg['temp_off']}/{cfg['temp_out']}")
    print("\n  channel   raw/1023    %      name")
    for i, k in enumerate(ROADS[:cfg["channels"]]):
        v = cfg["levels"].get(k)
        pct = f"{v * 100 / 1023:5.1f}" if isinstance(v, int) else "   ? "
        bar = "█" * int((v or 0) * 24 / 1023)
        print(f"  {k:<8}  {str(v):>6}    {pct}   {NAMES[i]:<12} {bar}")
    if cfg["schedule"]:
        k0 = next(iter(cfg["schedule"]))
        print(f"\n  schedule present: {len(cfg['schedule'])} rows x 24 pts "
              f"(e.g. {k0} = {cfg['schedule'][k0][:60]}...)")
    print(f"\n  raw reply ({len(raw)} bytes):\n  {raw[:400]}")


def probe(host):
    found = [p for p in PORTS if tcp_open(host, p)]
    if not found:
        return host, None, None, None, []
    for p in found:
        raw = http_get(host, p, "read=config")
        cfg = parse_config(raw) if raw else None
        if cfg:
            return host, p, cfg, raw, found
    return host, None, None, None, found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hosts", nargs="*", help="light IP addresses")
    ap.add_argument("--scan", metavar="CIDR", help="sweep a subnet instead")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--set", metavar="CH=VAL",
                    help="WRITE TEST: set one channel, e.g. b2=1023 (needs exactly one host)")
    a = ap.parse_args()

    hosts = list(a.hosts)
    if a.scan:
        hosts += [str(h) for h in ipaddress.ip_network(a.scan, strict=False).hosts()]
    if not hosts:
        ap.error("give one or more IPs, or --scan CIDR")

    if a.set:
        if len(hosts) != 1:
            ap.error("--set needs exactly one host")
        h = hosts[0]
        _, port, cfg, _, _ = probe(h)
        if not port:
            print(f"{h}: no local API, cannot write"); return
        print(f"sending {a.set} to {h}:{port} ...")
        print("reply:", repr(http_get(h, port, a.set)))
        return

    results = []
    workers = min(64, max(4, len(hosts)))
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for host, port, cfg, raw, open_ports in ex.map(probe, hosts):
            if not open_ports and len(hosts) > 8:
                continue
            results.append((host, port, cfg, raw, open_ports))

    if a.json:
        print(json.dumps([{"host": h, "port": p, "open_ports": o, "config": c}
                          for h, p, c, _, o in results], indent=2))
        return

    if not results:
        print("no hosts responded on any candidate HTTP port")
    for host, port, cfg, raw, open_ports in results:
        print(f"\n=== {host} ===")
        print(f"  open TCP (of {PORTS}): {open_ports or 'none'}")
        if cfg:
            report(host, port, cfg, raw)
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
