import subprocess
import threading
import time
import unittest.mock

from app.config import parse_config
from app.rf_source import (
    RFSourceManager,
    build_source_args,
    default_liveness_probe,
    rtl433_command,
)


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


def test_default_liveness_probe_is_none_for_local_source():
    # No remote host to probe in local-USB mode; the stale-output watchdog
    # is the only applicable safety net there.
    assert default_liveness_probe(_config(rtl433_source="local"), timeout=1.0) is None


def test_default_liveness_probe_pings_the_configured_host_not_the_source_port():
    """Root-cause regression test for a real incident (2026-08-19): the
    original probe opened a *second* TCP connection to the same rtl_tcp
    host:port that rtl_433's real data connection already uses. rtl_tcp
    only accepts one client, so that second connection could never
    cleanly succeed while the real connection was healthy - it just hung
    until timeout, which then killed the perfectly-good rtl_433 process,
    which caused the SDR to re-tune, which generated noise that got
    misdecoded as fake wall-switch presses (confirmed: reproduced the
    hang live against the real deployed system, watched it force a
    restart, then watched a spurious "livingroom/light" Bond correction
    follow). The fix: check host reachability via ICMP ping, which never
    touches rtl_tcp's one connection slot at all."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0)

    with unittest.mock.patch.object(subprocess, "run", fake_run):
        probe = default_liveness_probe(
            _config(
                rtl433_source="rtl_tcp",
                rtl433_source_host="192.168.0.27",
                rtl433_source_port=1234,
            ),
            timeout=2.0,
        )
        assert probe is not None
        assert probe() is True

    assert calls, "expected the probe to shell out to ping"
    (cmd,) = calls
    assert "192.168.0.27" in cmd
    assert "1234" not in " ".join(str(c) for c in cmd)  # never touches the source port


def test_default_liveness_probe_false_when_ping_fails():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=1)

    with unittest.mock.patch.object(subprocess, "run", fake_run):
        probe = default_liveness_probe(
            _config(rtl433_source="rtl_tcp", rtl433_source_host="10.255.255.1"),
            timeout=2.0,
        )
        assert probe is not None
        assert probe() is False


def test_default_liveness_probe_false_when_ping_raises():
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 2.0)

    with unittest.mock.patch.object(subprocess, "run", fake_run):
        probe = default_liveness_probe(
            _config(rtl433_source="rtl_tcp", rtl433_source_host="10.255.255.1"),
            timeout=2.0,
        )
        assert probe is not None
        assert probe() is False


def test_default_liveness_probe_real_ping_against_loopback():
    """One real (unmocked) smoke test against an address that should
    always answer ICMP - 127.0.0.1 - so this feature is proven against
    the real `ping` binary at least once, not only against a mock."""
    probe = default_liveness_probe(
        _config(rtl433_source="rtl_tcp", rtl433_source_host="127.0.0.1"),
        timeout=2.0,
    )
    assert probe is not None
    assert probe() is True


def test_lines_liveness_probe_restarts_process_when_unreachable():
    """Covers the real gap found 2026-08-19: the stale-output watchdog
    can't tell 'nobody pressed a switch in a while' apart from 'the
    connection actually died', so it either false-positives on normal
    overnight silence or (once loosened) takes too long to catch a real
    failure. An active liveness probe checks the rtl_tcp connection
    directly, independent of RF activity, so it can react quickly without
    caring how long it's been since the last real event."""
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.01,
        liveness_probe_interval_seconds=0.05,
        command=["python3", "-c", "print('line1', flush=True); import time; time.sleep(60)"],
        liveness_probe=lambda: False,
    )
    lines = []
    for line in manager.lines():
        lines.append(line)
        if len(lines) == 2:
            manager.stop()
            break
    assert lines == ["line1", "line1"]


def test_lines_liveness_probe_does_not_restart_when_reachable():
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.01,
        liveness_probe_interval_seconds=0.02,
        command=["python3", "-c", "print('line1', flush=True); import time; time.sleep(60)"],
        liveness_probe=lambda: True,
    )

    def stop_soon():
        time.sleep(0.3)  # several probe intervals worth, all reporting healthy
        manager.stop()

    threading.Thread(target=stop_soon, daemon=True).start()
    lines = list(manager.lines())
    assert lines == ["line1"]


