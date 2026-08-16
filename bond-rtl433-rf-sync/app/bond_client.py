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
    """Body for a 'power' button event: toggles the fan off if currently
    on, otherwise turns it on to the last known non-zero speed. The light
    unconditionally follows the fan's *new* resulting state, not light's
    own prior state - confirmed live 2026-08-16 that the physical wall
    switch's power button is a master toggle for the whole fixture, driven
    entirely by the fan's own on/off memory: fan-on/light-off -> both off,
    fan-off/light-on -> both on. It is NOT two independent per-entity
    toggles (that was the bug: the original design toggled light based on
    light's own prior state, which is wrong for exactly these two mixed
    cases)."""
    if currently_on:
        return {"power": 0, "light": 0}
    return {
        "power": 1,
        "speed": native_speed_step(last_speed_percentage, device.max_speed),
        "light": 1,
    }


def build_light_toggle_body(currently_on: bool) -> dict:
    """Body for a 'light' button event: simple believed-state toggle."""
    return {"light": 0 if currently_on else 1}
