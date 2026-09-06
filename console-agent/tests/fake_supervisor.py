"""A stand-in for the HAOS Supervisor REST API.

Every shape below was recorded from the live HA box on 2026-09-06 (see the
spec's "Facts verified on the live HA box" section) and then trimmed to the
fields the agent actually reads, plus enough neighbours to prove we ignore
them. The three add-ons cover the three states the real box reports today:
22 started, 4 stopped, 1 error.
"""


class SupervisorDown(RuntimeError):
    """What every method raises when the fake is constructed with fail=True."""


HOST_INFO = {
    "hostname": "homeassistant",
    "operating_system": "Home Assistant OS 18.2",
    "kernel": "6.18.39-haos",
    "disk_total": 433.8,
    "disk_used": 137.5,
    "disk_free": 296.3,
    "boot_timestamp": 1787800087113548,
}

CORE_INFO = {"version": "2026.9.1", "arch": "amd64", "machine": "generic-x86-64"}

ADDONS = [
    {"slug": "a0d7b954_glances", "name": "Glances", "state": "started", "version": "0.22.1"},
    {"slug": "local_stopped", "name": "Zigbee Bridge", "state": "stopped", "version": "3.1.0"},
    {"slug": "local_broken", "name": "Aardvark Exporter", "state": "error", "version": "0.4.2"},
]

ADDON_STATS = {
    "cpu_percent": 0.44,
    "memory_usage": 64602112,
    "memory_limit": 17716740096,
    "memory_percent": 0.36,
    "network_rx": 118237,
    "network_tx": 90113,
    "blk_read": 0,
    "blk_write": 4096,
}


class FakeSupervisor:
    """Duck-types app.main.Supervisor. Records which slugs were asked for stats."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.stats_calls: list[str] = []

    def _check(self):
        if self.fail:
            raise SupervisorDown("supervisor unreachable")

    def host_info(self):
        self._check()
        return dict(HOST_INFO)

    def core_info(self):
        self._check()
        return dict(CORE_INFO)

    def addons(self):
        self._check()
        return [dict(a) for a in ADDONS]

    def addon_stats(self, slug: str):
        self._check()
        self.stats_calls.append(slug)
        return dict(ADDON_STATS)
