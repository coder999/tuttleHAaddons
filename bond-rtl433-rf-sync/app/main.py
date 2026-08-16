from __future__ import annotations

import logging
import signal
import sys
import threading
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
from app.web import create_app

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
        try:
            device = self._config.device_for_room(event.room)
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


def _install_shutdown_handler(rf_source: RFSourceManager) -> None:
    """Ensures rf_source.stop() (which terminates the rtl_433 child process)
    runs on SIGTERM (docker stop / Supervisor restart) or SIGINT (Ctrl-C
    during manual/local testing), so the SDR dongle isn't left held by an
    orphaned rtl_433 process across restarts."""

    def _handle_shutdown(signum, frame):
        log.info("received signal %s, shutting down", signum)
        rf_source.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)


def main() -> int:
    config = load_config(OPTIONS_PATH)
    bond_client = BondClient(config.bond_host, config.bond_token)
    last_speed_store = LastSpeedStore(LAST_SPEED_PATH)
    event_log = EventLog()
    pipeline = Pipeline(config, bond_client, last_speed_store, event_log)
    debouncer = Debouncer(config.debounce_seconds, pipeline.handle_event)
    rf_source = RFSourceManager(config)
    _install_shutdown_handler(rf_source)

    pipeline_thread = threading.Thread(
        target=run_pipeline, args=(config, rf_source, debouncer), daemon=True
    )
    pipeline_thread.start()

    app = create_app(event_log)
    app.run(host="0.0.0.0", port=8100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
