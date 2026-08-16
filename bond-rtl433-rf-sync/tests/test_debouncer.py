import time

from app.debouncer import Debouncer
from app.matcher import MatchedEvent

QUIET = 0.05


def test_single_event_fires_once_after_quiet_period():
    fired = []
    d = Debouncer(QUIET, fired.append)
    event = MatchedEvent(room="livingroom", button="power", percentage=None)
    d.see(event)
    d.join_pending(timeout=1)
    assert fired == [event]


def test_repeated_events_same_key_coalesce_into_one_fire():
    fired = []
    d = Debouncer(QUIET, fired.append)
    event = MatchedEvent(room="livingroom", button="speed", percentage=66)
    for _ in range(5):
        d.see(event)
        time.sleep(QUIET / 5)
    d.join_pending(timeout=1)
    assert fired == [event]


def test_different_keys_fire_independently():
    fired = []
    d = Debouncer(QUIET, fired.append)
    e1 = MatchedEvent(room="livingroom", button="power", percentage=None)
    e2 = MatchedEvent(room="bedroom", button="light", percentage=None)
    d.see(e1)
    d.see(e2)
    d.join_pending(timeout=1)
    assert {e.room for e in fired} == {"livingroom", "bedroom"}


def test_rapid_repeats_delay_firing_past_naive_quiet_period():
    fired = []
    d = Debouncer(QUIET, fired.append)
    event = MatchedEvent(room="livingroom", button="power", percentage=None)
    start = time.monotonic()
    for _ in range(4):
        d.see(event)
        time.sleep(QUIET * 0.6)
    d.join_pending(timeout=1)
    elapsed = time.monotonic() - start
    assert fired == [event]
    assert elapsed >= QUIET
