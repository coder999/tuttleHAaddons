"""ProForm/iFit bike over HA Bluetooth: live sensors; rides saved as TCX and uploaded to Strava."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from pathlib import Path

import probatio as vol  # HA 2026.11 replaced voluptuous with probatio (same API)
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth, persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.config_entry_oauth2_flow import (
    OAuth2Session,
    async_get_config_entry_implementation,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from . import protocol
from .const import DEFAULT_WHEEL_RATIO, DOMAIN, WHEEL_RATIO
from .strava import Strava

_LOGGER = logging.getLogger(__name__)
SIGNAL = f"{DOMAIN}_update"
PLATFORMS = ["sensor", "switch"]
RIDE_END_IDLE = 120  # s with no pedaling ends a ride
MIN_RIDE = 60  # s; shorter rides are dropped
RETRY_AFTER_FAIL = 60  # s

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


class Bike:
    def __init__(self, hass: HomeAssistant, address: str, wheel_ratio: float) -> None:
        self.hass = hass
        self.address = address.upper()
        self.wheel_ratio = wheel_ratio
        self.strava: Strava | None = None
        self.rides_dir = Path(hass.config.path("ifit_rides"))
        self.enabled = True  # the switch entity restores the real value at startup
        self.status = "disconnected"
        self.data: dict = {"power": None, "cadence": None, "speed": None, "resistance": None}
        self.ride: list[tuple[float, int, int, float]] = []
        self.ride_distance = 0.0  # m
        self.last_pedal = 0.0
        self._task: asyncio.Task | None = None
        self._next_try = 0.0

    @property
    def ride_time(self) -> int:
        return int(self.ride[-1][0] - self.ride[0][0]) if self.ride else 0

    def _push(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL)

    @callback
    def maybe_connect(self, _now=None) -> None:
        # Timer, not an advertisement callback: HA doesn't re-fire callbacks for unchanged
        # adverts, so a callback alone would never retry after a dropped session.
        if not self.enabled or self._task or time.monotonic() < self._next_try:
            return
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if device:
            self._task = self.hass.async_create_background_task(self._session(device), DOMAIN)

    async def _session(self, device) -> None:
        self.status = "connecting"
        self._push()
        try:
            client = await establish_connection(BleakClientWithServiceCache, device, DOMAIN)
            try:
                await client.start_notify(protocol.NOTIFY_UUID, self._on_frame)
                for frame in protocol.INIT:
                    await client.write_gatt_char(protocol.WRITE_UUID, frame, response=True)
                    await asyncio.sleep(0.4)
                self.status = "connected"
                self._push()
                tick = 0
                next_second = time.monotonic()
                while self.enabled and client.is_connected:
                    # Clock-based, not tick-counted: each acked write takes ~150 ms at the
                    # bike's -88 dBm, which stretched a 5-tick "second" to ~1.75 s.
                    started = time.monotonic()
                    await client.write_gatt_char(
                        protocol.WRITE_UUID, protocol.POLL[tick % len(protocol.POLL)], response=True
                    )
                    tick += 1
                    if started >= next_second:
                        next_second += 1
                        if next_second <= started:  # fell behind (stall): resync, no burst
                            next_second = started + 1
                        self._second()
                    await asyncio.sleep(max(0.0, 0.2 - (time.monotonic() - started)))
            finally:
                await client.disconnect()
        except Exception as err:  # noqa: BLE001 - BLE drops are routine; the timer retries
            _LOGGER.info("Bike session ended: %r", err)
            self._next_try = time.monotonic() + RETRY_AFTER_FAIL
        finally:
            self._task = None
            self.data = dict.fromkeys(self.data)
            self.status = "disconnected"
            self._end_ride()
            self._push()

    def _on_frame(self, _char, frame: bytearray) -> None:
        _LOGGER.debug("<< %s", frame.hex(" "))
        if (parsed := protocol.parse(bytes(frame), self.wheel_ratio)) is not None:
            self.data.update(parsed)

    def _second(self) -> None:
        """1 Hz: sample the ride, end it after RIDE_END_IDLE idle, refresh the sensors."""
        now = time.time()
        cadence = self.data["cadence"] or 0
        if cadence > 0:
            self.last_pedal = now
        if self.ride and now - self.last_pedal > RIDE_END_IDLE:
            self._end_ride()
        elif self.ride or cadence > 0:
            speed = self.data["speed"] or 0.0
            if self.ride:
                self.ride_distance += speed / 3.6 * (now - self.ride[-1][0])
            self.ride.append((now, self.data["power"] or 0, cadence, speed))
        self.status = "riding" if self.ride else "connected"
        self._push()

    def _end_ride(self) -> None:
        ride = [s for s in self.ride if s[0] <= self.last_pedal]  # drop the idle tail
        self.ride, self.ride_distance = [], 0.0
        if len(ride) >= MIN_RIDE:
            self.hass.async_create_task(self._save_and_upload(ride))

    async def _save_and_upload(self, ride: list) -> None:
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime(ride[0][0])) + ".tcx"
        tcx = protocol.tcx(ride)
        await self.hass.async_add_executor_job(self._write, name, tcx)
        _LOGGER.info("Saved ride %s (%d s)", name, ride[-1][0] - ride[0][0])
        await self.upload(name, tcx)

    def _write(self, name: str, tcx: str) -> None:
        self.rides_dir.mkdir(exist_ok=True)
        (self.rides_dir / name).write_text(tcx)

    async def upload(self, name: str, tcx: str) -> None:
        if not self.strava:
            return
        try:
            url = await self.strava.upload(name, tcx)
        except Exception as err:  # noqa: BLE001 - surface every failure; the TCX is kept
            self._notify(f"Strava upload of {name} failed: {err}\n\nIf Strava needs connecting "
                         "again: Settings > Devices & services > iFit Bike > Reconfigure. Then "
                         f"retry with the `ifit_bike.upload_ride` action (file: {name}).")
        else:
            _LOGGER.info("Uploaded %s: %s", name, url)

    def _notify(self, msg: str) -> None:
        persistent_notification.async_create(self.hass, msg, "Bike ride", f"{DOMAIN}_strava")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def upload_ride(call: ServiceCall) -> None:
        # ponytail: one bike per HA; pick the first loaded entry. Add a device field for more.
        bikes = [e.runtime_data for e in hass.config_entries.async_entries(DOMAIN)
                 if e.state is ConfigEntryState.LOADED]
        if not bikes or not bikes[0].strava:
            raise HomeAssistantError("No iFit bike with Strava connected")
        bike = bikes[0]
        path = bike.rides_dir / Path(call.data["file"]).name  # basename only: no path escapes
        await bike.upload(path.name, await hass.async_add_executor_job(path.read_text))

    hass.services.async_register(
        DOMAIN, "upload_ride", upload_ride, vol.Schema({vol.Required("file"): cv.string})
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    bike = entry.runtime_data = Bike(
        hass, entry.data[CONF_ADDRESS], entry.options.get(WHEEL_RATIO, DEFAULT_WHEEL_RATIO)
    )
    if "auth_implementation" in entry.data:
        try:
            impl = await async_get_config_entry_implementation(hass, entry)
        except ValueError:  # its Application Credentials were deleted
            bike._notify("Strava sign-in is missing. Add the Strava Application Credentials "
                         "again, then Settings > Devices & services > iFit Bike > Reconfigure.")
        else:
            bike.strava = Strava(hass, OAuth2Session(hass, entry, impl))

    async def options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
        # Applied live, not by reload: a reload mid-ride would end the ride.
        bike.wheel_ratio = entry.options.get(WHEEL_RATIO, DEFAULT_WHEEL_RATIO)

    entry.async_on_unload(entry.add_update_listener(options_updated))
    entry.async_on_unload(
        async_track_time_interval(hass, bike.maybe_connect, timedelta(seconds=10))
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    bike: Bike = entry.runtime_data
    if bike._task:
        bike._task.cancel()  # its finally block disconnects and saves any ride in progress
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
