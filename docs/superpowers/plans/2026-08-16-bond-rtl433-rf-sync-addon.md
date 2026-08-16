# Bond-rtl_433 RF Sync Add-on Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained HA add-on that decodes the Ashby Park fan wall
switches' RF, matches/debounces presses, and corrects Bond's believed state
directly via its local API — replacing the current MQTT + 9 HA automations +
`rest_command` pipeline, without changing any of its proven no-RF safety
discipline.

**Architecture:** Single Python process, packaged as a standard HA add-on
(`python:3.12-slim` base, matching this repo's `markdown-wiki` conventions).
Owns `rtl_433` (subprocess, local USB or remote `rtl_tcp`), matching,
debouncing, Bond's belief-only `PATCH .../state` calls, and a read-only
ingress panel. No MQTT anywhere in this pipeline.

**Tech Stack:** Python 3.12, Flask's own dev server (ingress panel — not
gunicorn; see Task 11 for why), `requests` (Bond HTTP calls), `pytest`
(tests), Docker, HA Supervisor add-on framework.

**Spec:** `docs/superpowers/specs/2026-08-16-bond-rtl433-rf-sync-addon-design.md`

## Global Constraints

- **Only ever call Bond's belief-only `PATCH /v2/devices/<id>/state` local API.**
  Never a real transmit-type action (`TurnOn`, `SetSpeed`, `fan.turn_on`, etc.)
  in response to a detected wall-switch press — Bond's RF is bit-identical to
  the wall switches', so a real command double-transmits and either loops or
  undoes the user's press. This is the single most important constraint in
  this entire plan; every task that touches Bond must respect it.
- **Never call a real Bond control action against a live device without the
  user present and watching it**, even for manual testing/diagnostics.
- The existing HA-automation-based system (9 automations, `rest_command`,
  `fan_wallswitch_bridge.py` on the Pi) **stays running, untouched, until
  Task 14 passes** — it is the safety net throughout development.
- `rtl_tcp` only services one client at a time (no verified multi-client
  support) — any task that needs the Pi's SDR dongle for testing must
  explicitly stop `rtl433-mqtt.service` first, with the user's confirmation,
  and restart it afterward.
- **Pre-existing, carried-forward limitation, confirmed 2026-08-16:** the
  Pi's single RTL-SDR dongle is already shared with an unrelated gas-meter
  project (`rtlamr-mqtt.service`, via `rtl-tcp.service`, currently bound to
  `127.0.0.1` only). `rtl-tcp.service` already `Conflicts=rtl433-mqtt.service`
  — the two projects have never been able to run simultaneously, and this
  plan does not change that. After cutover (Task 15), `rtl-tcp.service` needs
  to bind `0.0.0.0` for the add-on's remote connection, and — because
  `rtl_tcp` serves one client — the add-on and the gas-meter reader still
  can't both be actively connected at once, but that coordination can no
  longer ride on `Conflicts=` between two Pi-local systemd units (one side is
  now inside an add-on container on a different host). This plan does
  **not** invent an automatic arbitration mechanism for that — it documents
  the limitation and leaves manual start/stop coordination (or a future
  second dongle) as the user's call, same as the status quo today.
- Bond device IDs (confirmed, all `max_speed: 3`): living room
  `ce4d90389da6937f`, dining room `33c72108a1a2548d`, bedroom
  `3e9252a7323111d2`. Bond Bridge: `http://192.168.0.110`, local API v2,
  `BOND-Token` header, token in 1Password `op://CLI/bond-bridge-local/credential`.
- The proven decode mechanics from `rtl_433_fan/fan_wallswitch_bridge.py`
  carry over unchanged: `rtl_433 -R 0 -X n=fan,m=OOK_PWM,s=744,l=376,r=900,g=900,t=150,y=0`,
  text output lines matching `^codes\s*:\s*\{25\}([0-9a-f]+)$`, decode as
  `code_int = int(hex, 16)`, `counter = (code_int >> 3) & 0b11`,
  `stable_id = code_int >> 5`. Trailing-edge debounce, 3.0s quiet period
  (tunable). This is empirically validated hardware behavior — don't
  "improve" it without new evidence.

---

### Task 1: Add-on skeleton and deployability check

**Files:**
- Create: `bond-rtl433-rf-sync/config.yaml`
- Create: `bond-rtl433-rf-sync/Dockerfile`
- Create: `bond-rtl433-rf-sync/run.sh`
- Create: `bond-rtl433-rf-sync/app/main.py`
- Create: `bond-rtl433-rf-sync/app/requirements.txt`
- Create: `bond-rtl433-rf-sync/README.md`
- Create: `bond-rtl433-rf-sync/CHANGELOG.md`

**Interfaces:**
- Produces: a bootable add-on skeleton later tasks fill in. `app/main.py`'s
  entry point stays `if __name__ == "__main__": main()` for the rest of the
  plan to build on.

- [ ] **Step 1: Create the add-on directory and config.yaml**

```yaml
name: Bond-rtl_433 RF Sync
slug: bond_rtl433_rf_sync
description: Corrects Bond Bridge's believed fan/light state from wall-switch RF presses, without transmitting anything
version: "0.1.0"
arch:
  - amd64
  - aarch64
startup: services
boot: auto
usb: true
map:
  - data:rw
options:
  bond_host: "192.168.0.110"
  bond_token: ""
  rtl433_source: "local"
  rtl433_source_host: ""
  rtl433_source_port: 1234
  rtl433_frequency: 304250000
  rtl433_sample_rate: 2048000
  rtl433_gain: 49.6
  debounce_seconds: 3.0
  dry_run: false
  code_table:
    - room: livingroom
      button: speed
      stable_id: "1ff"
    - room: livingroom
      button: light
      stable_id: "1f9"
    - room: livingroom
      button: power
      stable_id: "1d9"
    - room: diningroom
      button: speed
      stable_id: "27f"
    - room: diningroom
      button: light
      stable_id: "279"
    - room: diningroom
      button: power
      stable_id: "259"
    - room: bedroom
      button: speed
      stable_id: "2ff"
    - room: bedroom
      button: light
      stable_id: "2f9"
    - room: bedroom
      button: power
      stable_id: "2d9"
  room_devices:
    - room: livingroom
      bond_device_id: "ce4d90389da6937f"
      max_speed: 3
    - room: diningroom
      bond_device_id: "33c72108a1a2548d"
      max_speed: 3
    - room: bedroom
      bond_device_id: "3e9252a7323111d2"
      max_speed: 3
schema:
  bond_host: str
  bond_token: password
  rtl433_source: list(local|rtl_tcp)
  rtl433_source_host: str?
  rtl433_source_port: port?
  rtl433_frequency: int
  rtl433_sample_rate: int
  rtl433_gain: float
  debounce_seconds: float
  dry_run: bool
  code_table:
    - room: str
      button: list(power|light|speed)
      stable_id: str
  room_devices:
    - room: str
      bond_device_id: str
      max_speed: int
ingress: true
ingress_port: 8100
panel_icon: mdi:fan-alert
```

- [ ] **Step 2: Create the minimal entry point**

`app/main.py`:
```python
#!/usr/bin/env python3
"""Bond-rtl_433 RF Sync add-on entry point."""
import sys


def main() -> int:
    print("bond-rtl433-rf-sync: starting up", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Create requirements.txt**

`app/requirements.txt`:
```
Flask==3.0.3
requests==2.32.3
```

(No `gunicorn` — Task 11 runs the ingress panel via Flask's own
`app.run()` directly in-process, deliberately avoiding gunicorn's
worker/fork model, which would risk spawning duplicate background
pipeline threads.)

- [ ] **Step 4: Create the Dockerfile**

```dockerfile
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends rtl-433 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8100

CMD ["/run.sh"]
```

- [ ] **Step 5: Create run.sh**

```sh
#!/bin/sh
set -eu

exec python3 /app/main.py
```

```bash
chmod +x bond-rtl433-rf-sync/run.sh
```

- [ ] **Step 6: Create README.md and CHANGELOG.md**

`README.md`:
```markdown
# Bond-rtl_433 RF Sync

Corrects Bond Bridge's believed fan/light state from Ashby Park ceiling fan
wall-switch RF presses, without transmitting anything to the physical
devices — replaces an MQTT + Home-Assistant-automation pipeline with a
single self-contained add-on.

## Configuration

- `bond_host` / `bond_token` — Bond Bridge local API address and token.
- `rtl433_source` — `local` (USB dongle attached to this host, pick it in
  the Hardware tab) or `rtl_tcp` (point at a remote `rtl_tcp` server, e.g.
  a Raspberry Pi elsewhere on the network).
- `code_table` — maps each switch's decoded RF `stable_id` to a room/button.
- `room_devices` — maps each room to its Bond `device_id` and `max_speed`.
- `dry_run` — when true, logs the Bond call that would be made without
  sending it.

## Status

Under active development — see the project's implementation plan and design
spec in `docs/superpowers/`.
```

`CHANGELOG.md`:
```markdown
# Changelog

## 0.1.0

