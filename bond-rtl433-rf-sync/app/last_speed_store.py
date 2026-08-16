from __future__ import annotations

import json
import threading
from pathlib import Path


class LastSpeedStore:
    """Persists each room's last known non-zero fan speed percentage,
    functionally replacing HA's input_number.<room>_last_fan_speed helpers.
    """

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def get(self, room: str, default: int = 100) -> int:
        with self._lock:
            return self._data.get(room, default)

    def set(self, room: str, percentage: int) -> None:
        if percentage <= 0:
            return
        with self._lock:
            self._data[room] = percentage
            self._path.write_text(json.dumps(self._data))
