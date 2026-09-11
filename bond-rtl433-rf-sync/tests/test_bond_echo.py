from app.bond_echo import (
    ACTION_TO_BUTTON,
    BPUPListener,
    EchoTokenQueue,
    parse_action_topic,
)

DEVICE = "33c72108a1a2548d"


def _datagram(topic=None, **extra):
    import json

    msg = {"B": "ZZEJ48994", "i": "00000000", "f": 255, "s": 200, "m": 0, "b": {}}
    if topic is not None:
        msg["t"] = topic
    msg.update(extra)
    return json.dumps(msg).encode("utf-8")


def test_parse_action_topic_extracts_device_and_action():
    assert parse_action_topic(f"devices/{DEVICE}/actions/TurnLightOn") == (DEVICE, "TurnLightOn")


def test_parse_action_topic_rejects_state_topic():
    """Load-bearing: this add-on's own belief-only PATCH emits a state push.
    If a state topic ever produced a token, every correction would enqueue one
    and the next genuine press would be swallowed as a phantom echo."""
    assert parse_action_topic(f"devices/{DEVICE}/state") is None


def test_parse_action_topic_rejects_unrelated_topics():
    assert parse_action_topic("bridge/info") is None
    assert parse_action_topic(f"devices/{DEVICE}/actions/Turn/Extra") is None


def test_consume_on_empty_queue_is_false():
    q = EchoTokenQueue(ttl_seconds=5.0)
    assert q.consume(DEVICE, "light") is False


def test_enqueued_token_is_consumed_exactly_once():
    q = EchoTokenQueue(ttl_seconds=5.0)
    q.enqueue(DEVICE, "light", now=100.0)
    assert q.consume(DEVICE, "light", now=100.5) is True
    assert q.consume(DEVICE, "light", now=100.6) is False


def test_n_transmissions_suppress_exactly_n_echoes():
    """One token per transmission, so a burst of three commands suppresses
    three echoes and leaves nothing behind to eat a fourth, genuine press."""
    q = EchoTokenQueue(ttl_seconds=5.0)
    for _ in range(3):
        q.enqueue(DEVICE, "light", now=100.0)
    assert [q.consume(DEVICE, "light", now=101.0) for _ in range(4)] == [True, True, True, False]


def test_expired_token_is_dropped_not_consumed():
    """A transmission we never decoded (garbled, SDR restart) must not leave a
    token that later suppresses a real wall-switch press."""
    q = EchoTokenQueue(ttl_seconds=5.0)
    q.enqueue(DEVICE, "light", now=100.0)
    assert q.consume(DEVICE, "light", now=106.0) is False
    assert q.pending() == 0


def test_tokens_do_not_cross_buttons():
    """Keying on device alone would let a speed press consume the light's
    token: the speed press would be skipped AND the light echo would go on to
    be 'corrected', which is the feedback loop this is meant to stop."""
    q = EchoTokenQueue(ttl_seconds=5.0)
    q.enqueue(DEVICE, "light", now=100.0)
    assert q.consume(DEVICE, "speed", now=100.5) is False
    assert q.consume(DEVICE, "light", now=100.5) is True


def test_tokens_do_not_cross_devices():
    q = EchoTokenQueue(ttl_seconds=5.0)
    q.enqueue(DEVICE, "light", now=100.0)
    assert q.consume("ce4d90389da6937f", "light", now=100.5) is False


def test_listener_enqueues_token_for_action_push():
    q = EchoTokenQueue(ttl_seconds=5.0)
    listener = BPUPListener("192.168.0.110", q)
    listener.handle_datagram(_datagram(f"devices/{DEVICE}/actions/TurnLightOff"))
    assert q.consume(DEVICE, "light") is True


def test_listener_ignores_state_push():
    q = EchoTokenQueue(ttl_seconds=5.0)
    listener = BPUPListener("192.168.0.110", q)
    listener.handle_datagram(_datagram(f"devices/{DEVICE}/state"))
    assert q.pending() == 0


def test_listener_ignores_keepalive_and_garbage():
    q = EchoTokenQueue(ttl_seconds=5.0)
    listener = BPUPListener("192.168.0.110", q)
    listener.handle_datagram(_datagram())           # keepalive ack, no topic
    listener.handle_datagram(b"not json at all")
    listener.handle_datagram(b"")
    listener.handle_datagram(b'"a bare string"')
    listener.handle_datagram(b"\xff\xfe\x00")       # undecodable bytes
    assert q.pending() == 0


def test_turn_on_maps_to_the_button_the_decoder_emits_not_the_action_name():
    """TurnOn/TurnOff transmit the fan's speed code on this hardware, so
    match_line() reports 'speed'. Mapping them to 'power' would file the token
    under a key nothing ever consumes and suppression would silently no-op."""
    assert ACTION_TO_BUTTON["TurnOn"] == "speed"
    assert ACTION_TO_BUTTON["TurnOff"] == "speed"
    assert ACTION_TO_BUTTON["TurnLightOn"] == "light"


def test_unmapped_action_enqueues_nothing(caplog):
    import logging

    q = EchoTokenQueue(ttl_seconds=5.0)
    listener = BPUPListener("192.168.0.110", q)
    with caplog.at_level(logging.WARNING, logger="bond-rtl433-rf-sync"):
        listener.handle_datagram(_datagram(f"devices/{DEVICE}/actions/SomeFutureAction"))
    assert q.pending() == 0
    assert "SomeFutureAction" in caplog.text
