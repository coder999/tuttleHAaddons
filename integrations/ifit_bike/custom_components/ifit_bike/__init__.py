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
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import discovery
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from . import protocol
from .strava import NotAuthorized, Strava

_LOGGER = logging.getLogger(__name__)
DOMAIN = "ifit_bike"
SIGNAL = f"{DOMAIN}_update"
RIDE_END_IDLE = 120  # s with no pedaling ends a ride
MIN_RIDE = 60  # s; shorter rides are dropped
RETRY_AFTER_FAIL = 60  # s

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_ADDRESS): cv.string,
                # km/h per rpm. Calibration knob: compare the console's speed and adjust.
                vol.Optional("wheel_ratio", default=0.33): vol.Coerce(float),
                vol.Inclusive("strava_client_id", "strava"): cv.string,
                vol.Inclusive("strava_client_secret", "strava"): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class Bike:
    def __init__(self, hass: HomeAssistant, conf: dict) -> None:
        self.hass = hass
        self.address = conf[CONF_ADDRESS].upper()
        self.wheel_ratio = conf["wheel_ratio"]
        self.strava = (
            Strava(hass, conf["strava_client_id"], conf["strava_client_secret"])
            if "strava_client_id" in conf
            else None
        )
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
        except NotAuthorized:
            self._notify(f"Ride {name} saved but not uploaded: Strava isn't authorized yet. "
                         f"[Authorize]({self.strava.authorize_url}), then run "
                         f"`ifit_bike.strava_authorize` with the code, then `ifit_bike.upload_ride`.")
        except Exception as err:  # noqa: BLE001 - surface every failure; the TCX is kept
            self._notify(f"Strava upload of {name} failed: {err}\n\n"
                         f"Retry with `ifit_bike.upload_ride` (file: {name}).")
        else:
            _LOGGER.info("Uploaded %s: %s", name, url)

    def _notify(self, msg: str) -> None:
        persistent_notification.async_create(self.hass, msg, "Bike ride", f"{DOMAIN}_strava")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    bike = hass.data[DOMAIN] = Bike(hass, config[DOMAIN])
    async_track_time_interval(hass, bike.maybe_connect, timedelta(seconds=10))
    for platform in ("sensor", "switch"):
        hass.async_create_task(discovery.async_load_platform(hass, platform, DOMAIN, {}, config))

    async def strava_authorize(call: ServiceCall) -> None:
        await bike.strava.exchange(call.data["code"].strip())
        persistent_notification.async_dismiss(hass, f"{DOMAIN}_strava")

    async def upload_ride(call: ServiceCall) -> None:
        path = bike.rides_dir / Path(call.data["file"]).name  # basename only: no path escapes
        await bike.upload(path.name, await hass.async_add_executor_job(path.read_text))

    if bike.strava:
        hass.services.async_register(
            DOMAIN, "strava_authorize", strava_authorize, vol.Schema({vol.Required("code"): cv.string})
        )
        hass.services.async_register(
            DOMAIN, "upload_ride", upload_ride, vol.Schema({vol.Required("file"): cv.string})
        )
        if not await bike.strava.authorized():
            bike._notify(f"[Authorize Strava]({bike.strava.authorize_url}). After approving, the "
                         "browser lands on a dead localhost page: copy the `code=` value from its "
                         "address bar and run the `ifit_bike.strava_authorize` action with it.")
    return True
