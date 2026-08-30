from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections.abc import Callable, Iterator

from app.config import Config

FLEX_DECODER = "n=fan,m=OOK_PWM,s=744,l=376,r=900,g=900,t=150,y=0"

# Sentinel put on the reader-thread queue when the subprocess's stdout hits
# real EOF (i.e. the process exited on its own) - distinct from a queue.get()
# timeout, which means the process is still alive but has gone quiet.
_EOF = object()


def build_source_args(config: Config) -> list[str]:
    """The only thing that differs between local-USB and remote-rtl_tcp
    modes; everything else about the rtl_433 invocation is identical."""
    args: list[str] = []
    if config.rtl433_source == "rtl_tcp":
        args += ["-d", f"rtl_tcp:{config.rtl433_source_host}:{config.rtl433_source_port}"]
    args += [
        "-f", str(config.rtl433_frequency),
        "-s", str(config.rtl433_sample_rate),
        "-g", str(config.rtl433_gain),
    ]
    return args


def rtl433_command(config: Config) -> list[str]:
    return ["rtl_433", *build_source_args(config), "-R", "0", "-X", FLEX_DECODER]


def default_liveness_probe(config: Config, timeout: float) -> Callable[[], bool] | None:
    """Builds a probe that checks whether the rtl_tcp source *host* is
    reachable, independent of RF activity. Real wall-switch presses can
    legitimately be hours apart, so silence on rtl_433's stdout alone is
    not a reliable "the connection died" signal (2026-08-19 #1: the
    stale-output watchdog fired overnight on completely normal RF
    inactivity, not an actual failure) - probing directly gives a real,
    fast signal that doesn't depend on anyone touching a switch.

    Deliberately checks reachability via ICMP ping, NOT a second TCP
    connection to the source port. An earlier version opened a second
    `socket.create_connection` to the exact host:port that rtl_433's real
    data connection already uses - but rtl_tcp only accepts one client,
    so that second connection could never cleanly succeed while the real
    one was healthy. It just hung until timeout, which then killed the
    perfectly-good rtl_433 process, which made the SDR re-tune, which
    generated noise that got misdecoded as fake wall-switch presses
    (2026-08-19 #2: reproduced live - a spurious "livingroom/light" Bond
    correction followed a probe-forced restart with no real button
    press). Pinging the host instead never touches rtl_tcp's one
    connection slot at all, so it can't compete with the real client.

    Returns None for local-USB mode, where there's no remote host to
    probe; the stale-output watchdog is the only applicable safety net
    there."""
    if config.rtl433_source != "rtl_tcp":
        return None
    host = config.rtl433_source_host
    ping_timeout = max(1, int(timeout))

    def probe() -> bool:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(ping_timeout), host],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout + 2,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    return probe


