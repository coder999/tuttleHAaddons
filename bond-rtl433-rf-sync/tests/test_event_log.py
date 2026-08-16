from app.event_log import EventLog


def test_record_appends_event():
    log = EventLog()
    log.record("livingroom", "speed", 66, {"power": 1, "speed": 2}, "ok")
    events = log.recent_events()
    assert len(events) == 1
    assert events[0].room == "livingroom"
    assert events[0].body == {"power": 1, "speed": 2}
    assert events[0].result == "ok"


def test_record_updates_current_state_for_room():
    log = EventLog()
    log.record("livingroom", "speed", 66, {"power": 1, "speed": 2}, "ok")
    assert log.current_state() == {"livingroom": {"power": 1, "speed": 2}}


def test_current_state_merges_multiple_updates_for_same_room():
    log = EventLog()
    log.record("livingroom", "speed", 66, {"power": 1, "speed": 2}, "ok")
    log.record("livingroom", "light", None, {"light": 1}, "ok")
    assert log.current_state() == {"livingroom": {"power": 1, "speed": 2, "light": 1}}


def test_recent_events_returns_newest_first():
    log = EventLog()
    log.record("livingroom", "power", None, {"power": 1}, "ok")
    log.record("bedroom", "light", None, {"light": 1}, "ok")
    events = log.recent_events()
    assert [e.room for e in events] == ["bedroom", "livingroom"]


def test_ring_buffer_respects_max_events():
    log = EventLog(max_events=3)
    for i in range(5):
        log.record("livingroom", "power", None, {"power": i}, "ok")
    events = log.recent_events()
    assert len(events) == 3
    # newest first, oldest two (body power=0, power=1) dropped
    assert [e.body["power"] for e in events] == [4, 3, 2]
