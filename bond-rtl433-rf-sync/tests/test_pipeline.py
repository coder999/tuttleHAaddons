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