- Initial add-on skeleton.
```

- [ ] **Step 7: Build the Docker image locally and verify it starts**

```bash
cd bond-rtl433-rf-sync
docker build -t bond-rtl433-rf-sync:dev .
docker run --rm bond-rtl433-rf-sync:dev
```

Expected output: `bond-rtl433-rf-sync: starting up`, exit code 0.

- [ ] **Step 8: Commit**

```bash
cd /home/mark/projects/tuttleHAaddons
git add bond-rtl433-rf-sync/
git commit -m "Add bond-rtl433-rf-sync add-on skeleton"
```

---

---

### Task 2: Config loader

**Files:**
- Create: `bond-rtl433-rf-sync/app/config.py`
- Test: `bond-rtl433-rf-sync/tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first pure-logic module).
- Produces: `Config` (frozen dataclass: `bond_host: str`, `bond_token: str`,
  `rtl433_source: str`, `rtl433_source_host: str`, `rtl433_source_port: int`,
  `rtl433_frequency: int`, `rtl433_sample_rate: int`, `rtl433_gain: float`,
  `debounce_seconds: float`, `dry_run: bool`,
  `code_table: tuple[CodeTableEntry, ...]`, `room_devices: tuple[RoomDevice, ...]`,
  method `device_for_room(room: str) -> RoomDevice`). `CodeTableEntry`
  (`room: str`, `button: str`, `stable_id: int`). `RoomDevice` (`room: str`,
  `bond_device_id: str`, `max_speed: int`). `ConfigError(ValueError)`.
  `load_config(options_path: Path) -> Config`. `parse_config(raw: dict) -> Config`.
  Later tasks import `Config`, `CodeTableEntry`, `RoomDevice`, `ConfigError`,
  `load_config`, `parse_config` from `config.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import pytest
from app.config import Config, ConfigError, parse_config


def _base_raw():
    return {
        "bond_host": "192.168.0.110",
        "bond_token": "secret",
        "rtl433_source": "local",
        "code_table": [
            {"room": "livingroom", "button": "speed", "stable_id": "1ff"},
        ],
        "room_devices": [
            {"room": "livingroom", "bond_device_id": "ce4d90389da6937f", "max_speed": 3},
        ],
    }


def test_parse_config_valid_minimal():
    cfg = parse_config(_base_raw())
    assert isinstance(cfg, Config)
    assert cfg.bond_host == "192.168.0.110"
    assert cfg.code_table[0].stable_id == 0x1FF
    assert cfg.debounce_seconds == 3.0
    assert cfg.dry_run is False


def test_parse_config_missing_required_field():
    raw = _base_raw()
    del raw["bond_host"]
    with pytest.raises(ConfigError, match="bond_host"):
        parse_config(raw)


def test_parse_config_invalid_rtl433_source():
    raw = _base_raw()
    raw["rtl433_source"] = "usb_stick"
    with pytest.raises(ConfigError, match="rtl433_source"):
        parse_config(raw)


def test_parse_config_rtl_tcp_requires_host():
    raw = _base_raw()
    raw["rtl433_source"] = "rtl_tcp"
    with pytest.raises(ConfigError, match="rtl433_source_host"):
        parse_config(raw)


def test_parse_config_rtl_tcp_with_host_succeeds():
    raw = _base_raw()
    raw["rtl433_source"] = "rtl_tcp"
    raw["rtl433_source_host"] = "192.168.0.50"
    cfg = parse_config(raw)
    assert cfg.rtl433_source_host == "192.168.0.50"
    assert cfg.rtl433_source_port == 1234


def test_parse_config_empty_code_table():
    raw = _base_raw()
    raw["code_table"] = []
    with pytest.raises(ConfigError, match="code_table"):
        parse_config(raw)


def test_parse_config_orphaned_room_in_code_table():
    raw = _base_raw()
    raw["code_table"].append({"room": "bedroom", "button": "power", "stable_id": "2d9"})
    with pytest.raises(ConfigError, match="bedroom"):
        parse_config(raw)


def test_device_for_room_lookup():
    cfg = parse_config(_base_raw())
    device = cfg.device_for_room("livingroom")
    assert device.bond_device_id == "ce4d90389da6937f"
    assert device.max_speed == 3


def test_device_for_room_missing_raises():
    cfg = parse_config(_base_raw())
    with pytest.raises(ValueError, match="diningroom"):
        cfg.device_for_room("diningroom")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd bond-rtl433-rf-sync
pip install -r app/requirements.txt pytest
python -m pytest tests/test_config.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 3: Write the implementation**

`app/config.py`:
```python
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
        debounce_seconds=float(raw.get("debounce_seconds", 3.0)),
        dry_run=bool(raw.get("dry_run", False)),
        code_table=code_table,
        room_devices=room_devices,
    )
```

Add an empty `bond-rtl433-rf-sync/app/__init__.py` and `bond-rtl433-rf-sync/tests/__init__.py`
so `app.config` imports cleanly, and `bond-rtl433-rf-sync/pytest.ini`:
```ini
[pytest]
pythonpath = .
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_config.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/__init__.py tests/test_config.py tests/__init__.py pytest.ini
git commit -m "Add config loader for bond-rtl433-rf-sync"
```

---


### Task 3: Matcher — decode rtl_433 text lines against the code table

**Files:**
- Create: `bond-rtl433-rf-sync/app/matcher.py`
- Test: `bond-rtl433-rf-sync/tests/test_matcher.py`

**Interfaces:**
- Consumes: `Config`, `CodeTableEntry` from `app/config.py` (Task 2).
- Produces: `SPEED_COUNTER_TO_PERCENTAGE: dict[int, int]` (`{0: 33, 1: 66, 2: 100, 3: 0}`).
  `LINE_RE: re.Pattern` (matches `codes : {25}<hex>` lines).
  `decode_hex(hex_code: str) -> tuple[int, int]` (returns `(stable_id, counter)`).
  `@dataclass(frozen=True) class MatchedEvent: room: str; button: str; percentage: int | None`.
  `match_line(line: str, code_table: tuple[CodeTableEntry, ...]) -> MatchedEvent | None`.
  Task 4 (Debouncer) and Task 9 (Main) consume `MatchedEvent` and `match_line`.

- [ ] **Step 1: Write the failing tests**

`tests/test_matcher.py`:
```python
from app.config import CodeTableEntry
from app.matcher import MatchedEvent, decode_hex, match_line

CODE_TABLE = (
    CodeTableEntry(room="livingroom", button="speed", stable_id=0x1FF),
    CodeTableEntry(room="livingroom", button="light", stable_id=0x1F9),
    CodeTableEntry(room="livingroom", button="power", stable_id=0x1D9),
    CodeTableEntry(room="bedroom", button="speed", stable_id=0x2FF),
)


def test_decode_hex_splits_stable_id_and_counter():
    # 0x1ff0 >> 3 & 0b11 == 0b10 == counter 2; 0x1ff0 >> 5 == 0xff... use a real
    # example: code 0x3fe0 -> counter = (0x3fe0 >> 3) & 0b11, stable_id = 0x3fe0 >> 5
    stable_id, counter = decode_hex("3fe0")
    assert stable_id == (0x3FE0 >> 5)
    assert counter == ((0x3FE0 >> 3) & 0b11)


def test_match_line_speed_button_maps_counter_to_percentage():
    # stable_id 0x1ff, counter 0 (=33%): code = (0x1ff << 5) | (0 << 3) = 0x3fe0
    line = "codes     : {25}3fe0"
    event = match_line(line, CODE_TABLE)
    assert event == MatchedEvent(room="livingroom", button="speed", percentage=33)


def test_match_line_speed_button_counter_3_is_off():
    # counter 3: code = (0x1ff << 5) | (3 << 3) = 0x3fe0 | 0x18 = 0x3ff8
    line = "codes     : {25}3ff8"
    event = match_line(line, CODE_TABLE)
    assert event == MatchedEvent(room="livingroom", button="speed", percentage=0)


def test_match_line_power_button_has_no_percentage():
    # stable_id 0x1d9: code = 0x1d9 << 5 = 0x3b20
    line = "codes     : {25}3b20"
    event = match_line(line, CODE_TABLE)
    assert event == MatchedEvent(room="livingroom", button="power", percentage=None)


def test_match_line_unknown_stable_id_returns_none():
    line = "codes     : {25}ffffff"
    assert match_line(line, CODE_TABLE) is None


def test_match_line_non_matching_format_returns_none():
    assert match_line("some unrelated rtl_433 output", CODE_TABLE) is None
    assert match_line("", CODE_TABLE) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd bond-rtl433-rf-sync
python -m pytest tests/test_matcher.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.matcher'`.

- [ ] **Step 3: Write the implementation**

