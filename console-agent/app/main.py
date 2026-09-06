#!/usr/bin/env python3
"""Console Agent: push this HAOS host's state to console.marktuttle.dev.

Host CPU/RAM come from /proc via psutil -- inside a container those files
describe the HOST, so no API is needed for the two numbers that matter most.
Disk, uptime, versions and the add-on list come from the Supervisor API.

Network throughput is NOT reported. /proc/net/dev is per network namespace,
and this add-on deliberately has no host_network, so a psutil counter here
would measure the add-on's own traffic rather than the host's. The contract
requires net_rx_bps/net_tx_bps, so they are sent as 0: an honest zero beats
a plausible-looking wrong number on a dashboard.

Never exits on a push failure: the console's SIGNAL LOST is the liveness
signal. Only GET calls are made to the Supervisor.
"""
import json
import os
import sys
import time

import psutil
import requests

SUPERVISOR = "http://supervisor"
OPTIONS = "/data/options.json"
DEFAULT_INGEST_URL = "https://console.marktuttle.dev/api/ingest"


class Supervisor:
    def __init__(self, token: str):
        self.h = {"Authorization": f"Bearer {token}"}

    def _get(self, path: str):
        r = requests.get(SUPERVISOR + path, headers=self.h, timeout=10)
        r.raise_for_status()
        return r.json()["data"]

    def host_info(self):
        return self._get("/host/info")

    def core_info(self):
        return self._get("/core/info")

    def addons(self):
        try:
            return self._get("/addons")["addons"]
        except requests.HTTPError as e:
            # The Supervisor CLI deprecates "addons" in favour of "apps", so a
            # 404 here plausibly means the REST path was renamed too. Anything
            # else (401/403 from a missing hassio_role, a 5xx) is a real error
            # about /addons and must surface with its own status rather than
            # being masked by a second failing request.
            if e.response is not None and e.response.status_code == 404:
                return self._get("/apps")["apps"]
            raise

    def addon_stats(self, slug: str):
        return self._get(f"/addons/{slug}/stats")


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:                    # noqa: BLE001 -- degrade, never crash
        print(f"console-agent: supervisor call failed: {e}", flush=True)
        return default


def build_snapshot(sup, addon_stats: bool = True, sample_seconds: float = 1.0) -> dict:
    cpu = psutil.cpu_percent(interval=sample_seconds)
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    host = _safe(sup.host_info, {})
    core = _safe(sup.core_info, {})
    boot_us = host.get("boot_timestamp")
    uptime = int(time.time() - boot_us / 1e6) if boot_us else int(time.time() - psutil.boot_time())
    load = os.getloadavg()
    kernel = " · ".join(x for x in [
        host.get("kernel"),
        (host.get("operating_system") or "").replace("Home Assistant OS", "HAOS") or None,
        f"Core {core['version']}" if core.get("version") else None] if x)
    containers = []
    for a in _safe(sup.addons, []):
        slug = a.get("slug", "")
        state = a.get("state") or "unknown"
        version = str(a.get("version") or "")
        # The console's container table renders name/status/stats but not
        # `image`, so the version would be invisible if it lived only there.
        # Keep `image` (the contract requires it) and repeat the version here.
        status = " · ".join([state] + ([f"v{version}"] if version else []) + [slug])
        c = {"name": a.get("name") or slug, "image": version,
             "state": state, "health": "none", "status": status}
        if addon_stats and state == "started":
            st = _safe(lambda: sup.addon_stats(slug), None)
            if st:
                c["cpu_pct"] = round(float(st.get("cpu_percent") or 0), 2)
                c["mem_mb"] = round(float(st.get("memory_usage") or 0) / 2**20)
        containers.append(c)
    return {
        "schema": 1, "host": "ha",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kernel": kernel or "unknown",
        "metrics": {
            "cpu_pct": round(min(100.0, cpu), 1),
            "load1": round(load[0], 2), "load5": round(load[1], 2), "load15": round(load[2], 2),
            "mem_total_mb": round(vm.total / 2**20), "mem_used_mb": round((vm.total - vm.available) / 2**20),
            "swap_used_mb": round(sw.used / 2**20),
            "disk_root_total_gb": float(host.get("disk_total") or 0),
            "disk_root_used_gb": float(host.get("disk_used") or 0),
            # Namespaced counters would measure this container, not the host --
            # see the module docstring. Zero, not a wrong number.
            "net_rx_bps": 0, "net_tx_bps": 0,
            "cpu_temp_c": None, "top_process": None, "uptime_s": max(0, uptime),
        },
        "containers": sorted(containers, key=lambda c: c["name"].lower()),
        "timers": [], "failed_units": [], "heartbeats": [], "logs": {},
    }


def push(url: str, token: str, body: bytes) -> None:
    try:
        r = requests.post(url, data=body, timeout=10,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                   "User-Agent": "console-agent/0.1 (ha)"})
        if r.status_code == 204:
            print(f"console-agent: 204 ({len(body)} bytes)", flush=True)
        else:
            print(f"console-agent: HTTP {r.status_code} from console: {r.text[:500]}", flush=True)
    except requests.RequestException as e:
        print(f"console-agent: console unreachable: {e}", flush=True)


def load_options(path: str = OPTIONS):
    """Returns the options dict, or None if the file is unreadable/not JSON."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"console-agent: cannot read {path}: {e}", flush=True)
        return None


def main() -> int:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        print("console-agent: SUPERVISOR_TOKEN missing; is hassio_api set in config.yaml?", flush=True)
        return 2
    opts = load_options(OPTIONS)
    if opts is None:
        # A corrupt options file is a misconfiguration, not a transient fault:
        # exit non-zero so the Supervisor shows the add-on as failed.
        print("console-agent: options file is unusable; not starting.", flush=True)
        return 2
    ingest_token = opts.get("ingest_token", "")
    if not ingest_token:
        print("console-agent: ingest_token option is empty; set it in the add-on configuration. Idling.", flush=True)
    ingest_url = opts.get("ingest_url") or DEFAULT_INGEST_URL
    sup = Supervisor(token)
    interval = int(opts.get("interval_seconds", 30))
    while True:
        started = time.time()
        if ingest_token:
            # A bug in build_snapshot must not become a Supervisor restart loop:
            # one log line per interval is far easier to diagnose than a
            # container that keeps dying before its own log can be read.
            try:
                body = json.dumps(build_snapshot(sup, bool(opts.get("addon_stats", True))),
                                  separators=(",", ":")).encode()
                push(ingest_url, ingest_token, body)
            except Exception as e:            # noqa: BLE001 -- degrade, never crash
                print(f"console-agent: snapshot failed: {e!r}", flush=True)
        time.sleep(max(1.0, interval - (time.time() - started)))


if __name__ == "__main__":
    sys.exit(main())
