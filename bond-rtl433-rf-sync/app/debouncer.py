from __future__ import annotations

import threading
from typing import Callable, Mapping

from app.matcher import MatchedEvent

FireCallback = Callable[[MatchedEvent], None]

# Buttons whose Bond correction is a *relative* toggle rather than an absolute
# value. These need one fire per physical press, because two presses that
# collapse into one fire leave Bond's belief inverted and it stays inverted.
TOGGLE_BUTTONS = ("light", "power")


class Debouncer:
    """Trailing-edge debounce that coalesces repeated matches of the same
    (room, button, percentage) into one callback firing `quiet_seconds` after
    the LAST matching event, resetting the timer on every repeat.

    The quiet period is per-button, because "how long is one press?" and "how
    long between presses?" are different questions and the buttons want
    different answers:

    * Toggle buttons (light, power) use a short `burst_gap_seconds` (~0.5s).
      One press re-transmits every ~60ms for at most ~0.8s, while distinct
      presses are seconds apart -- so a 0.5s silence reliably separates
      presses, and each burst becomes exactly one toggle. A long quiet period
      here is a bug: N presses inside it collapse to ONE toggle, the bulb
      moves N times, Bond's belief moves once, and it ends inverted.

    * Speed uses the longer `debounce_seconds`. Its correction body is
      absolute ({'power':1,'speed':N}), so collapsing a flurry of repeats into
      one write is correct and saves needless API calls -- losing the count
      costs nothing when the value is not relative.
    """

    def __init__(
        self,
        quiet_seconds: float,
        on_fire: FireCallback,
        quiet_seconds_by_button: Mapping[str, float] | None = None,
    ):
        self._quiet_seconds = quiet_seconds
        self._quiet_seconds_by_button = dict(quiet_seconds_by_button or {})
        self._on_fire = on_fire
        self._timers: dict[tuple[str, str, int | None], threading.Timer] = {}
        self._lock = threading.Lock()

    def quiet_seconds_for(self, button: str) -> float:
        return self._quiet_seconds_by_button.get(button, self._quiet_seconds)

    def see(self, event: MatchedEvent) -> None:
        key = (event.room, event.button, event.percentage)
        with self._lock:
            existing = self._timers.get(key)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(
                self.quiet_seconds_for(event.button), self._fire, args=(key, event)
            )
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _fire(self, key: tuple[str, str, int | None], event: MatchedEvent) -> None:
        # threading.Timer.cancel() is best-effort: if see() calls cancel()
        # after this timer's thread has already passed its internal
        # "not cancelled" check, this _fire still runs. Guard by identity
        # (not just key) so a stale, superseded timer doesn't pop the
        # newer timer's dict entry out from under it or double-fire --
        # if we're no longer the timer on file for this key, a newer
        # timer has replaced us and will fire the correct final event.
        with self._lock:
            if self._timers.get(key) is not threading.current_thread():
                return
            self._timers.pop(key, None)
        self._on_fire(event)

    def join_pending(self, timeout: float | None = None) -> None:
        """Block until all pending timers have fired - used by tests and
        graceful shutdown so an in-flight event isn't lost."""
        with self._lock:
            timers = list(self._timers.values())
        for t in timers:
            t.join(timeout=timeout)
