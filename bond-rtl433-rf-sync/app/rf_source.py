from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections.abc import Iterator

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


class RFSourceManager:
    """Spawns rtl_433 (or, in tests, a fake stand-in command) and yields its
    stdout lines, restarting with a fixed backoff if the process exits
    unexpectedly (SDR unplugged, rtl_tcp connection dropped, etc.) or if it
    goes silent for longer than stale_timeout_seconds while still nominally
    running (rtl_tcp connection hung without the process itself exiting)."""

    def __init__(
        self,
        config: Config,
        restart_backoff_seconds: float = 5.0,
        stale_timeout_seconds: float = 3600.0,
        command: list[str] | None = None,
    ):
        self._restart_backoff_seconds = restart_backoff_seconds
        self._stale_timeout_seconds = stale_timeout_seconds
        self._command = command or rtl433_command(config)
        self._stopped = False
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        self._stopped = True
        with self._lock:
            if self._proc is not None:
                self._proc.terminate()

    @staticmethod
    def _pump_stdout(proc: subprocess.Popen, out: "queue.Queue[object]") -> None:
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

            out: "queue.Queue[object]" = queue.Queue()
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
                    yield item  # type: ignore[misc]
                    if self._stopped:
                        return
            finally:
                proc.terminate()
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
            else:
                print(
                    f"rtl_433 exited (code={proc.returncode}), restarting in "
                    f"{self._restart_backoff_seconds}s",
                    flush=True,
                )
            time.sleep(self._restart_backoff_seconds)
