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


BURST_GAP = 0.05
LONG_DEBOUNCE = 0.5


def _burst_debouncer(fired):
    """A Debouncer configured the way main() configures it: toggle buttons on
    the short burst gap, everything else on the long debounce."""
    return Debouncer(
        LONG_DEBOUNCE, fired.append, quiet_seconds_by_button={"light": BURST_GAP,
                                                              "power": BURST_GAP}
    )


def _press(d, event, repeats=5, spacing=BURST_GAP / 5):
    """One physical press: the switch re-transmits the same code several times
    in quick succession (~60ms apart in the field)."""
    for _ in range(repeats):
        d.see(event)
        time.sleep(spacing)


def test_quiet_period_is_per_button():
    d = Debouncer(LONG_DEBOUNCE, lambda e: None,
                  quiet_seconds_by_button={"light": BURST_GAP})
    assert d.quiet_seconds_for("light") == BURST_GAP
    assert d.quiet_seconds_for("speed") == LONG_DEBOUNCE
    assert d.quiet_seconds_for("power") == LONG_DEBOUNCE


def test_one_press_is_one_toggle_despite_rf_repeats():
    fired = []
    d = _burst_debouncer(fired)
    event = MatchedEvent(room="diningroom", button="light", percentage=None)
    _press(d, event)
    d.join_pending(timeout=1)
    assert fired == [event]


def test_two_light_presses_inside_the_old_debounce_window_fire_twice():
    """The press-count-loss regression. Under the old single 3.0s trailing-edge
    debounce these two presses collapsed into ONE correction: the bulb toggled
    twice, Bond's belief toggled once, and Bond stayed inverted from then on.
    The gap here is longer than BURST_GAP but shorter than LONG_DEBOUNCE, which
    is exactly the case that used to be lost."""
    fired = []
    d = _burst_debouncer(fired)
    event = MatchedEvent(room="diningroom", button="light", percentage=None)
    _press(d, event)
    time.sleep(BURST_GAP * 3)
    _press(d, event)
    d.join_pending(timeout=1)
    assert len(fired) == 2


def test_three_rapid_power_presses_fire_three_times():
    """Power is a believed-state toggle too, so it loses presses the same way
    light does and gets the same burst segmentation."""
    fired = []
    d = _burst_debouncer(fired)
    event = MatchedEvent(room="diningroom", button="power", percentage=None)
    for _ in range(3):
        _press(d, event)
        time.sleep(BURST_GAP * 3)
    d.join_pending(timeout=1)
    assert len(fired) == 3


def test_speed_still_coalesces_on_the_long_debounce():
    """Speed's correction body is absolute, so collapsing repeats is correct
    and saves pointless API calls - it must NOT get burst segmentation."""
    fired = []
    d = _burst_debouncer(fired)
    event = MatchedEvent(room="diningroom", button="speed", percentage=66)
    _press(d, event)
    time.sleep(BURST_GAP * 3)
    _press(d, event)
    d.join_pending(timeout=2)
    assert fired == [event]
