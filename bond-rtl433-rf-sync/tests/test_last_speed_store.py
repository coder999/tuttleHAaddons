import json

from app.last_speed_store import LastSpeedStore


def test_get_returns_default_when_room_unknown(tmp_path):
    store = LastSpeedStore(tmp_path / "last_speed.json")
    assert store.get("bedroom") == 100
    assert store.get("bedroom", default=66) == 66


def test_set_then_get_returns_stored_value(tmp_path):
    store = LastSpeedStore(tmp_path / "last_speed.json")
    store.set("bedroom", 33)
    assert store.get("bedroom") == 33


def test_set_zero_percentage_is_ignored(tmp_path):
    store = LastSpeedStore(tmp_path / "last_speed.json")
    store.set("bedroom", 66)
    store.set("bedroom", 0)
    assert store.get("bedroom") == 66


def test_persists_across_instances(tmp_path):
    path = tmp_path / "last_speed.json"
    LastSpeedStore(path).set("livingroom", 100)
    reloaded = LastSpeedStore(path)
    assert reloaded.get("livingroom") == 100


def test_corrupted_file_falls_back_to_empty(tmp_path):
    path = tmp_path / "last_speed.json"
    path.write_text("not valid json{{{")
    store = LastSpeedStore(path)
    assert store.get("diningroom") == 100
    store.set("diningroom", 33)
    assert json.loads(path.read_text()) == {"diningroom": 33}
