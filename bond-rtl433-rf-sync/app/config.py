from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class CodeTableEntry:
    room: str
    button: str
    stable_id: int


@dataclass(frozen=True)
class RoomDevice:
    room: str
    bond_device_id: str
    max_speed: int


@dataclass(frozen=True)
class Config:
    bond_host: str
    bond_token: str
    rtl433_source: str
    rtl433_source_host: str
    rtl433_source_port: int
    rtl433_frequency: int
    rtl433_sample_rate: int
    rtl433_gain: float
    rtl433_stale_timeout_seconds: float
    rtl433_liveness_probe_interval_seconds: float
    rtl433_liveness_probe_timeout_seconds: float
    debounce_seconds: float
    dry_run: bool
    code_table: tuple[CodeTableEntry, ...]
    room_devices: tuple[RoomDevice, ...]

    def device_for_room(self, room: str) -> RoomDevice:
        for d in self.room_devices:
            if d.room == room:
                return d
        raise ValueError(f"no room_devices entry for room={room!r}")


def load_config(options_path: Path) -> Config:
    raw = json.loads(options_path.read_text())
    return parse_config(raw)


def parse_config(raw: dict) -> Config:
    required = ["bond_host", "bond_token", "rtl433_source", "code_table", "room_devices"]
    missing = [k for k in required if k not in raw]
    if missing:
        raise ConfigError(f"missing required option(s): {', '.join(missing)}")

    rtl433_source = raw["rtl433_source"]
    if rtl433_source not in ("local", "rtl_tcp"):
        raise ConfigError(f"rtl433_source must be 'local' or 'rtl_tcp', got {rtl433_source!r}")
    if rtl433_source == "rtl_tcp" and not raw.get("rtl433_source_host"):
        raise ConfigError("rtl433_source_host is required when rtl433_source is 'rtl_tcp'")

    if not raw["code_table"]:
        raise ConfigError("code_table must not be empty")
    if not raw["room_devices"]:
        raise ConfigError("room_devices must not be empty")

    code_table = tuple(
        CodeTableEntry(room=e["room"], button=e["button"], stable_id=int(e["stable_id"], 16))
        for e in raw["code_table"]
    )
    room_devices = tuple(
        RoomDevice(room=e["room"], bond_device_id=e["bond_device_id"], max_speed=int(e["max_speed"]))
        for e in raw["room_devices"]
    )
    invalid_max_speed = [d.room for d in room_devices if d.max_speed < 1]
    if invalid_max_speed:
        raise ConfigError(
            f"room_devices max_speed must be >= 1, got invalid entries for room(s): "
            f"{sorted(invalid_max_speed)}"
        )

    rtl433_stale_timeout_seconds = float(raw.get("rtl433_stale_timeout_seconds", 21600.0))
    if rtl433_stale_timeout_seconds <= 0:
        raise ConfigError(
            "rtl433_stale_timeout_seconds must be > 0, got "
            f"{rtl433_stale_timeout_seconds!r} - a non-positive value makes the "
            "restart loop spin, continuously killing and respawning rtl_433"
        )

    rtl433_liveness_probe_interval_seconds = float(
        raw.get("rtl433_liveness_probe_interval_seconds", 60.0)
    )
    if rtl433_liveness_probe_interval_seconds < 5.0:
        raise ConfigError(
            "rtl433_liveness_probe_interval_seconds must be >= 5.0, got "
            f"{rtl433_liveness_probe_interval_seconds!r} - too short an interval can "
            "livelock the restart loop (a freshly-(re)spawned rtl_433 killed by the "
            "next probe check before it has any real chance to reconnect)"
        )

    rtl433_liveness_probe_timeout_seconds = float(
        raw.get("rtl433_liveness_probe_timeout_seconds", 10.0)
    )
    if rtl433_liveness_probe_timeout_seconds <= 0:
        raise ConfigError(
            "rtl433_liveness_probe_timeout_seconds must be > 0, got "
            f"{rtl433_liveness_probe_timeout_seconds!r}"
        )

    rooms_with_devices = {d.room for d in room_devices}
    rooms_in_code_table = {e.room for e in code_table}
    orphaned = rooms_in_code_table - rooms_with_devices
    if orphaned:
        raise ConfigError(
            f"code_table references room(s) with no room_devices entry: {sorted(orphaned)}"
        )

    return Config(
        bond_host=raw["bond_host"],
        bond_token=raw["bond_token"],
        rtl433_source=rtl433_source,
        rtl433_source_host=raw.get("rtl433_source_host", ""),
        rtl433_source_port=int(raw.get("rtl433_source_port", 1234)),
        rtl433_frequency=int(raw.get("rtl433_frequency", 304250000)),
        rtl433_sample_rate=int(raw.get("rtl433_sample_rate", 2048000)),
        rtl433_gain=float(raw.get("rtl433_gain", 49.6)),
        rtl433_stale_timeout_seconds=rtl433_stale_timeout_seconds,
        rtl433_liveness_probe_interval_seconds=rtl433_liveness_probe_interval_seconds,
        rtl433_liveness_probe_timeout_seconds=rtl433_liveness_probe_timeout_seconds,
        debounce_seconds=float(raw.get("debounce_seconds", 3.0)),
        dry_run=bool(raw.get("dry_run", False)),
        code_table=code_table,
        room_devices=room_devices,
    )
