from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LoggedEvent:
    timestamp: float
    room: str
    button: str
    percentage: int | None
    body: dict
    result: str


class EventLog:
    """In-memory ring buffer of recent Bond corrections, plus a live
    per-room believed-state snapshot - both feed the ingress panel."""

    def __init__(self, max_events: int = 200):
        self._events: deque[LoggedEvent] = deque(maxlen=max_events)
        self._state: dict[str, dict] = {}
        self._lock = threading.Lock()

    def record(
        self, room: str, button: str, percentage: int | None, body: dict, result: str
    ) -> None:
        event = LoggedEvent(
            timestamp=time.time(),
            room=room,
            button=button,
            percentage=percentage,
            body=body,
            result=result,
        )
        with self._lock:
            self._events.append(event)
            self._state.setdefault(room, {}).update(body)

    def recent_events(self) -> list[LoggedEvent]:
        with self._lock:
            return list(reversed(self._events))

    def current_state(self) -> dict[str, dict]:
        with self._lock:
            return {room: dict(state) for room, state in self._state.items()}