`app/matcher.py`:
```python
from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import CodeTableEntry

SPEED_COUNTER_TO_PERCENTAGE = {0: 33, 1: 66, 2: 100, 3: 0}

LINE_RE = re.compile(r"codes\s*:\s*\{25\}([0-9a-f]+)$")


@dataclass(frozen=True)
class MatchedEvent:
    room: str
    button: str
    percentage: int | None


def decode_hex(hex_code: str) -> tuple[int, int]:
    code_int = int(hex_code, 16)
    counter = (code_int >> 3) & 0b11
    stable_id = code_int >> 5
    return stable_id, counter


def match_line(
    line: str, code_table: tuple[CodeTableEntry, ...]
) -> MatchedEvent | None:
    m = LINE_RE.search(line.rstrip())
    if not m:
        return None
    stable_id, counter = decode_hex(m.group(1))
    for entry in code_table:
        if entry.stable_id == stable_id:
            percentage = (
                SPEED_COUNTER_TO_PERCENTAGE[counter] if entry.button == "speed" else None
            )
            return MatchedEvent(room=entry.room, button=entry.button, percentage=percentage)
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_matcher.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/matcher.py tests/test_matcher.py
git commit -m "Add RF line matcher for bond-rtl433-rf-sync"
```

---

### Task 4: Debouncer — trailing-edge quiet-period coalescing

**Files:**
- Create: `bond-rtl433-rf-sync/app/debouncer.py`
- Test: `bond-rtl433-rf-sync/tests/test_debouncer.py`

**Interfaces:**
- Consumes: `MatchedEvent` from `app/matcher.py` (Task 3).
- Produces: `class Debouncer` with `__init__(self, quiet_seconds: float, on_fire: Callable[[MatchedEvent], None])`,
  `see(self, event: MatchedEvent) -> None`, `join_pending(self, timeout: float | None = None) -> None`.
  Task 9 (Main) wires `Debouncer.see` as the callback for each matched RF event,
  and `on_fire` as the entry point into the Bond Client.

- [ ] **Step 1: Write the failing tests**

`tests/test_debouncer.py`:
```python
import time

from app.debouncer import Debouncer
from app.matcher import MatchedEvent

QUIET = 0.05


def test_single_event_fires_once_after_quiet_period():
    fired = []
    d = Debouncer(QUIET, fired.append)
    event = MatchedEvent(room="livingroom", button="power", percentage=None)
    d.see(event)
    d.join_pending(timeout=1)
    assert fired == [event]


def test_repeated_events_same_key_coalesce_into_one_fire():
    fired = []
    d = Debouncer(QUIET, fired.append)
    event = MatchedEvent(room="livingroom", button="speed", percentage=66)
    for _ in range(5):
        d.see(event)
        time.sleep(QUIET / 5)
    d.join_pending(timeout=1)
    assert fired == [event]


def test_different_keys_fire_independently():
    fired = []
    d = Debouncer(QUIET, fired.append)
    e1 = MatchedEvent(room="livingroom", button="power", percentage=None)
    e2 = MatchedEvent(room="bedroom", button="light", percentage=None)
    d.see(e1)
    d.see(e2)
    d.join_pending(timeout=1)
    assert {e.room for e in fired} == {"livingroom", "bedroom"}


def test_rapid_repeats_delay_firing_past_naive_quiet_period():
    fired = []
    d = Debouncer(QUIET, fired.append)
    event = MatchedEvent(room="livingroom", button="power", percentage=None)
    start = time.monotonic()
    for _ in range(4):
        d.see(event)
        time.sleep(QUIET * 0.6)
    d.join_pending(timeout=1)
    elapsed = time.monotonic() - start
    assert fired == [event]
    assert elapsed >= QUIET
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd bond-rtl433-rf-sync
python -m pytest tests/test_debouncer.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.debouncer'`.

- [ ] **Step 3: Write the implementation**

`app/debouncer.py`:
```python
from __future__ import annotations

import threading
from typing import Callable

from app.matcher import MatchedEvent

FireCallback = Callable[[MatchedEvent], None]


class Debouncer:
    """Trailing-edge debounce: coalesces repeated matches of the same
    (room, button, percentage) into one callback firing `quiet_seconds`
    after the LAST matching event, resetting the timer on every repeat.
    Mirrors fan_wallswitch_bridge.py's proven behavior (a held/repeated
    button re-transmits several times; we want one logical event per
    physical press, not one per RF repeat).
    """

    def __init__(self, quiet_seconds: float, on_fire: FireCallback):
        self._quiet_seconds = quiet_seconds
        self._on_fire = on_fire
        self._timers: dict[tuple[str, str, int | None], threading.Timer] = {}
        self._lock = threading.Lock()

    def see(self, event: MatchedEvent) -> None:
        key = (event.room, event.button, event.percentage)
        with self._lock:
            existing = self._timers.get(key)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(self._quiet_seconds, self._fire, args=(key, event))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _fire(self, key: tuple[str, str, int | None], event: MatchedEvent) -> None:
        with self._lock:
            self._timers.pop(key, None)
        self._on_fire(event)

    def join_pending(self, timeout: float | None = None) -> None:
        """Block until all pending timers have fired - used by tests and
        graceful shutdown so an in-flight event isn't lost."""
        with self._lock:
            timers = list(self._timers.values())
        for t in timers:
            t.join(timeout=timeout)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_debouncer.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/debouncer.py tests/test_debouncer.py
git commit -m "Add trailing-edge debouncer for bond-rtl433-rf-sync"
```

---

### Task 5: Last-Speed Store — persisted per-room resume speed

**Files:**
- Create: `bond-rtl433-rf-sync/app/last_speed_store.py`
- Test: `bond-rtl433-rf-sync/tests/test_last_speed_store.py`

**Interfaces:**
- Consumes: nothing beyond the standard library.
- Produces: `class LastSpeedStore` with `__init__(self, path: Path)`,
  `get(self, room: str, default: int = 100) -> int`,
  `set(self, room: str, percentage: int) -> None`. Task 6 (Bond Client)
  calls `get()` to compute a power-on resume target and `set()` after every
  non-zero speed event, functionally replacing
  `input_number.<room>_last_fan_speed`.

- [ ] **Step 1: Write the failing tests**

`tests/test_last_speed_store.py`:
```python
import json

from app.last_speed_store import LastSpeedStore


def test_get_returns_default_when_room_unknown(tmp_path):
    store = LastSpeedStore(tmp_path / "last_speed.json")
    assert store.get("bedroom") == 100
    assert store.get("bedroom", default=66) == 66


def test_set_then_get_returns_stored_value(tmp_path):
    store = LastSpeedStore(tmp_path / "last_speed.json")
    store.set("bedroom", 33)
    assert store.get("bedroom") == 33


def test_set_zero_percentage_is_ignored(tmp_path):
    store = LastSpeedStore(tmp_path / "last_speed.json")
    store.set("bedroom", 66)
    store.set("bedroom", 0)
    assert store.get("bedroom") == 66


def test_persists_across_instances(tmp_path):
    path = tmp_path / "last_speed.json"
    LastSpeedStore(path).set("livingroom", 100)
    reloaded = LastSpeedStore(path)
    assert reloaded.get("livingroom") == 100


def test_corrupted_file_falls_back_to_empty(tmp_path):
    path = tmp_path / "last_speed.json"
    path.write_text("not valid json{{{")
    store = LastSpeedStore(path)
    assert store.get("diningroom") == 100
    store.set("diningroom", 33)
    assert json.loads(path.read_text()) == {"diningroom": 33}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_last_speed_store.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.last_speed_store'`.

- [ ] **Step 3: Write the implementation**

`app/last_speed_store.py`:
```python
from __future__ import annotations

import json
import threading
from pathlib import Path


class LastSpeedStore:
    """Persists each room's last known non-zero fan speed percentage,
    functionally replacing HA's input_number.<room>_last_fan_speed helpers.
    """

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def get(self, room: str, default: int = 100) -> int:
        with self._lock:
            return self._data.get(room, default)

    def set(self, room: str, percentage: int) -> None:
        if percentage <= 0:
            return
        with self._lock:
            self._data[room] = percentage
            self._path.write_text(json.dumps(self._data))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_last_speed_store.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/last_speed_store.py tests/test_last_speed_store.py
git commit -m "Add persisted last-speed store for bond-rtl433-rf-sync"
```

---

### Task 6: Bond Client — belief-only local API calls

**Files:**
- Create: `bond-rtl433-rf-sync/app/bond_client.py`
- Test: `bond-rtl433-rf-sync/tests/test_bond_client.py`

**Interfaces:**
- Consumes: `RoomDevice` from `app/config.py` (Task 2), `MatchedEvent` from
  `app/matcher.py` (Task 3).
- Produces: `class BondClient` with `__init__(self, host: str, token: str, session: requests.Session | None = None)`,
  `get_state(self, device_id: str) -> dict`, `patch_state(self, device_id: str, body: dict) -> dict`.
  `native_speed_step(percentage: int, max_speed: int) -> int`.
  `build_speed_event_body(event: MatchedEvent, device: RoomDevice) -> dict`.
  `build_power_toggle_body(currently_on: bool, last_speed_percentage: int, device: RoomDevice) -> dict`.
  `build_light_toggle_body(currently_on: bool) -> dict`.
  Task 9 (Main) is the only caller of the `build_*` functions and
  `patch_state`/`get_state`.

