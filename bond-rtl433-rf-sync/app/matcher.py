from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import CodeTableEntry

SPEED_COUNTER_TO_PERCENTAGE = {0: 33, 1: 66, 2: 100, 3: 0}

LINE_RE = re.compile(r"codes\s*:\s*\{25\}([0-9a-f]+)$")


@dataclass(frozen=True)
class MatchedEvent:
    room: str
    button: str
    percentage: int | None


def decode_hex(hex_code: str) -> tuple[int, int]:
    code_int = int(hex_code, 16)
    counter = (code_int >> 3) & 0b11
    stable_id = code_int >> 5
    return stable_id, counter


def decode_only(line: str) -> tuple[str, int] | None:
    """The (hex stable_id, counter) of an RF line, regardless of whether any
    code_table entry claims it; None if the line carries no RF code at all.

    Exists so an unmatched press can still be logged. Configuring code_table
    requires knowing your own switches' stable_ids, and they can only be
    learned off the air -- if unmatched transmissions were silent there would
    be no way to discover them.
    """
    m = LINE_RE.search(line.rstrip())
    if not m:
        return None
    stable_id, counter = decode_hex(m.group(1))
    return f"{stable_id:x}", counter


def match_line(
    line: str, code_table: tuple[CodeTableEntry, ...]
) -> MatchedEvent | None:
    m = LINE_RE.search(line.rstrip())
    if not m:
        return None
    stable_id, counter = decode_hex(m.group(1))
    for entry in code_table:
        if entry.stable_id == stable_id:
            percentage = (
                SPEED_COUNTER_TO_PERCENTAGE[counter] if entry.button == "speed" else None
            )
            return MatchedEvent(room=entry.room, button=entry.button, percentage=percentage)
    return None
