import subprocess

from app.config import parse_config
from app.rf_source import RFSourceManager, build_source_args, rtl433_command


def _config(**overrides):
    raw = {
        "bond_host": "192.168.0.110",
        "bond_token": "secret",
        "rtl433_source": "local",
        "rtl433_frequency": 304250000,
        "rtl433_sample_rate": 2048000,
        "rtl433_gain": 49.6,
        "code_table": [{"room": "livingroom", "button": "power", "stable_id": "1d9"}],
        "room_devices": [
            {"room": "livingroom", "bond_device_id": "ce4d90389da6937f", "max_speed": 3}
        ],
    }
    raw.update(overrides)
    return parse_config(raw)


def test_build_source_args_local_mode_has_no_device_flag():
    args = build_source_args(_config(rtl433_source="local"))
    assert "-d" not in args
    assert args == ["-f", "304250000", "-s", "2048000", "-g", "49.6"]


def test_build_source_args_rtl_tcp_mode_prepends_device_flag():
    args = build_source_args(
        _config(
            rtl433_source="rtl_tcp",
            rtl433_source_host="192.168.0.50",
            rtl433_source_port=1234,
        )
    )
    assert args[:2] == ["-d", "rtl_tcp:192.168.0.50:1234"]
    assert args[2:] == ["-f", "304250000", "-s", "2048000", "-g", "49.6"]


def test_rtl433_command_disables_builtin_protocols_and_sets_flex_decoder():
    cmd = rtl433_command(_config())
    assert cmd[0] == "rtl_433"
    assert cmd[cmd.index("-R") + 1] == "0"
    assert "m=OOK_PWM" in cmd[cmd.index("-X") + 1]


def test_lines_yields_subprocess_stdout():
    manager = RFSourceManager(
        _config(),
        command=["python3", "-c", "print('line1'); print('line2')"],
    )
    lines = []
    for line in manager.lines():
        lines.append(line)
        if len(lines) == 2:
            manager.stop()
    assert lines == ["line1", "line2"]


def test_lines_restarts_process_after_it_exits():
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.05,
        command=["python3", "-c", "print('tick')"],
    )
    lines = []
    for line in manager.lines():
        lines.append(line)
        if len(lines) == 3:
            manager.stop()
            break
    assert lines == ["tick", "tick", "tick"]


def test_lines_restarts_process_after_prolonged_silence():
    """Covers the real 2026-08-17/18 incident: rtl_433's underlying rtl_tcp
    connection went silently dead (pi WiFi hang) without the rtl_433 process
    itself exiting, so the old exit-triggered restart never fired and the
    add-on sat blocked on a dead subprocess for over a day with no output
    and no error logged."""
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.01,
        stale_timeout_seconds=0.05,
        command=["python3", "-c", "print('line1', flush=True); import time; time.sleep(60)"],
    )
    lines = []
    for line in manager.lines():
        lines.append(line)
        if len(lines) == 2:
            manager.stop()
            break
    # First "line1" from the original (now-hung) process; staleness watchdog
    # kills and restarts it, and the fresh process prints "line1" again.
    assert lines == ["line1", "line1"]


def test_lines_retries_after_popen_raises_on_spawn(monkeypatch):
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.01,
        command=["python3", "-c", "print('ok')"],
    )

    real_popen = subprocess.Popen
    calls = {"count": 0}

    def flaky_popen(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise FileNotFoundError("rtl_433: command not found")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", flaky_popen)

    lines = []
    for line in manager.lines():
        lines.append(line)
        manager.stop()
        break

    assert lines == ["ok"]
    assert calls["count"] == 2
