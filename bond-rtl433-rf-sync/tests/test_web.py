from app.event_log import EventLog
from app.web import create_app


def test_index_returns_200():
    app = create_app(EventLog())
    resp = app.test_client().get("/")
    assert resp.status_code == 200


def test_index_shows_recorded_event():
    event_log = EventLog()
    event_log.record("livingroom", "speed", 66, {"power": 1, "speed": 2}, "ok")
    app = create_app(event_log)
    body = app.test_client().get("/").get_data(as_text=True)
    assert "livingroom" in body
    assert "speed" in body


def test_index_shows_current_state():
    event_log = EventLog()
    event_log.record("bedroom", "power", None, {"power": 1}, "ok")
    app = create_app(event_log)
    body = app.test_client().get("/").get_data(as_text=True)
    assert "bedroom" in body


def test_healthz_returns_ok():
    app = create_app(EventLog())
    resp = app.test_client().get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
