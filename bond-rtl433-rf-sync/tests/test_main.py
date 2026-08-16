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