**This is the single most safety-critical module in the whole add-on** —
`BondClient` must only ever expose `get_state`/`patch_state` (the belief-only
`PATCH .../state` endpoint). It must never grow a method that calls Bond's
`/actions/<name>` endpoints (real transmit-type commands) — that's the exact
mistake that caused a real physical feedback loop earlier in this project.

- [ ] **Step 1: Write the failing tests**

`tests/test_bond_client.py`:
```python
import pytest
import requests

from app.bond_client import (
    BondClient,
    build_light_toggle_body,
    build_power_toggle_body,
    build_speed_event_body,
    native_speed_step,
)
from app.config import RoomDevice
from app.matcher import MatchedEvent

LIVINGROOM = RoomDevice(room="livingroom", bond_device_id="ce4d90389da6937f", max_speed=3)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, headers, None))
        return self.response

    def patch(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("PATCH", url, headers, json))
        return self.response


def test_native_speed_step_rounds_up_to_nearest_step():
    assert native_speed_step(33, max_speed=3) == 1
    assert native_speed_step(66, max_speed=3) == 2
    assert native_speed_step(100, max_speed=3) == 3


def test_build_speed_event_body_zero_is_power_off():
    event = MatchedEvent(room="livingroom", button="speed", percentage=0)
    assert build_speed_event_body(event, LIVINGROOM) == {"power": 0}


def test_build_speed_event_body_nonzero_sets_power_and_speed():
    event = MatchedEvent(room="livingroom", button="speed", percentage=66)
    assert build_speed_event_body(event, LIVINGROOM) == {"power": 1, "speed": 2}


def test_build_power_toggle_body_currently_on_turns_off():
    body = build_power_toggle_body(currently_on=True, last_speed_percentage=66, device=LIVINGROOM)
    assert body == {"power": 0}


def test_build_power_toggle_body_currently_off_resumes_last_speed():
    body = build_power_toggle_body(currently_on=False, last_speed_percentage=66, device=LIVINGROOM)
    assert body == {"power": 1, "speed": 2}


def test_build_light_toggle_body_on_to_off():
    assert build_light_toggle_body(currently_on=True) == {"light": 0}


def test_build_light_toggle_body_off_to_on():
    assert build_light_toggle_body(currently_on=False) == {"light": 1}


def test_bond_client_get_state_sends_correct_request():
    session = FakeSession(FakeResponse(json_data={"power": 1, "speed": 2, "light": 0}))
    client = BondClient("192.168.0.110", "tok123", session=session)
    result = client.get_state("ce4d90389da6937f")
    assert result == {"power": 1, "speed": 2, "light": 0}
    method, url, headers, body = session.calls[0]
    assert method == "GET"
    assert url == "http://192.168.0.110/v2/devices/ce4d90389da6937f/state"
    assert headers["BOND-Token"] == "tok123"


def test_bond_client_patch_state_sends_correct_request_and_headers():
    session = FakeSession(FakeResponse(json_data={"power": 1}))
    client = BondClient("192.168.0.110", "tok123", session=session)
    result = client.patch_state("ce4d90389da6937f", {"power": 1, "speed": 2})
    assert result == {"power": 1}
    method, url, headers, body = session.calls[0]
    assert method == "PATCH"
    assert url == "http://192.168.0.110/v2/devices/ce4d90389da6937f/state"
    assert headers["BOND-Token"] == "tok123"
    assert headers["Content-Type"] == "application/json"
    assert body == {"power": 1, "speed": 2}


def test_bond_client_raises_on_http_error():
    session = FakeSession(FakeResponse(status_code=500))
    client = BondClient("192.168.0.110", "tok123", session=session)
    with pytest.raises(requests.HTTPError):
        client.get_state("ce4d90389da6937f")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd bond-rtl433-rf-sync
python -m pytest tests/test_bond_client.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.bond_client'`.

- [ ] **Step 3: Write the implementation**

`app/bond_client.py`:
```python
from __future__ import annotations

import math

import requests

from app.config import RoomDevice
from app.matcher import MatchedEvent


class BondClient:
    """Talks ONLY to Bond Bridge's belief-only local API
    (`GET`/`PATCH /v2/devices/<id>/state`). Never call a real transmit-type
    `/actions/<name>` endpoint from this class - that's what caused the
    physical RF feedback loop this whole add-on exists to avoid.
    """

    def __init__(self, host: str, token: str, session: requests.Session | None = None):
        self._base_url = f"http://{host}/v2"
        self._token = token
        self._session = session or requests.Session()

    def get_state(self, device_id: str) -> dict:
        resp = self._session.get(
            f"{self._base_url}/devices/{device_id}/state",
            headers={"BOND-Token": self._token},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()

    def patch_state(self, device_id: str, body: dict) -> dict:
        resp = self._session.patch(
            f"{self._base_url}/devices/{device_id}/state",
            headers={"BOND-Token": self._token, "Content-Type": "application/json"},
            json=body,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()


def native_speed_step(percentage: int, max_speed: int) -> int:
    """Converts a wall-switch percentage (33/66/100) to Bond's native speed
    step (1..max_speed). Percentage 0 is handled by callers as power-off,
    not a speed step."""
    return math.ceil(percentage / 100 * max_speed)


def build_speed_event_body(event: MatchedEvent, device: RoomDevice) -> dict:
    """Body for a 'speed' button event: 0% means off; anything else sets
    power on plus the corresponding native speed step."""
    assert event.button == "speed"
    assert event.percentage is not None
    if event.percentage == 0:
        return {"power": 0}
    return {"power": 1, "speed": native_speed_step(event.percentage, device.max_speed)}


def build_power_toggle_body(
    currently_on: bool, last_speed_percentage: int, device: RoomDevice
) -> dict:
    """Body for a 'power' button event: toggles off if currently on,
    otherwise turns on to the last known non-zero speed."""
    if currently_on:
        return {"power": 0}
    return {"power": 1, "speed": native_speed_step(last_speed_percentage, device.max_speed)}


def build_light_toggle_body(currently_on: bool) -> dict:
    """Body for a 'light' button event: simple believed-state toggle."""
    return {"light": 0 if currently_on else 1}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_bond_client.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add app/bond_client.py tests/test_bond_client.py
git commit -m "Add Bond belief-only API client for bond-rtl433-rf-sync"
```

---

### Task 7: Event Log — ring buffer + per-room state snapshot

**Files:**
- Create: `bond-rtl433-rf-sync/app/event_log.py`
- Test: `bond-rtl433-rf-sync/tests/test_event_log.py`

**Interfaces:**
- Consumes: nothing beyond the standard library.
- Produces: `@dataclass(frozen=True) class LoggedEvent: timestamp: float; room: str; button: str; percentage: int | None; body: dict; result: str`.
  `class EventLog` with `__init__(self, max_events: int = 200)`,
  `record(self, room: str, button: str, percentage: int | None, body: dict, result: str) -> None`,
  `recent_events(self) -> list[LoggedEvent]` (newest first),
  `current_state(self) -> dict[str, dict]`. Task 9 (Main) calls `record()`
  after every Bond call attempt; Task 10 (Ingress panel) calls
  `recent_events()`/`current_state()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_event_log.py`:
```python
from app.event_log import EventLog


def test_record_appends_event():
    log = EventLog()
    log.record("livingroom", "speed", 66, {"power": 1, "speed": 2}, "ok")
    events = log.recent_events()
    assert len(events) == 1
    assert events[0].room == "livingroom"
    assert events[0].body == {"power": 1, "speed": 2}
    assert events[0].result == "ok"


def test_record_updates_current_state_for_room():
    log = EventLog()
    log.record("livingroom", "speed", 66, {"power": 1, "speed": 2}, "ok")
    assert log.current_state() == {"livingroom": {"power": 1, "speed": 2}}


def test_current_state_merges_multiple_updates_for_same_room():
    log = EventLog()
    log.record("livingroom", "speed", 66, {"power": 1, "speed": 2}, "ok")
    log.record("livingroom", "light", None, {"light": 1}, "ok")
    assert log.current_state() == {"livingroom": {"power": 1, "speed": 2, "light": 1}}


def test_recent_events_returns_newest_first():
    log = EventLog()
    log.record("livingroom", "power", None, {"power": 1}, "ok")
    log.record("bedroom", "light", None, {"light": 1}, "ok")
    events = log.recent_events()
    assert [e.room for e in events] == ["bedroom", "livingroom"]


def test_ring_buffer_respects_max_events():
    log = EventLog(max_events=3)
    for i in range(5):
        log.record("livingroom", "power", None, {"power": i}, "ok")
    events = log.recent_events()
    assert len(events) == 3
    # newest first, oldest two (body power=0, power=1) dropped
    assert [e.body["power"] for e in events] == [4, 3, 2]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd bond-rtl433-rf-sync
python -m pytest tests/test_event_log.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.event_log'`.

- [ ] **Step 3: Write the implementation**

