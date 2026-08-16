from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator

from app.config import Config

FLEX_DECODER = "n=fan,m=OOK_PWM,s=744,l=376,r=900,g=900,t=150,y=0"


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
    unexpectedly (SDR unplugged, rtl_tcp connection dropped, etc.)."""

    def __init__(
        self,
        config: Config,
        restart_backoff_seconds: float = 5.0,
        command: list[str] | None = None,
    ):
        self._restart_backoff_seconds = restart_backoff_seconds
        self._command = command or rtl433_command(config)
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def lines(self) -> Iterator[str]:
        while not self._stopped:
            proc = subprocess.Popen(
                self._command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    yield line.rstrip()
                    if self._stopped:
                        proc.terminate()
                        return
            finally:
                proc.wait()
            if self._stopped:
                return
            print(
                f"rtl_433 exited (code={proc.returncode}), restarting in "
                f"{self._restart_backoff_seconds}s",
                flush=True,
            )
            time.sleep(self._restart_backoff_seconds)
