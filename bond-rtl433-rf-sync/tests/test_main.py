import signal
import threading
import time

import pytest

from app.config import parse_config
from app.debouncer import Debouncer
from app.matcher import MatchedEvent
from app.main import _install_shutdown_handler, run_pipeline
from app.rf_source import RFSourceManager


def _config():
    raw = {
        "bond_host": "192.168.0.110",
        "bond_token": "tok",
        "rtl433_source": "local",
        "debounce_seconds": 0.3,
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
        time.sleep(0.5)
        rf_source.stop()

    threading.Thread(target=stop_soon, daemon=True).start()
    run_pipeline(config, rf_source, debouncer)
    debouncer.join_pending(timeout=2)

    assert seen == [MatchedEvent(room="livingroom", button="power", percentage=None)]


def test_install_shutdown_handler_stops_rf_source_on_sigterm_and_sigint(monkeypatch):
    stopped = []

    class FakeRFSource:
        def stop(self):
            stopped.append(True)

    registered = {}

    def fake_signal(sig, handler):
        registered[sig] = handler

    monkeypatch.setattr(signal, "signal", fake_signal)

    _install_shutdown_handler(FakeRFSource())

    assert signal.SIGTERM in registered
    assert signal.SIGINT in registered

    with pytest.raises(SystemExit):
        registered[signal.SIGTERM](signal.SIGTERM, None)

    assert stopped == [True]
