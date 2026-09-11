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
from app.bond_echo import BPUPListener, EchoTokenQueue
from app.config import Config, load_config
from app.debouncer import TOGGLE_BUTTONS, Debouncer
from app.event_log import EventLog
from app.last_speed_store import LastSpeedStore
from app.matcher import MatchedEvent, decode_only, match_line
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
        echo_tokens: EchoTokenQueue | None = None,
    ):
        self._config = config
        self._bond = bond_client
        self._last_speed = last_speed_store
        self._event_log = event_log
        # An empty queue never consumes, so omitting it disables echo
        # suppression rather than requiring every caller to build one.
        self._echo_tokens = echo_tokens or EchoTokenQueue(0.0)

    def handle_event(self, event: MatchedEvent) -> None:
        try:
            device = self._config.device_for_room(event.room)
            # Before correcting anything, ask whether this transmission was
            # ours. The Bond Bridge's own TX is byte-identical to a wall
            # switch press -- it IS the same code -- so the only way to tell
            # them apart is that the bridge told us in advance it was about
            # to transmit. Checked even under dry_run, so a dry run exercises
            # the real decision path rather than a different one.
            if self._echo_tokens.consume(device.bond_device_id, event.button):
                log.info("ignored %s/%s (bond self-TX echo)", event.room, event.button)
                self._event_log.record(
                    event.room, event.button, event.percentage, {}, "ignored (bond self-TX echo)"
                )
                return
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
            # An unmatched but well-formed transmission is how you discover
            # your own switches' stable_ids -- there is no other source for
            # them -- so it is logged rather than dropped silently.
            decoded = decode_only(line)
            if decoded is not None:
                log.info("unmatched RF press: stable_id=%s counter=%s "
                         "(add it to code_table to act on it)", *decoded)
            continue
        log.info("seen %s/%s percentage=%s", event.room, event.button, event.percentage)
        debouncer.see(event)


def _install_shutdown_handler(
    rf_source: RFSourceManager, bpup_listener: BPUPListener | None = None
) -> None:
    """Ensures rf_source.stop() (which terminates the rtl_433 child process)
    runs on SIGTERM (docker stop / Supervisor restart) or SIGINT (Ctrl-C
    during manual/local testing), so the SDR dongle isn't left held by an
    orphaned rtl_433 process across restarts."""

    def _handle_shutdown(signum, frame):
        log.info("received signal %s, shutting down", signum)
        if bpup_listener is not None:
            bpup_listener.stop()
        rf_source.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)


def main() -> int:
    config = load_config(OPTIONS_PATH)
    bond_client = BondClient(config.bond_host, config.bond_token)
    last_speed_store = LastSpeedStore(LAST_SPEED_PATH)
    event_log = EventLog()
    echo_tokens = EchoTokenQueue(config.bond_echo_ttl_seconds)
    bpup_listener = BPUPListener(config.bond_host, echo_tokens)
    pipeline = Pipeline(config, bond_client, last_speed_store, event_log, echo_tokens)
    # Toggle buttons get the short burst gap so each physical press produces
    # its own correction; speed keeps the long debounce because its body is
    # absolute and coalescing repeats is the desired behaviour there.
    debouncer = Debouncer(
        config.debounce_seconds,
        pipeline.handle_event,
        quiet_seconds_by_button={b: config.burst_gap_seconds for b in TOGGLE_BUTTONS},
    )
    rf_source = RFSourceManager(
        config,
        stale_timeout_seconds=config.rtl433_stale_timeout_seconds,
        liveness_probe_interval_seconds=config.rtl433_liveness_probe_interval_seconds,
        liveness_probe_timeout_seconds=config.rtl433_liveness_probe_timeout_seconds,
    )
    _install_shutdown_handler(rf_source, bpup_listener)
    bpup_listener.start()

    pipeline_thread = threading.Thread(
        target=run_pipeline, args=(config, rf_source, debouncer), daemon=True
    )
    pipeline_thread.start()

    app = create_app(event_log)
    app.run(host="0.0.0.0", port=8100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
