from __future__ import annotations

import threading
from typing import Callable

from app.matcher import MatchedEvent

FireCallback = Callable[[MatchedEvent], None]


class Debouncer:
    """Trailing-edge debounce: coalesces repeated matches of the same
    (room, button, percentage) into one callback firing `quiet_seconds`
    after the LAST matching event, resetting the timer on every repeat.
    Mirrors fan_wallswitch_bridge.py's proven behavior (a held/repeated
    button re-transmits several times; we want one logical event per
    physical press, not one per RF repeat).
    """

    def __init__(self, quiet_seconds: float, on_fire: FireCallback):
        self._quiet_seconds = quiet_seconds
        self._on_fire = on_fire
        self._timers: dict[tuple[str, str, int | None], threading.Timer] = {}
        self._lock = threading.Lock()

    def see(self, event: MatchedEvent) -> None:
        key = (event.room, event.button, event.percentage)
        with self._lock:
            existing = self._timers.get(key)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(self._quiet_seconds, self._fire, args=(key, event))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _fire(self, key: tuple[str, str, int | None], event: MatchedEvent) -> None:
        with self._lock:
            self._timers.pop(key, None)
        self._on_fire(event)

    def join_pending(self, timeout: float | None = None) -> None:
        """Block until all pending timers have fired - used by tests and
        graceful shutdown so an in-flight event isn't lost."""
        with self._lock:
            timers = list(self._timers.values())
        for t in timers:
            t.join(timeout=timeout)