def test_lines_stop_returns_promptly_with_slow_liveness_probe_interval():
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.01,
        liveness_probe_interval_seconds=30.0,
        command=["python3", "-c", "print('line1', flush=True); import time; time.sleep(60)"],
        liveness_probe=lambda: True,
    )

    def stop_soon():
        time.sleep(0.2)
        manager.stop()

    threading.Thread(target=stop_soon, daemon=True).start()
    start = time.monotonic()
    lines = list(manager.lines())
    elapsed = time.monotonic() - start

    assert lines == ["line1"]
    assert elapsed < 5.0  # nowhere near the 30s probe interval


def test_lines_liveness_prober_survives_probe_exception():
    """An injected (or, in principle, a future built-in) probe that raises
    instead of returning False must not silently kill the prober thread -
    that would permanently and silently fall back to relying solely on the
    6-hour stale-timeout for the rest of the process's life, the exact
    failure mode this whole feature exists to move away from. An
    exception is treated as "couldn't confirm reachability", not as
    "confirmed unreachable" - it does not by itself force a restart,
    since we don't actually know the source is down."""
    calls = {"count": 0}

    def flaky_probe():
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("boom")
        return True

    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.01,
        liveness_probe_interval_seconds=0.02,
        command=["python3", "-c", "print('line1', flush=True); import time; time.sleep(60)"],
        liveness_probe=flaky_probe,
    )

    def stop_soon():
        time.sleep(0.3)
        manager.stop()

    threading.Thread(target=stop_soon, daemon=True).start()
    lines = list(manager.lines())

    assert lines == ["line1"]  # never restarted - the exception didn't force one
    assert calls["count"] >= 2  # prober kept looping after the exception, not dead


def test_lines_local_source_never_starts_liveness_prober():
    """End-to-end through RFSourceManager's real default wiring (no
    liveness_probe= override) - the local-mode no-op isn't just true of
    default_liveness_probe() in isolation, it must actually hold for the
    manager that consumes it."""
    manager = RFSourceManager(
        _config(rtl433_source="local"),
        restart_backoff_seconds=0.01,
        command=["python3", "-c", "print('line1', flush=True)"],
    )
    assert manager._liveness_probe is None

    lines = []
    for line in manager.lines():
        lines.append(line)
        if len(lines) == 1:
            manager.stop()
            break

    assert manager._prober_started is False


def test_lines_exit_log_distinguishes_probe_triggered_restart(capsys):
    """A reader skimming only the 'rtl_433 exited' line (not the prober's
    separate 'forcing restart' line just before it) should still be able
    to tell a probe-triggered kill apart from a genuine crash."""
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.01,
        liveness_probe_interval_seconds=0.05,
        command=["python3", "-c", "print('line1', flush=True); import time; time.sleep(60)"],
        liveness_probe=lambda: False,
    )
    lines = []
    for line in manager.lines():
        lines.append(line)
        if len(lines) == 2:
            manager.stop()
            break

    out = capsys.readouterr().out
    exit_lines = [line for line in out.splitlines() if line.startswith("rtl_433 exited")]
    assert exit_lines, "expected at least one 'rtl_433 exited' log line"
    assert "liveness probe" in exit_lines[0]


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


def test_lines_stop_returns_promptly_during_long_stale_wait():
    """The property the staleness watchdog most depends on for safety:
    stop() must interrupt an in-progress stale-timeout wait immediately,
    not block until the (potentially very long, e.g. the 1-hour default)
    timeout elapses. Uses a deliberately long stale_timeout_seconds and
    asserts stop() (called from another thread, as it is in production via
    the SIGTERM handler) returns almost immediately, not anywhere near it."""
    manager = RFSourceManager(
        _config(),
        restart_backoff_seconds=0.01,
        stale_timeout_seconds=30.0,
        command=["python3", "-c", "print('line1', flush=True); import time; time.sleep(60)"],
    )

    def stop_soon():
        time.sleep(0.2)
        manager.stop()

    threading.Thread(target=stop_soon, daemon=True).start()

    start = time.monotonic()
    lines = list(manager.lines())
    elapsed = time.monotonic() - start

    assert lines == ["line1"]
    assert elapsed < 5.0  # nowhere near the 30s stale timeout


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