class RFSourceManager:
    """Spawns rtl_433 (or, in tests, a fake stand-in command) and yields its
    stdout lines, restarting with a fixed backoff if the process exits
    unexpectedly (SDR unplugged, rtl_tcp connection dropped, etc.), if an
    active liveness probe reports the source unreachable (see
    default_liveness_probe), or - as a last-resort safety net - if it goes
    silent for longer than stale_timeout_seconds while still nominally
    running."""

    def __init__(
        self,
        config: Config,
        restart_backoff_seconds: float = 5.0,
        stale_timeout_seconds: float = 21600.0,
        liveness_probe_interval_seconds: float = 60.0,
        liveness_probe_timeout_seconds: float = 10.0,
        terminate_timeout_seconds: float = 5.0,
        command: list[str] | None = None,
        liveness_probe: Callable[[], bool] | None = None,
    ):
        self._restart_backoff_seconds = restart_backoff_seconds
        self._stale_timeout_seconds = stale_timeout_seconds
        self._liveness_probe_interval_seconds = liveness_probe_interval_seconds
        self._terminate_timeout_seconds = terminate_timeout_seconds
        self._command = command or rtl433_command(config)
        self._liveness_probe = (
            liveness_probe
            if liveness_probe is not None
            else default_liveness_probe(config, liveness_probe_timeout_seconds)
        )
        self._stopped = False
        self._stop_event = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._prober_started = False
        self._probe_triggered_kill = threading.Event()

    def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        self._terminate_current_proc()

    def _terminate_current_proc(self) -> None:
        with self._lock:
            if self._proc is not None:
                self._proc.terminate()

    def _run_liveness_prober(self) -> None:
        assert self._liveness_probe is not None
        while not self._stop_event.wait(self._liveness_probe_interval_seconds):
            try:
                reachable = self._liveness_probe()
            except Exception as exc:  # noqa: BLE001 - never let the prober die silently;
                # a raising probe means "couldn't confirm reachability", not "confirmed
                # unreachable" - keep looping rather than forcing a restart on it, and
                # rely on the stale-timeout fallback if something is actually wrong.
                print(
                    f"liveness probe raised {exc!r}, will retry next interval",
                    flush=True,
                )
                continue
            if not reachable:
                print(
                    "rtl_433 source unreachable (liveness probe failed), forcing restart",
                    flush=True,
                )
                self._probe_triggered_kill.set()
                self._terminate_current_proc()

    @staticmethod
    def _pump_stdout(proc: subprocess.Popen, out: queue.Queue[object]) -> None:
        """Runs in a background thread so the main loop can apply a timeout
        to stdout inactivity - a plain `for line in proc.stdout` blocks
        forever if the process is alive but has stopped producing output
        (e.g. rtl_433's underlying rtl_tcp connection hung without the
        process itself exiting), which is exactly what happened in the real
        2026-08-17/18 incident this watchdog exists to catch."""
        assert proc.stdout is not None
        for line in proc.stdout:
            out.put(line.rstrip())
        out.put(_EOF)

    def lines(self) -> Iterator[str]:
        if self._liveness_probe is not None and not self._prober_started:
            self._prober_started = True
            threading.Thread(target=self._run_liveness_prober, daemon=True).start()
        while not self._stopped:
            try:
                proc = subprocess.Popen(
                    self._command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                print(
                    f"failed to start rtl_433 ({exc}), retrying in "
                    f"{self._restart_backoff_seconds}s",
                    flush=True,
                )
                time.sleep(self._restart_backoff_seconds)
                continue
            with self._lock:
                self._proc = proc

            out: queue.Queue[object] = queue.Queue()
            reader = threading.Thread(target=self._pump_stdout, args=(proc, out), daemon=True)
            reader.start()

            stale = False
            try:
                while True:
                    try:
                        item = out.get(timeout=self._stale_timeout_seconds)
                    except queue.Empty:
                        stale = True
                        break
                    if item is _EOF:
                        break
                    yield item
                    if self._stopped:
                        return
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=self._terminate_timeout_seconds)
                except subprocess.TimeoutExpired:
                    # Process ignored SIGTERM (e.g. blocked on a dead
                    # rtl_tcp connection) - escalate rather than block this
                    # whole loop forever (2026-08-29 incident: proc.wait()
                    # here had no timeout, so a non-responsive rtl_433 froze
                    # the entire manager - no further restarts, no further
                    # log lines - for 22+ hours until manually restarted).
                    proc.kill()
                    proc.wait()
                proc.stdout.close()
                with self._lock:
                    self._proc = None
            if self._stopped:
                return
            if stale:
                print(
                    f"no rtl_433 output for {self._stale_timeout_seconds}s, presumed "
                    f"hung, restarting in {self._restart_backoff_seconds}s",
                    flush=True,
                )
            elif self._probe_triggered_kill.is_set():
                self._probe_triggered_kill.clear()
                print(
                    f"rtl_433 exited (code={proc.returncode}) after a liveness probe "
                    f"failure, restarting in {self._restart_backoff_seconds}s",
                    flush=True,
                )
            else:
                print(
                    f"rtl_433 exited (code={proc.returncode}), restarting in "
                    f"{self._restart_backoff_seconds}s",
                    flush=True,
                )
            time.sleep(self._restart_backoff_seconds)
