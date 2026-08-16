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
    # Real wall-switch behavior confirmed live 2026-08-16: the power button
    # is a master toggle for the whole fixture, driven by the fan's own
    # state - light unconditionally follows the fan's *new* state, not
    # light's own prior state (fan on/light off -> both off; fan off/light
    # on -> both on). See build_power_toggle_body's docstring.
    body = build_power_toggle_body(currently_on=True, last_speed_percentage=66, device=LIVINGROOM)
    assert body == {"power": 0, "light": 0}


def test_build_power_toggle_body_currently_off_resumes_last_speed():
    body = build_power_toggle_body(currently_on=False, last_speed_percentage=66, device=LIVINGROOM)
    assert body == {"power": 1, "speed": 2, "light": 1}


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