`app/event_log.py`:
```python
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LoggedEvent:
    timestamp: float
    room: str
    button: str
    percentage: int | None
    body: dict
    result: str


class EventLog:
    """In-memory ring buffer of recent Bond corrections, plus a live
    per-room believed-state snapshot - both feed the ingress panel."""

    def __init__(self, max_events: int = 200):
        self._events: deque[LoggedEvent] = deque(maxlen=max_events)
        self._state: dict[str, dict] = {}
        self._lock = threading.Lock()

    def record(
        self, room: str, button: str, percentage: int | None, body: dict, result: str
    ) -> None:
        event = LoggedEvent(
            timestamp=time.time(),
            room=room,
            button=button,
            percentage=percentage,
            body=body,
            result=result,
        )
        with self._lock:
            self._events.append(event)
            self._state.setdefault(room, {}).update(body)

    def recent_events(self) -> list[LoggedEvent]:
        with self._lock:
            return list(reversed(self._events))

    def current_state(self) -> dict[str, dict]:
        with self._lock:
            return {room: dict(state) for room, state in self._state.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_event_log.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/event_log.py tests/test_event_log.py
git commit -m "Add event log for bond-rtl433-rf-sync"
```

---

### Task 8: RF Source Manager — rtl_433 subprocess, local or rtl_tcp

**Files:**
- Create: `bond-rtl433-rf-sync/app/rf_source.py`
- Test: `bond-rtl433-rf-sync/tests/test_rf_source.py`

**Interfaces:**
- Consumes: `Config` from `app/config.py` (Task 2).
- Produces: `FLEX_DECODER: str`. `build_source_args(config: Config) -> list[str]`.
  `rtl433_command(config: Config) -> list[str]`. `class RFSourceManager` with
  `__init__(self, config: Config, restart_backoff_seconds: float = 5.0, command: list[str] | None = None)`,
  `lines(self) -> Iterator[str]`, `stop(self) -> None`. Task 9 (Main)
  iterates `RFSourceManager(config).lines()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_rf_source.py`:
```python
from app.config import parse_config
from app.rf_source import RFSourceManager, build_source_args, rtl433_command


def _config(**overrides):
    raw = {
        "bond_host": "192.168.0.110",
        "bond_token": "secret",
        "rtl433_source": "local",
        "rtl433_frequency": 304250000,
        "rtl433_sample_rate": 2048000,
        "rtl433_gain": 49.6,
        "code_table": [{"room": "livingroom", "button": "power", "stable_id": "1d9"}],
        "room_devices": [
            {"room": "livingroom", "bond_device_id": "ce4d90389da6937f", "max_speed": 3}
        ],
    }
    raw.update(overrides)
    return parse_config(raw)


def test_build_source_args_local_mode_has_no_device_flag():
    args = build_source_args(_config(rtl433_source="local"))
    assert "-d" not in args
    assert args == ["-f", "304250000", "-s", "2048000", "-g", "49.6"]


def test_build_source_args_rtl_tcp_mode_prepends_device_flag():
    args = build_source_args(
        _config(
            rtl433_source="rtl_tcp",
            rtl433_source_host="192.168.0.50",
            rtl433_source_port=1234,
        )
    )
    assert args[:2] == ["-d", "rtl_tcp:192.168.0.50:1234"]
    assert args[2:] == ["-f", "304250000", "-s", "2048000", "-g", "49.6"]


def test_rtl433_command_disables_builtin_protocols_and_sets_flex_decoder():
    cmd = rtl433_command(_config())
    assert cmd[0] == "rtl_433"
    assert cmd[cmd.index("-R") + 1] == "0"
    assert "m=OOK_PWM" in cmd[cmd.index("-X") + 1]


def test_lines_yields_subprocess_stdout():
    manager = RFSourceManager(
        _config(),
        command=["python3", "-c", "print('line1'); print('line2')"],
    )
    lines = []
    for line in manager.lines():
        lines.append(line)
        if len(lines) == 2:
            manager.stop()
    assert lines == ["line1", "line2"]


def test_lines_restarts_process_after_it_exits():
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.05,
        command=["python3", "-c", "print('tick')"],
    )
    lines = []
    for line in manager.lines():
        lines.append(line)
        if len(lines) == 3:
            manager.stop()
            break
    assert lines == ["tick", "tick", "tick"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_rf_source.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rf_source'`.

- [ ] **Step 3: Write the implementation**

`app/rf_source.py`:
```python
from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator

from app.config import Config

FLEX_DECODER = "n=fan,m=OOK_PWM,s=744,l=376,r=900,g=900,t=150,y=0"


def build_source_args(config: Config) -> list[str]:
    """The only thing that differs between local-USB and remote-rtl_tcp
    modes; everything else about the rtl_433 invocation is identical."""
    args: list[str] = []
    if config.rtl433_source == "rtl_tcp":
        args += ["-d", f"rtl_tcp:{config.rtl433_source_host}:{config.rtl433_source_port}"]
    args += [
        "-f", str(config.rtl433_frequency),
        "-s", str(config.rtl433_sample_rate),
        "-g", str(config.rtl433_gain),
    ]
    return args


def rtl433_command(config: Config) -> list[str]:
    return ["rtl_433", *build_source_args(config), "-R", "0", "-X", FLEX_DECODER]


class RFSourceManager:
    """Spawns rtl_433 (or, in tests, a fake stand-in command) and yields its
    stdout lines, restarting with a fixed backoff if the process exits
    unexpectedly (SDR unplugged, rtl_tcp connection dropped, etc.)."""

    def __init__(
        self,
        config: Config,
        restart_backoff_seconds: float = 5.0,
        command: list[str] | None = None,
    ):
        self._restart_backoff_seconds = restart_backoff_seconds
        self._command = command or rtl433_command(config)
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def lines(self) -> Iterator[str]:
        while not self._stopped:
            proc = subprocess.Popen(
                self._command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    yield line.rstrip()
                    if self._stopped:
                        proc.terminate()
                        return
            finally:
                proc.wait()
            if self._stopped:
                return
            print(
                f"rtl_433 exited (code={proc.returncode}), restarting in "
                f"{self._restart_backoff_seconds}s",
                flush=True,
            )
            time.sleep(self._restart_backoff_seconds)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_rf_source.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/rf_source.py tests/test_rf_source.py
git commit -m "Add RF source manager for bond-rtl433-rf-sync"
```

---

### Task 9: Main orchestration — wire everything together

**Files:**
- Modify: `bond-rtl433-rf-sync/app/main.py`
- Test: `bond-rtl433-rf-sync/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Config`/`load_config` (Task 2), `MatchedEvent`/`match_line` (Task 3),
  `Debouncer` (Task 4), `LastSpeedStore` (Task 5), `BondClient`/`build_*_body`
  (Task 6), `EventLog` (Task 7), `RFSourceManager` (Task 8).
- Produces: `class Pipeline` with `__init__(self, config, bond_client, last_speed_store, event_log)`,
  `handle_event(self, event: MatchedEvent) -> None`. `run(config: Config) -> None`.
  `main() -> int`. Task 10 (Ingress panel) shares the same `EventLog` instance
  `run()` constructs. Task 11 wires `run()` into `run.sh`.

**This is where the Global Constraint about never calling a real Bond action
is enforced end to end** — `Pipeline.handle_event` only ever calls
`self._bond.get_state` (read) and `self._bond.patch_state` (belief-only
write), matching `BondClient`'s restricted surface from Task 6.

- [ ] **Step 1: Write the failing tests**

