#!/usr/bin/env python3
"""Console Agent: push this HAOS host's state to console.marktuttle.dev.

Host CPU/RAM come from /proc via psutil -- inside a container those files
describe the HOST, so no API is needed for the two numbers that matter most.
Disk, uptime, versions and the add-on list come from the Supervisor API.
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
        except requests.HTTPError:           # Supervisor renamed add-ons to apps
            return self._get("/apps")["apps"]

    def addon_stats(self, slug: str):
        return self._get(f"/addons/{slug}/stats")


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:                    # noqa: BLE001 -- degrade, never crash
        print(f"console-agent: supervisor call failed: {e}", flush=True)
        return default


def build_snapshot(sup, addon_stats: bool = True, sample_seconds: float = 1.0) -> dict:
    net0 = psutil.net_io_counters()
    cpu = psutil.cpu_percent(interval=sample_seconds)
    net1 = psutil.net_io_counters()
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    host = _safe(sup.host_info, {})
    core = _safe(sup.core_info, {})
    boot_us = host.get("boot_timestamp")
    uptime = int(time.time() - boot_us / 1e6) if boot_us else int(time.time() - psutil.boot_time())
    load = os.getloadavg()
    kernel = " · ".join(x for x in [host.get("kernel"),
                                    host.get("operating_system", "").replace("Home Assistant OS", "HAOS") or None,
                                    f"Core {core['version']}" if core.get("version") else None] if x)
    containers = []
    for a in _safe(sup.addons, []):
        c = {"name": a.get("name", a["slug"]), "image": str(a.get("version", "")), "state": a.get("state", "unknown"),
             "health": "none", "status": f"{a.get('state', 'unknown')} · {a['slug']}"}
        if addon_stats and a.get("state") == "started":
            st = _safe(lambda: sup.addon_stats(a["slug"]), None)
            if st:
                c["cpu_pct"] = round(float(st.get("cpu_percent", 0)), 2)
                c["mem_mb"] = round(float(st.get("memory_usage", 0)) / 2**20)
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
            "disk_root_total_gb": float(host.get("disk_total", 0) or 0),
            "disk_root_used_gb": float(host.get("disk_used", 0) or 0),
            "net_rx_bps": max(0, int((net1.bytes_recv - net0.bytes_recv) * 8 / max(sample_seconds, 0.01))),
            "net_tx_bps": max(0, int((net1.bytes_sent - net0.bytes_sent) * 8 / max(sample_seconds, 0.01))),
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


def main() -> int:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        print("console-agent: SUPERVISOR_TOKEN missing; is hassio_api set in config.yaml?", flush=True)
        return 2
    opts = json.load(open(OPTIONS))
    ingest_token = opts.get("ingest_token", "")
    if not ingest_token:
        print("console-agent: ingest_token option is empty; set it in the add-on configuration. Idling.", flush=True)
    sup = Supervisor(token)
    interval = int(opts.get("interval_seconds", 30))
    while True:
        started = time.time()
        if ingest_token:
            body = json.dumps(build_snapshot(sup, bool(opts.get("addon_stats", True))), separators=(",", ":")).encode()
            push(opts["ingest_url"], ingest_token, body)
        time.sleep(max(1.0, interval - (time.time() - started)))


if __name__ == "__main__":
    sys.exit(main())
