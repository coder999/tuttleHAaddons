from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
from collections import deque

log = logging.getLogger("bond-rtl433-rf-sync")

BPUP_PORT = 30007
BPUP_KEEPALIVE_SECONDS = 60.0
BPUP_RECONNECT_SECONDS = 5.0

_ACTION_TOPIC_RE = re.compile(r"^devices/([^/]+)/actions/([^/]+)$")

# Maps a Bond action to the button the RF DECODER emits when it hears that
# action's transmission -- which is NOT always the button the action's name
# implies. On this hardware TurnOn/TurnOff transmit the fan's *speed* code
# (stable_id 27f), so match_line() reports "speed", never "power"; verified
# live 2026-09-11 by commanding TurnOn/TurnOff and reading the add-on log.
#
# This mapping must stay in the decoder's vocabulary, not the API's. Keying
# TurnOn to "power" would enqueue a token under a key nothing ever consumes:
# the genuine echo would arrive as "speed", find no token, and be "corrected"
# -- suppression silently doing nothing while appearing configured.
ACTION_TO_BUTTON = {
    "TurnLightOn": "light",
    "TurnLightOff": "light",
    "ToggleLight": "light",
    "SetBrightness": "light",
    "TurnOn": "speed",
    "TurnOff": "speed",
    "TogglePower": "speed",
    "SetSpeed": "speed",
    "IncreaseSpeed": "speed",
    "DecreaseSpeed": "speed",
}


def parse_action_topic(topic: str) -> tuple[str, str] | None:
    """(device_id, action) for a `devices/<id>/actions/<Action>` BPUP topic,
    None for any other topic (notably `devices/<id>/state`, which is what a
    belief-only PATCH emits and must never be treated as a transmission)."""
    m = _ACTION_TOPIC_RE.match(topic)
    if not m:
        return None
    return m.group(1), m.group(2)


class EchoTokenQueue:
    """Counts transmissions the Bond Bridge has told us it is about to make,
    so the RF decode of each one can be recognised as our own echo instead of
    a wall-switch press.

    A queue of one-shot tokens, deliberately NOT a time window. A window
    covering "the next N seconds after a command" would also swallow a
    genuine press that lands inside it -- exactly the case the wall switch
    makes common (command the light from HA, walk over, press the switch).
    Consuming exactly one token per Bond transmission suppresses exactly the
    echoes and nothing else.
    """

    def __init__(self, ttl_seconds: float):
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def enqueue(self, device_id: str, button: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._tokens.setdefault((device_id, button), deque()).append(now)

    def consume(self, device_id: str, button: str, now: float | None = None) -> bool:
        """Consumes ONE unexpired token for this (device, button), returning
        whether one was found. Expired tokens are dropped rather than used:
        a transmission we never decoded (garbled, out of range, SDR restart)
        must not leave a token behind that later eats a real press."""
        now = time.monotonic() if now is None else now
        key = (device_id, button)
        with self._lock:
            tokens = self._tokens.get(key)
            if tokens is None:
                return False
            while tokens and now - tokens[0] > self._ttl_seconds:
                tokens.popleft()
            consumed = bool(tokens)
            if consumed:
                tokens.popleft()
            if not tokens:
                self._tokens.pop(key, None)
            return consumed

    def pending(self) -> int:
        """Total unexpired-or-not tokens outstanding; for tests and logging."""
        with self._lock:
            return sum(len(t) for t in self._tokens.values())


class BPUPListener:
    """Subscribes to the Bond Bridge Push UDP Protocol and enqueues one echo
    token per transmission the bridge announces.

    Bond announces a real RF transmission as `devices/<id>/actions/<Action>`
    and a belief-only state write as `devices/<id>/state`. Only the former
    produces a token, which is what lets this add-on's own PATCH corrections
    coexist with echo suppression -- a PATCH emits no `/actions/` push, so it
    cannot be mistaken for something the bridge put on the air.
    """

    def __init__(
        self,
        host: str,
        token_queue: EchoTokenQueue,
        port: int = BPUP_PORT,
        keepalive_seconds: float = BPUP_KEEPALIVE_SECONDS,
    ):
        self._host = host
        self._port = port
        self._tokens = token_queue
        self._keepalive_seconds = keepalive_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="bpup-listener")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._listen()
            except Exception as exc:  # noqa: BLE001 - a dead listener must not kill the add-on
                # Losing BPUP costs echo suppression, not correctness of the
                # RF path, so retry forever rather than exiting: the fan keeps
                # tracking wall-switch presses while the bridge is unreachable.
                log.error("BPUP listener error (%s); reconnecting in %.0fs", exc,
                          BPUP_RECONNECT_SECONDS)
                self._stop.wait(BPUP_RECONNECT_SECONDS)

    def _listen(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1.0)
            sock.connect((self._host, self._port))
            sock.send(b"\n")
            log.info("BPUP listener subscribed to %s:%s", self._host, self._port)
            last_keepalive = time.monotonic()
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_keepalive >= self._keepalive_seconds:
                    sock.send(b"\n")
                    last_keepalive = now
                try:
                    data = sock.recv(65535)
                except socket.timeout:
                    continue
                self.handle_datagram(data)

    def handle_datagram(self, data: bytes) -> None:
        """Public so tests can drive the parse/enqueue path without a socket."""
        try:
            msg = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(msg, dict):
            return
        topic = msg.get("t")
        if not isinstance(topic, str):
            # Keepalive acknowledgements carry no topic.
            return
        parsed = parse_action_topic(topic)
        if parsed is None:
            return
        device_id, action = parsed
        button = ACTION_TO_BUTTON.get(action)
        if button is None:
            # Worth a log line rather than a silent drop: an unmapped action is
            # a transmission whose echo will be "corrected" as a real press.
            log.warning("BPUP: unmapped action %r on %s - its echo will not be "
                        "suppressed; add it to ACTION_TO_BUTTON", action, device_id)
            return
        self._tokens.enqueue(device_id, button)
        log.info("BPUP: %s %s -> expecting one %s echo", device_id, action, button)