`tests/test_pipeline.py`:
```python
import requests

from app.bond_client import BondClient
from app.config import parse_config
from app.event_log import EventLog
from app.last_speed_store import LastSpeedStore
from app.matcher import MatchedEvent
from app.main import Pipeline


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, get_response=None, raise_on_patch=False):
        self.get_response = get_response or FakeResponse()
        self.raise_on_patch = raise_on_patch
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, headers, None))
        return self.get_response

    def patch(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("PATCH", url, headers, json))
        if self.raise_on_patch:
            raise requests.ConnectionError("bond unreachable")
        return FakeResponse(json_data=json)


def _config(dry_run=False):
    raw = {
        "bond_host": "192.168.0.110",
        "bond_token": "tok123",
        "rtl433_source": "local",
        "dry_run": dry_run,
        "code_table": [
            {"room": "livingroom", "button": "speed", "stable_id": "1ff"},
            {"room": "livingroom", "button": "power", "stable_id": "1d9"},
            {"room": "livingroom", "button": "light", "stable_id": "1f9"},
        ],
        "room_devices": [
            {"room": "livingroom", "bond_device_id": "ce4d90389da6937f", "max_speed": 3}
        ],
    }
    return parse_config(raw)


def _pipeline(tmp_path, session, dry_run=False):
    config = _config(dry_run=dry_run)
    bond_client = BondClient(config.bond_host, config.bond_token, session=session)
    last_speed_store = LastSpeedStore(tmp_path / "last_speed.json")
    event_log = EventLog()
    return Pipeline(config, bond_client, last_speed_store, event_log), event_log, last_speed_store


def test_speed_event_patches_and_updates_last_speed(tmp_path):
    session = FakeSession()
    pipeline, event_log, last_speed = _pipeline(tmp_path, session)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="speed", percentage=66))
    method, url, headers, body = session.calls[-1]
    assert method == "PATCH"
    assert body == {"power": 1, "speed": 2}
    assert last_speed.get("livingroom") == 66
    assert event_log.recent_events()[0].result == "ok"


def test_speed_event_zero_does_not_update_last_speed(tmp_path):
    session = FakeSession()
    pipeline, event_log, last_speed = _pipeline(tmp_path, session)
    last_speed.set("livingroom", 66)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="speed", percentage=0))
    assert session.calls[-1][3] == {"power": 0}
    assert last_speed.get("livingroom") == 66  # unchanged


def test_power_event_currently_on_turns_off(tmp_path):
    session = FakeSession(get_response=FakeResponse(json_data={"power": 1, "speed": 3, "light": 0}))
    pipeline, event_log, _ = _pipeline(tmp_path, session)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="power", percentage=None))
    assert session.calls[0][0] == "GET"
    assert session.calls[-1] == (
        "PATCH",
        "http://192.168.0.110/v2/devices/ce4d90389da6937f/state",
        {"BOND-Token": "tok123", "Content-Type": "application/json"},
        {"power": 0},
    )


def test_power_event_currently_off_resumes_last_speed(tmp_path):
    session = FakeSession(get_response=FakeResponse(json_data={"power": 0, "speed": 1, "light": 0}))
    pipeline, event_log, last_speed = _pipeline(tmp_path, session)
    last_speed.set("livingroom", 66)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="power", percentage=None))
    assert session.calls[-1][3] == {"power": 1, "speed": 2}


def test_light_event_toggles_from_current_state(tmp_path):
    session = FakeSession(get_response=FakeResponse(json_data={"power": 1, "speed": 2, "light": 1}))
    pipeline, event_log, _ = _pipeline(tmp_path, session)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="light", percentage=None))
    assert session.calls[-1][3] == {"light": 0}


def test_dry_run_never_calls_patch(tmp_path):
    session = FakeSession()
    pipeline, event_log, _ = _pipeline(tmp_path, session, dry_run=True)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="speed", percentage=66))
    assert all(call[0] != "PATCH" for call in session.calls)
    assert event_log.recent_events()[0].result == "dry_run"
    assert event_log.recent_events()[0].body == {"power": 1, "speed": 2}


def test_bond_patch_failure_is_logged_not_raised(tmp_path):
    session = FakeSession(raise_on_patch=True)
    pipeline, event_log, _ = _pipeline(tmp_path, session)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="speed", percentage=66))
    assert event_log.recent_events()[0].result.startswith("error:")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd bond-rtl433-rf-sync
python -m pytest tests/test_pipeline.py -v
```
Expected: FAIL with `ImportError: cannot import name 'Pipeline' from 'app.main'`.

- [ ] **Step 3: Write the implementation**

