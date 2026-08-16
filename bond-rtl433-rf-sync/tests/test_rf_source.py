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
