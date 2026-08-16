from app.config import CodeTableEntry
from app.matcher import MatchedEvent, decode_hex, match_line

CODE_TABLE = (
    CodeTableEntry(room="livingroom", button="speed", stable_id=0x1FF),
    CodeTableEntry(room="livingroom", button="light", stable_id=0x1F9),
    CodeTableEntry(room="livingroom", button="power", stable_id=0x1D9),
    CodeTableEntry(room="bedroom", button="speed", stable_id=0x2FF),
)


def test_decode_hex_splits_stable_id_and_counter():
    # 0x1ff0 >> 3 & 0b11 == 0b10 == counter 2; 0x1ff0 >> 5 == 0xff... use a real
    # example: code 0x3fe0 -> counter = (0x3fe0 >> 3) & 0b11, stable_id = 0x3fe0 >> 5
    stable_id, counter = decode_hex("3fe0")
    assert stable_id == (0x3FE0 >> 5)
    assert counter == ((0x3FE0 >> 3) & 0b11)


def test_match_line_speed_button_maps_counter_to_percentage():
    # stable_id 0x1ff, counter 0 (=33%): code = (0x1ff << 5) | (0 << 3) = 0x3fe0
    line = "codes     : {25}3fe0"
    event = match_line(line, CODE_TABLE)
    assert event == MatchedEvent(room="livingroom", button="speed", percentage=33)


def test_match_line_speed_button_counter_3_is_off():
    # counter 3: code = (0x1ff << 5) | (3 << 3) = 0x3fe0 | 0x18 = 0x3ff8
    line = "codes     : {25}3ff8"
    event = match_line(line, CODE_TABLE)
    assert event == MatchedEvent(room="livingroom", button="speed", percentage=0)


def test_match_line_power_button_has_no_percentage():
    # stable_id 0x1d9: code = 0x1d9 << 5 = 0x3b20
    line = "codes     : {25}3b20"
    event = match_line(line, CODE_TABLE)
    assert event == MatchedEvent(room="livingroom", button="power", percentage=None)


def test_match_line_unknown_stable_id_returns_none():
    line = "codes     : {25}ffffff"
    assert match_line(line, CODE_TABLE) is None


def test_match_line_non_matching_format_returns_none():
    assert match_line("some unrelated rtl_433 output", CODE_TABLE) is None
    assert match_line("", CODE_TABLE) is None