`app/main.py` (replaces Task 1's minimal version):
```python
from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.bond_client import (
    BondClient,
    build_light_toggle_body,
    build_power_toggle_body,
    build_speed_event_body,
)
from app.config import Config, load_config
from app.debouncer import Debouncer
from app.event_log import EventLog
from app.last_speed_store import LastSpeedStore
from app.matcher import MatchedEvent, match_line
from app.rf_source import RFSourceManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("bond-rtl433-rf-sync")

OPTIONS_PATH = Path("/data/options.json")
LAST_SPEED_PATH = Path("/data/last_speed.json")


class Pipeline:
    """Turns a debounced MatchedEvent into a belief-only Bond correction.
    Never calls anything but BondClient.get_state/patch_state - see the
    Global Constraints in this plan for why that matters."""

    def __init__(
        self,
        config: Config,
        bond_client: BondClient,
        last_speed_store: LastSpeedStore,
        event_log: EventLog,
    ):
        self._config = config
        self._bond = bond_client
        self._last_speed = last_speed_store
        self._event_log = event_log

    def handle_event(self, event: MatchedEvent) -> None:
        device = self._config.device_for_room(event.room)
        try:
            if event.button == "speed":
                assert event.percentage is not None
                body = build_speed_event_body(event, device)
                if event.percentage:
                    self._last_speed.set(event.room, event.percentage)
            elif event.button == "power":
                state = self._bond.get_state(device.bond_device_id)
                body = build_power_toggle_body(
                    currently_on=bool(state.get("power")),
                    last_speed_percentage=self._last_speed.get(event.room),
                    device=device,
                )
            elif event.button == "light":
                state = self._bond.get_state(device.bond_device_id)
                body = build_light_toggle_body(currently_on=bool(state.get("light")))
            else:
                log.warning("unknown button type %r for room %r", event.button, event.room)
                return
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline on one bad event
            log.error("failed to build Bond call for %s/%s: %s", event.room, event.button, exc)
            self._event_log.record(event.room, event.button, event.percentage, {}, f"error: {exc}")
            return

        if self._config.dry_run:
            log.info("[dry-run] would PATCH %s with %s", device.bond_device_id, body)
            self._event_log.record(event.room, event.button, event.percentage, body, "dry_run")
            return

        try:
            self._bond.patch_state(device.bond_device_id, body)
            log.info("corrected %s/%s -> %s", event.room, event.button, body)
            self._event_log.record(event.room, event.button, event.percentage, body, "ok")
        except Exception as exc:  # noqa: BLE001 - log and move on, self-heals on next event
            log.error("Bond PATCH failed for %s/%s: %s", event.room, event.button, exc)
            self._event_log.record(event.room, event.button, event.percentage, body, f"error: {exc}")


def run(config: Config) -> None:
    bond_client = BondClient(config.bond_host, config.bond_token)
    last_speed_store = LastSpeedStore(LAST_SPEED_PATH)
    event_log = EventLog()
    pipeline = Pipeline(config, bond_client, last_speed_store, event_log)
    debouncer = Debouncer(config.debounce_seconds, pipeline.handle_event)
    rf_source = RFSourceManager(config)

    log.info(
        "bond-rtl433-rf-sync starting (source=%s, dry_run=%s)",
        config.rtl433_source,
        config.dry_run,
    )
    for line in rf_source.lines():
        event = match_line(line, config.code_table)
        if event is None:
            continue
        log.info("seen %s/%s percentage=%s", event.room, event.button, event.percentage)
        debouncer.see(event)


def main() -> int:
    config = load_config(OPTIONS_PATH)
    run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_pipeline.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Run the full test suite so far**

```bash
python -m pytest -v
```
Expected: all tests across every module pass (config, matcher, debouncer,
last_speed_store, bond_client, event_log, rf_source, pipeline).

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_pipeline.py
git commit -m "Wire pipeline orchestration for bond-rtl433-rf-sync"
```

---

### Task 10: Ingress panel — read-only event history and state

**Files:**
- Create: `bond-rtl433-rf-sync/app/web.py`
- Create: `bond-rtl433-rf-sync/app/templates/index.html`
- Test: `bond-rtl433-rf-sync/tests/test_web.py`

**Interfaces:**
- Consumes: `EventLog` from `app/event_log.py` (Task 7).
- Produces: `create_app(event_log: EventLog) -> Flask`. Task 11 (Main) calls
  `create_app(event_log)` and serves it alongside the pipeline thread.

- [ ] **Step 1: Write the failing tests**

`tests/test_web.py`:
```python
from app.event_log import EventLog
from app.web import create_app


def test_index_returns_200():
    app = create_app(EventLog())
    resp = app.test_client().get("/")
    assert resp.status_code == 200


def test_index_shows_recorded_event():
    event_log = EventLog()
    event_log.record("livingroom", "speed", 66, {"power": 1, "speed": 2}, "ok")
    app = create_app(event_log)
    body = app.test_client().get("/").get_data(as_text=True)
    assert "livingroom" in body
    assert "speed" in body


def test_index_shows_current_state():
    event_log = EventLog()
    event_log.record("bedroom", "power", None, {"power": 1}, "ok")
    app = create_app(event_log)
    body = app.test_client().get("/").get_data(as_text=True)
    assert "bedroom" in body


def test_healthz_returns_ok():
    app = create_app(EventLog())
    resp = app.test_client().get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd bond-rtl433-rf-sync
python -m pytest tests/test_web.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.web'`.

- [ ] **Step 3: Write the implementation**

`app/web.py`:
```python
from __future__ import annotations

from flask import Flask, render_template

from app.event_log import EventLog


def create_app(event_log: EventLog) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            events=event_log.recent_events(),
            state=event_log.current_state(),
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
```

`app/templates/index.html`:
```html
<!doctype html>
<html>
<head>
  <title>Bond-rtl_433 RF Sync</title>
  <meta http-equiv="refresh" content="5">
  <style>
    body { font-family: sans-serif; margin: 1.5rem; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 2rem; }
    th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }
    th { background: #f0f0f0; }
    .ok { color: #1a7f37; }
    .dry_run { color: #9a6700; }
    .error { color: #cf222e; }
  </style>
</head>
<body>
  <h1>Bond-rtl_433 RF Sync</h1>

  <h2>Current believed state</h2>
  <table>
    <tr><th>Room</th><th>State</th></tr>
    {% for room, s in state.items() %}
    <tr><td>{{ room }}</td><td>{{ s }}</td></tr>
    {% endfor %}
  </table>

  <h2>Recent events</h2>
  <table>
    <tr><th>Time</th><th>Room</th><th>Button</th><th>Percentage</th><th>Body</th><th>Result</th></tr>
    {% for e in events %}
    <tr>
      <td>{{ e.timestamp }}</td>
      <td>{{ e.room }}</td>
      <td>{{ e.button }}</td>
      <td>{{ e.percentage }}</td>
      <td>{{ e.body }}</td>
      <td class="{{ e.result.split(':')[0] }}">{{ e.result }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_web.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/web.py app/templates/index.html tests/test_web.py
git commit -m "Add read-only ingress panel for bond-rtl433-rf-sync"
```

---

### Task 11: Wire pipeline thread + web server together in main()

**Files:**
- Modify: `bond-rtl433-rf-sync/app/main.py`
- Test: `bond-rtl433-rf-sync/tests/test_main.py`

**Interfaces:**
- Consumes: `create_app` from `app/web.py` (Task 10), everything `main.py`
  already imports from Tasks 2–9.
- Produces: `run_pipeline(config: Config, rf_source: RFSourceManager, debouncer: Debouncer) -> None`
  (replaces Task 9's `run()` — same loop body, extracted so `main()` can run
  it in a background thread alongside the web server). `main()`'s behavior
  changes: starts the pipeline in a daemon thread, then serves the ingress
  panel in the foreground (keeps the container's PID 1 as the web server,
  simplest possible process model — no s6-overlay needed for one add-on).

- [ ] **Step 1: Write the failing test**

`tests/test_main.py`:
```python
import threading
import time

from app.config import parse_config
from app.debouncer import Debouncer
from app.matcher import MatchedEvent
from app.main import run_pipeline
from app.rf_source import RFSourceManager


def _config():
    raw = {
        "bond_host": "192.168.0.110",
        "bond_token": "tok",
        "rtl433_source": "local",
        "debounce_seconds": 0.05,
        "code_table": [{"room": "livingroom", "button": "power", "stable_id": "1d9"}],
        "room_devices": [
            {"room": "livingroom", "bond_device_id": "ce4d90389da6937f", "max_speed": 3}
        ],
    }
    return parse_config(raw)


def test_run_pipeline_feeds_matched_lines_into_debouncer():
    config = _config()
    seen = []
    debouncer = Debouncer(config.debounce_seconds, seen.append)
    rf_source = RFSourceManager(
        config,
        command=["python3", "-c", "print('codes     : {25}3b20')"],
        restart_backoff_seconds=0.05,
    )

    def stop_soon():
        time.sleep(0.3)
        rf_source.stop()

    threading.Thread(target=stop_soon, daemon=True).start()
    run_pipeline(config, rf_source, debouncer)
    debouncer.join_pending(timeout=1)

    assert seen == [MatchedEvent(room="livingroom", button="power", percentage=None)]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd bond-rtl433-rf-sync
python -m pytest tests/test_main.py -v
```
Expected: FAIL with `ImportError: cannot import name 'run_pipeline' from 'app.main'`.

- [ ] **Step 3: Modify app/main.py**

Replace the existing `run(config: Config) -> None` and `main() -> int`
functions at the bottom of `app/main.py` with:

```python
import threading

from app.web import create_app


def run_pipeline(config: Config, rf_source: RFSourceManager, debouncer: Debouncer) -> None:
    log.info(
        "bond-rtl433-rf-sync pipeline starting (source=%s, dry_run=%s)",
        config.rtl433_source,
        config.dry_run,
    )
    for line in rf_source.lines():
        event = match_line(line, config.code_table)
        if event is None:
            continue
        log.info("seen %s/%s percentage=%s", event.room, event.button, event.percentage)
        debouncer.see(event)


def main() -> int:
    config = load_config(OPTIONS_PATH)
    bond_client = BondClient(config.bond_host, config.bond_token)
    last_speed_store = LastSpeedStore(LAST_SPEED_PATH)
    event_log = EventLog()
    pipeline = Pipeline(config, bond_client, last_speed_store, event_log)
    debouncer = Debouncer(config.debounce_seconds, pipeline.handle_event)
    rf_source = RFSourceManager(config)

    pipeline_thread = threading.Thread(
        target=run_pipeline, args=(config, rf_source, debouncer), daemon=True
    )
    pipeline_thread.start()

    app = create_app(event_log)
    app.run(host="0.0.0.0", port=8100)
    return 0
```

(Add the `import threading` and `from app.web import create_app` lines near
the top of the file with the other imports.)

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_main.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest -v
```
Expected: all tests pass across every module.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "Wire pipeline thread and ingress web server together"
```

---

### Task 12: Deploy to Home Assistant Supervisor, confirm it boots

**Files:** none — manual deployment and verification.

**Interfaces:**
- Consumes: everything built in Tasks 1–11.
- Produces: a running, installed add-on instance to build the remaining
  tasks' live testing on.

At this point the add-on has no real RF source available yet (no dongle is
attached to the HA host, and the Pi's dongle is still exclusively held by
`rtl433-mqtt.service`, per the Global Constraints) — this task only confirms
the container, config, and ingress panel work end to end. Periodic
"rtl_433 exited, restarting" log lines during this task are **expected**,
not a bug — real RF source validation is Task 13.

**Completed 2026-08-16. Found and fixed a real deployment bug this task
exists to catch:** the built Docker image flattened `app/`'s contents
directly into `/app/`, but the codebase's absolute imports
(`from app.bond_client import ...`) require `app` to be an importable
package — `ModuleNotFoundError: No module named 'app'` on every boot.
None of the 60 unit tests exercise the actual built container's import
resolution (they run via local `pytest` with `pythonpath = .`), so this
was invisible until real deployment. Fixed by copying `app/` to `/app/app/`
and running via `python3 -m app.main` instead of `python3 /app/main.py`
(commit `febee09`), verified locally with a real `docker build`+`docker run`
before pushing. **Operational gotcha also discovered:** Supervisor compares
`config.yaml`'s `version:` field to decide whether to re-fetch/rebuild from
git — a fix commit alone doesn't trigger a rebuild without a version bump
(bumped to 0.2.1, commit `f9fe5b3`), and `ha store reload` (not
`ha store update`) is the correct command to refresh a custom repo's
metadata before Supervisor will see a new version at all. After the fix:
add-on boots clean, `/healthz` returns 200, ingress panel renders
correctly, `rtl_433` retries gracefully with backoff when no source is
available (exactly the expected degraded state for this task).

**Scope note:** Tasks 13–15 all validate the `rtl_tcp` (remote Pi) path,
matching your actual setup — `usb: true`/local-USB mode is code-complete
and unit-testable (Task 8's `build_source_args` tests cover its argument
construction) but **not live-validated against a real directly-attached
dongle** in this plan, since there isn't a spare one to attach to this HA
host. Worth a real test before this add-on goes into the public repo for
others whose primary use case is local-only.

- [x] **Step 1: Push all work so far**

```bash
cd /home/mark/projects/tuttleHAaddons
git push
```

- [x] **Step 2: Confirm the repository is visible to Supervisor and install the add-on**

In Home Assistant: Settings → Add-ons → Add-on Store → ⋮ (top right) →
Check for updates (the `tuttleHAaddons` repository is already added, since
`markdown-wiki` is installed from it). Find "Bond-rtl_433 RF Sync" in the
store, click it, click **Install**. Expected: install completes without
error (the Docker build succeeds, including the `apt-get install rtl-433`
step).

- [x] **Step 3: Configure minimally and start it**

On the add-on's **Configuration** tab, set:
- `bond_host`: `192.168.0.110`
- `bond_token`: (the value from 1Password `op://CLI/bond-bridge-local/credential` — fetch it yourself via `op read`, paste it in, don't leave it in shell history)
- `dry_run`: `true`

Leave `rtl433_source`, `code_table`, and `room_devices` at their defaults.
Save, then start the add-on.

- [x] **Step 4: Check the Log tab**

Expected: a line like
`bond-rtl433-rf-sync pipeline starting (source=local, dry_run=True)`,
followed by periodic `rtl_433 exited (code=...), restarting in 5.0s` lines
(expected, no dongle attached here yet).

- [x] **Step 5: Check the ingress panel**

Settings → Add-ons → Bond-rtl_433 RF Sync → **Open Web UI**. Expected: the
page loads, shows "Current believed state" and "Recent events" headers,
both empty (no real event has fired yet).

- [x] **Step 6: Stop the add-on**

It doesn't need to keep running yet — real RF testing happens in Task 13,
which needs the Pi's dongle temporarily freed up first. Stop it from the
add-on's page (or leave it running with `dry_run: true` if you prefer — it's
harmless either way since dry-run never calls Bond).

---

### Task 13: Dry-run validation against real hardware

**Files:** none — live RF testing, no code changes.

**Interfaces:**
- Consumes: the deployed add-on from Task 12.
- Produces: confirmed decode/match accuracy for all 9 button combinations,
  with zero Bond calls made (dry-run throughout).

**Get explicit user confirmation before Step 1** — this task temporarily
stops the Pi's safety-net service.

- [x] **Step 1: Stop the Pi's fan bridge and start a temporary rtl_tcp**

```bash
ssh raspberrypi 'sudo systemctl stop rtl433-mqtt.service'
ssh raspberrypi 'sudo systemd-run --unit=temp-rtl-tcp --collect rtl_tcp -a 0.0.0.0 -p 1234'
ssh raspberrypi 'systemctl is-active temp-rtl-tcp'
```
Expected: `active`.

- [x] **Step 2: Point the add-on at it**

On the add-on's Configuration tab: `rtl433_source: rtl_tcp`,
`rtl433_source_host: <the Pi's IP>`, `rtl433_source_port: 1234`,
`dry_run: true` (unchanged). Save, start the add-on.

- [x] **Step 3: Confirm connection in the Log tab**

Expected: `bond-rtl433-rf-sync pipeline starting (source=rtl_tcp, ...)`
with no further `restarting` errors — the add-on is now successfully
reading from the Pi's dongle over the network.

- [x] **Step 4: One button at a time, all 9 combinations**

For each of {livingroom, diningroom, bedroom} × {power, light, speed}:
press the real physical wall-switch button once, then check the Log tab
for a `seen ...` line followed by
`[dry-run] would PATCH <device_id> with <body>`. Confirm the logged body
matches what's expected for that button (e.g. bedroom speed landing on
66% → `{"power": 1, "speed": 2}`; a power/light press → a toggle body
consistent with the room's actual current physical state). Also confirm
the ingress panel's "Recent events" table shows the same entries.

- [x] **Step 5: Restore the Pi's safety net**

```bash
ssh raspberrypi 'sudo systemctl stop temp-rtl-tcp'
ssh raspberrypi 'sudo systemctl start rtl433-mqtt.service'
ssh raspberrypi 'systemctl is-active rtl433-mqtt.service'
```
Expected: `active`. Stop the add-on (or leave `dry_run: true` running,
harmless either way) until Task 14.

**Completed 2026-08-16.** All 9 button combinations (3 rooms × power/light/
speed) decoded correctly and produced the expected `[dry-run] would PATCH`
body, each cross-checked against Bond's real current belief via a live
`GET .../state` at the time of the press — every toggle direction and every
speed-to-native-step conversion matched. Zero mismatches, zero decode
errors. Confirmed via the `received signal 15, shutting down` log line
during an unrelated restart that the final-review SIGTERM fix also works
correctly in production, not just in its unit test. Pi's safety net
restored cleanly afterward; add-on left in a harmless degraded-retry state
(its `rtl433_source` still points at the Pi's now-stopped temporary
`rtl_tcp`) until Task 14 resumes.

---

### Task 14: Live validation, one room at a time

**Files:** none — live testing, no code changes.

**Interfaces:**
- Consumes: the add-on validated dry-run-clean in Task 13.
- Produces: confirmed live Bond corrections for all 9 combinations, with
  the old HA-automation system still running in parallel throughout (per
  Global Constraints — not retired until Task 15).

**Get explicit user confirmation before Step 1.**

- [ ] **Step 1: Repeat Task 13's dongle-borrowing setup**

```bash
ssh raspberrypi 'sudo systemctl stop rtl433-mqtt.service'
ssh raspberrypi 'sudo systemd-run --unit=temp-rtl-tcp --collect rtl_tcp -a 0.0.0.0 -p 1234'
```

- [ ] **Step 2: Flip dry_run off**

On the add-on's Configuration tab, set `dry_run: false`. Save, start (or
restart) the add-on.

