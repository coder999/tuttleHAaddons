import pytest
from app.config import Config, ConfigError, parse_config


def _base_raw():
    return {
        "bond_host": "192.168.0.110",
        "bond_token": "secret",
        "rtl433_source": "local",
        "code_table": [
            {"room": "livingroom", "button": "speed", "stable_id": "1ff"},
        ],
        "room_devices": [
            {"room": "livingroom", "bond_device_id": "ce4d90389da6937f", "max_speed": 3},
        ],
    }


def test_parse_config_valid_minimal():
    cfg = parse_config(_base_raw())
    assert isinstance(cfg, Config)
    assert cfg.bond_host == "192.168.0.110"
    assert cfg.code_table[0].stable_id == 0x1FF
    assert cfg.debounce_seconds == 3.0
    assert cfg.dry_run is False


def test_parse_config_missing_required_field():
    raw = _base_raw()
    del raw["bond_host"]
    with pytest.raises(ConfigError, match="bond_host"):
        parse_config(raw)


def test_parse_config_invalid_rtl433_source():
    raw = _base_raw()
    raw["rtl433_source"] = "usb_stick"
    with pytest.raises(ConfigError, match="rtl433_source"):
        parse_config(raw)


def test_parse_config_rtl_tcp_requires_host():
    raw = _base_raw()
    raw["rtl433_source"] = "rtl_tcp"
    with pytest.raises(ConfigError, match="rtl433_source_host"):
        parse_config(raw)


def test_parse_config_rtl_tcp_with_host_succeeds():
    raw = _base_raw()
    raw["rtl433_source"] = "rtl_tcp"
    raw["rtl433_source_host"] = "192.168.0.50"
    cfg = parse_config(raw)
    assert cfg.rtl433_source_host == "192.168.0.50"
    assert cfg.rtl433_source_port == 1234


def test_parse_config_empty_code_table():
    raw = _base_raw()
    raw["code_table"] = []
    with pytest.raises(ConfigError, match="code_table"):
        parse_config(raw)


def test_parse_config_orphaned_room_in_code_table():
    raw = _base_raw()
    raw["code_table"].append({"room": "bedroom", "button": "power", "stable_id": "2d9"})
    with pytest.raises(ConfigError, match="bedroom"):
        parse_config(raw)


def test_parse_config_zero_max_speed_raises():
    raw = _base_raw()
    raw["room_devices"][0]["max_speed"] = 0
    with pytest.raises(ConfigError, match="max_speed"):
        parse_config(raw)


def test_parse_config_rtl433_stale_timeout_seconds_defaults_to_six_hours():
    # Deliberately generous: this is now a last-resort safety net behind the
    # active liveness probe (see rtl433_liveness_probe_interval_seconds
    # below), not the primary detector - a real household can go many hours
    # without a wall-switch press (2026-08-19: the old 1-hour default fired
    # overnight on completely normal RF silence, not an actual failure).
    cfg = parse_config(_base_raw())
    assert cfg.rtl433_stale_timeout_seconds == 21600.0


def test_parse_config_rtl433_stale_timeout_seconds_override():
    raw = _base_raw()
    raw["rtl433_stale_timeout_seconds"] = 300
    cfg = parse_config(raw)
    assert cfg.rtl433_stale_timeout_seconds == 300.0


def test_parse_config_rtl433_liveness_probe_interval_seconds_defaults_to_one_minute():
    cfg = parse_config(_base_raw())
    assert cfg.rtl433_liveness_probe_interval_seconds == 60.0


def test_parse_config_rtl433_liveness_probe_interval_seconds_override():
    raw = _base_raw()
    raw["rtl433_liveness_probe_interval_seconds"] = 30
    cfg = parse_config(raw)
    assert cfg.rtl433_liveness_probe_interval_seconds == 30.0


def test_parse_config_zero_liveness_probe_interval_raises():
    raw = _base_raw()
    raw["rtl433_liveness_probe_interval_seconds"] = 0
    with pytest.raises(ConfigError, match="rtl433_liveness_probe_interval_seconds"):
        parse_config(raw)


def test_parse_config_negative_liveness_probe_interval_raises():
    raw = _base_raw()
    raw["rtl433_liveness_probe_interval_seconds"] = -1
    with pytest.raises(ConfigError, match="rtl433_liveness_probe_interval_seconds"):
        parse_config(raw)


def test_parse_config_rtl433_liveness_probe_timeout_seconds_defaults_to_ten():
    cfg = parse_config(_base_raw())
    assert cfg.rtl433_liveness_probe_timeout_seconds == 10.0


def test_parse_config_rtl433_liveness_probe_timeout_seconds_override():
    raw = _base_raw()
    raw["rtl433_liveness_probe_timeout_seconds"] = 3
    cfg = parse_config(raw)
    assert cfg.rtl433_liveness_probe_timeout_seconds == 3.0


def test_parse_config_zero_liveness_probe_timeout_raises():
    raw = _base_raw()
    raw["rtl433_liveness_probe_timeout_seconds"] = 0
    with pytest.raises(ConfigError, match="rtl433_liveness_probe_timeout_seconds"):
        parse_config(raw)


def test_parse_config_too_small_liveness_probe_interval_raises():
    # A positive but too-small interval can livelock the restart loop: a
    # freshly-spawned rtl_433 gets killed by the next probe check before it
    # has any real chance to reconnect and produce output.
    raw = _base_raw()
    raw["rtl433_liveness_probe_interval_seconds"] = 1
    with pytest.raises(ConfigError, match="rtl433_liveness_probe_interval_seconds"):
        parse_config(raw)


def test_parse_config_zero_stale_timeout_raises():
    raw = _base_raw()
    raw["rtl433_stale_timeout_seconds"] = 0
    with pytest.raises(ConfigError, match="rtl433_stale_timeout_seconds"):
        parse_config(raw)


def test_parse_config_negative_stale_timeout_raises():
    raw = _base_raw()
    raw["rtl433_stale_timeout_seconds"] = -5
    with pytest.raises(ConfigError, match="rtl433_stale_timeout_seconds"):
        parse_config(raw)


def test_device_for_room_lookup():
    cfg = parse_config(_base_raw())
    device = cfg.device_for_room("livingroom")
    assert device.bond_device_id == "ce4d90389da6937f"
    assert device.max_speed == 3


def test_device_for_room_missing_raises():
    cfg = parse_config(_base_raw())
    with pytest.raises(ValueError, match="diningroom"):
        cfg.device_for_room("diningroom")
