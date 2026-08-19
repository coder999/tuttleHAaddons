import requests

from app.bond_client import BondClient
from app.config import CodeTableEntry, Config, parse_config
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


def test_power_event_currently_on_turns_off_light_too(tmp_path):
    # Regression test for real wall-switch behavior confirmed live
    # 2026-08-16: the power button is a master toggle for the whole
    # fixture, driven by the fan's own state - light unconditionally
    # follows the fan's *new* state, NOT light's own prior state. This
    # fixture is deliberately a mixed state (fan on, light off) - the
    # old (buggy) independent-toggle logic would have turned light ON
    # here (toggling from its own off state), not off.
    session = FakeSession(get_response=FakeResponse(json_data={"power": 1, "speed": 3, "light": 0}))
    pipeline, event_log, _ = _pipeline(tmp_path, session)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="power", percentage=None))
    assert session.calls[0][0] == "GET"
    assert session.calls[-1] == (
        "PATCH",
        "http://192.168.0.110/v2/devices/ce4d90389da6937f/state",
        {"BOND-Token": "tok123", "Content-Type": "application/json"},
        {"power": 0, "light": 0},
    )


def test_power_event_currently_off_resumes_last_speed_and_turns_light_on(tmp_path):
    # Regression test, other mixed state (fan off, light on): old
    # independent-toggle logic would have turned light OFF here
    # (toggling from its own on state), not left it on.
    session = FakeSession(get_response=FakeResponse(json_data={"power": 0, "speed": 1, "light": 1}))
    pipeline, event_log, last_speed = _pipeline(tmp_path, session)
    last_speed.set("livingroom", 66)
    pipeline.handle_event(MatchedEvent(room="livingroom", button="power", percentage=None))
    assert session.calls[-1][3] == {"power": 1, "speed": 2, "light": 1}


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


def test_unknown_room_device_lookup_failure_is_logged_not_raised(tmp_path):
    # Config-drift scenario: a code_table entry references a room with no
    # matching room_devices entry. parse_config() rejects this at load time,
    # but nothing stops it happening at runtime (e.g. options.json edited by
    # hand, or a future config loader that's more permissive) - construct a
    # Config directly, bypassing parse_config's validation, to reach the
    # device_for_room() lookup that runs inside handle_event().
    session = FakeSession()
    config = Config(
        bond_host="192.168.0.110",
        bond_token="tok123",
        rtl433_source="local",
        rtl433_source_host="",
        rtl433_source_port=1234,
        rtl433_frequency=304250000,
        rtl433_sample_rate=2048000,
        rtl433_gain=49.6,
        rtl433_stale_timeout_seconds=3600.0,
        rtl433_liveness_probe_interval_seconds=60.0,
        debounce_seconds=3.0,
        dry_run=False,
        code_table=(CodeTableEntry(room="diningroom", button="power", stable_id=0x1D9),),
        room_devices=(),  # no entry for "diningroom" - device_for_room() will raise
    )
    bond_client = BondClient(config.bond_host, config.bond_token, session=session)
    last_speed_store = LastSpeedStore(tmp_path / "last_speed.json")
    event_log = EventLog()
    pipeline = Pipeline(config, bond_client, last_speed_store, event_log)

    pipeline.handle_event(MatchedEvent(room="diningroom", button="power", percentage=None))

    assert event_log.recent_events()[0].result.startswith("error:")
    assert all(call[0] not in ("GET", "PATCH") for call in session.calls)