- [ ] **Step 3: One button at a time, all 9 combinations, with the user watching the physical device**

Same procedure as Task 13 Step 4, but this time each event makes a real
`PATCH` call. For each button: press it, confirm in the Log tab that
exactly one `corrected <room>/<button> -> <body>` line appears (not
`error:`), confirm via the ingress panel or
`mcp__bond__get_device_state`/a raw `GET .../state` call that Bond's belief
now matches physical reality, and **confirm the physical device did not
additionally respond** (no double RF) — the same verification the original
HA-automation system was validated with earlier today.

- [ ] **Step 4: Restore the Pi's safety net**

```bash
ssh raspberrypi 'sudo systemctl stop temp-rtl-tcp'
ssh raspberrypi 'sudo systemctl start rtl433-mqtt.service'
```

Do not proceed to Task 15 until all 9 combinations are confirmed clean.

---

### Task 15: Cutover — retire the old pipeline

**Files:**
- Modify (HA host): `/config/automations.yaml` — disable (don't delete)
  automations `1786000000001`–`009` via the UI toggle, not an `enabled:`
  YAML key (that key was confirmed broken on this HA version 2026-08-15 —
  see `rtl_433_fan/FAN_WALLSWITCH_SYNC.md`).
- Modify (Pi): `/etc/systemd/system/rtl-tcp.service` — bind address.
- Modify (Pi): disable `rtl433-mqtt.service`.
- Modify: `rtl_433_fan/FAN_WALLSWITCH_SYNC.md` — document the cutover.

**Interfaces:**
- Consumes: Task 14's live-validated add-on.
- Produces: the add-on as the sole path correcting Bond's belief; the old
  MQTT/automation/rest_command pipeline fully retired (not deleted from
  history — still visible in git/HA's config auto-commit).

**Get explicit user confirmation before every step below — this is the
most consequential task in the plan.**

- [ ] **Step 1: Disable the 9 old HA automations via the UI**

Settings → Automations & Scenes → for each of the 9 "Fan wall switch -
livingroom/diningroom/bedroom power+light/light/speed" automations, use the
toggle to disable it (not delete — keeps history, easy to re-enable if
needed).

- [ ] **Step 2: Point rtl-tcp.service at all interfaces and make it the permanent source**

```bash
ssh raspberrypi 'sudo sed -i "s/-a 127.0.0.1/-a 0.0.0.0/" /etc/systemd/system/rtl-tcp.service'
ssh raspberrypi 'sudo systemctl daemon-reload'
ssh raspberrypi 'sudo systemctl disable --now rtl433-mqtt.service'
ssh raspberrypi 'sudo systemctl enable --now rtl-tcp.service'
ssh raspberrypi 'systemctl is-active rtl-tcp.service'
```
Expected: `active`. Note per the Global Constraints: this and the
gas-meter's `rtlamr-mqtt.service` still can't both be actively connected to
it at once — that's an unchanged pre-existing limitation, not something
this step fixes.

- [ ] **Step 3: Point the add-on at the now-permanent source and confirm it boots clean**

On the add-on's Configuration tab: `rtl433_source_host` set to the Pi's IP,
`dry_run: false`. Set `boot: auto` behavior is already the add-on's default
from `config.yaml` (Task 1) — confirm in the add-on's Info tab that
"Start on boot" is enabled. Restart the add-on, confirm the Log tab shows a
clean startup with no `restarting` errors.

- [ ] **Step 4: One more live press per room, confirm the add-on (now the only active corrector) still works end to end**

Press one button in each room, confirm `corrected <room>/<button> -> ...`
in the log and a matching physical/believed-state check, same as Task 14.

- [ ] **Step 5: Update FAN_WALLSWITCH_SYNC.md with the cutover**

Add a dated entry to `rtl_433_fan/FAN_WALLSWITCH_SYNC.md` documenting: the
9 HA automations are now disabled (not deleted), `fan_wallswitch_bridge.py`
and `rtl433-mqtt.service` are retired in favor of the `bond-rtl433-rf-sync`
add-on, the Pi's role is now just `rtl-tcp.service` bound to `0.0.0.0`, and
a pointer to this add-on's repo/spec/plan for anyone picking this up later.
Commit and push from `/home/mark/projects/rtl_433_fan`.

```bash
cd /home/mark/projects/rtl_433_fan
git add FAN_WALLSWITCH_SYNC.md
git commit -m "Document cutover to bond-rtl433-rf-sync add-on"
git push
```

- [ ] **Step 6: Bump the add-on's version and tag the tuttleHAaddons repo**

```bash
cd /home/mark/projects/tuttleHAaddons
# bump version: "0.1.0" -> "1.0.0" in bond-rtl433-rf-sync/config.yaml and CHANGELOG.md
git add bond-rtl433-rf-sync/config.yaml bond-rtl433-rf-sync/CHANGELOG.md
git commit -m "bond-rtl433-rf-sync 1.0.0: live-validated, cut over from HA automations"
git tag -a "bond-rtl433-rf-sync-1.0.0" -m "First live-validated release, replaces the rtl_433_fan HA-automation pipeline"
git push && git push --tags
```
