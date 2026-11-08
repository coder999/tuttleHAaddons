"""iFit BLE protocol for ProForm bikes advertising as I_EB, plus a TCX writer. Pure stdlib.

Frames are QZ's (github.com/cagnulein/qdomyos-zwift) *default* proformbike profile — the one
with no model flag set, which came from the 2021 ProForm capture in QZ issues #115/#131
(#115 is a Sport CX, PFEX33921.0, the bike this was built for). QZ src/devices/proformbike/proformbike.cpp:
btinit() final else branch, update() default poll cycle, characteristicChanged() final else.
"""

from __future__ import annotations

import time

SERVICE_UUID = "00001533-1412-efde-1523-785feabcd123"
WRITE_UUID = "00001534-1412-efde-1523-785feabcd123"
NOTIFY_UUID = "00001535-1412-efde-1523-785feabcd123"


def _f(hexstr: str) -> bytes:
    """Hex frame, zero-padded to 20 bytes when it is a full packet (not a 4-byte header)."""
    b = bytes.fromhex(hexstr)
    return b if len(b) == 4 else b.ljust(20, b"\0")


_I1 = _f("fe020802")
_I5 = _f("fe020a02")
INIT = [
    _I1, _f("ff08020402040204 8187"),
    _I1, _f("ff08020402040704 808b"),
    _I1, _f("ff08020402040704 8893"),
    _I5, _f("ff0a020402060206 8200008a"),
    _I5, _f("ff0a020402060206 8400008c"),
    _I1, _f("ff08020402040204 959b"),
    _f("fe022c04"),
    _f("0012020402280728 90070110cc7a3ef4b8663af8"),
    _f("0112b472461cf0be92403ceacea488764a2804e2"),
    _f("ff08f6cce0980200 00d1"),
]

# Sent one per 200 ms tick, cycling.
POLL = [
    _f("fe021903"),
    _f("0012020402150715 02000fbc907000000040 0000"),
    _f("ff070000001000085d"),
    _f("fe021703"),
    _f("0012020402130713 02000d3c9c3100004040 0080"),
    _f("ff0500800100a9"),
    _f("fe020d02"),
]

# Set-resistance commands, one per level 1-16 (index = level - 1). QZ forceResistance()
# default branch: written right after the poll frame fe 02 0d 02 (POLL[6]), its header.
# Bytes 11-12 are the target (LE, +625 per level); byte 12 is the same scale the bike reports
# back in data byte 11 (RESISTANCE below).
SET_RESISTANCE = [
    _f("ff0d020402090709020104" + f"{lo:02x}{hi:02x}00{ck:02x}")
    for lo, hi, ck in [
        (0x32, 0x02, 0x4B), (0xA3, 0x04, 0xBE), (0x14, 0x07, 0x32), (0x85, 0x09, 0xA5),
        (0xF6, 0x0B, 0x18), (0x67, 0x0E, 0x8C), (0xD8, 0x10, 0xFF), (0x49, 0x13, 0x73),
        (0xBA, 0x15, 0xE6), (0x2B, 0x18, 0x5A), (0x9C, 0x1A, 0xCD), (0x0D, 0x1D, 0x41),
        (0x7E, 0x1F, 0xB4), (0xEF, 0x21, 0x27), (0x60, 0x24, 0x9B), (0xD1, 0x26, 0x0E),
    ]
]
RESISTANCE_AFTER_POLL = 6  # index into POLL

# Byte 11 -> console resistance level (Sport CX has 16). In-between bytes appear while the
# level is changing; QZ keeps the previous level for them, so do we.
RESISTANCE = {
    0x00: 1, 0x02: 1, 0x04: 2, 0x07: 3, 0x09: 4, 0x0B: 5, 0x0C: 5, 0x0E: 6, 0x10: 7, 0x11: 7,
    0x13: 8, 0x15: 9, 0x18: 10, 0x1A: 11, 0x1D: 12, 0x1F: 13, 0x21: 14, 0x22: 14, 0x24: 15,
    0x26: 16, 0x27: 16,
}


def parse(frame: bytes, wheel_ratio: float) -> dict | None:
    """Notification -> {power, cadence, speed (km/h), resistance?}, or None if not a data frame.

    QZ derives speed as wheel_ratio * cadence (default 0.33); the bike reports none.
    """
    # QZ checks only bytes 0-3, but on the Sport CX the init burst also answers with
    # 00 12 01 04 02 <1c|1d|21|...> frames that decode as junk (e.g. 3 W, 15 rpm). Steady-state
    # data is always type 02 32 (live capture 2026-11-07), so require that too.
    if len(frame) != 20 or frame[:6] != b"\x00\x12\x01\x04\x02\x32" or frame[12:] == b"\xff" * 8:
        return None
    power = frame[12] | frame[13] << 8
    if power > 3000:  # QZ: the bike sends junk here sometimes; zero power, keep the rest
        return {"power": 0}
    out = {
        "power": power,
        "cadence": frame[18],
        "speed": round(wheel_ratio * frame[18], 2),
        # The console's own odometer, meters, uint16 (wraps at ~40.7 mi). Not in QZ; matched
        # the console's distance readout live 2026-11-07 (8.37 mi) and 2026-11-08 (3.5 mi).
        "odometer": frame[14] | frame[15] << 8,
    }
    if frame[11] in RESISTANCE:
        out["resistance"] = RESISTANCE[frame[11]]
    return out


def odometer_step(last: int, now: int) -> int:
    """Meters ridden between two odometer readings. A drop means the console restarted its
    count (new workout), so count from 0. ponytail: a true uint16 wrap (40.7 mi into one
    console session) undercounts once."""
    return now - last if now >= last else now


def tcx(samples: list[tuple[float, int, int, float, float]]) -> str:
    """samples: [(epoch_s, watts, cadence, speed_kmh, ride_distance_m)], ~1 s apart, gaps
    allowed -> TCX with distance, power and cadence."""

    def ts(t: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

    joules = 0.0
    prev = samples[0][0]
    pts = []
    for t, watts, cad, kmh, dist in samples:
        dt = min(t - prev, 5)  # a dropout gap shouldn't count as effort at the last wattage
        prev = t
        joules += watts * dt
        pts.append(
            f"<Trackpoint><Time>{ts(t)}</Time><DistanceMeters>{dist:.1f}</DistanceMeters>"
            f"<Cadence>{min(int(cad), 254)}</Cadence><Extensions><ns3:TPX>"
            f"<ns3:Speed>{kmh / 3.6:.2f}</ns3:Speed><ns3:Watts>{int(watts)}</ns3:Watts>"
            f"</ns3:TPX></Extensions></Trackpoint>"
        )
    start = ts(samples[0][0])
    secs = samples[-1][0] - samples[0][0]
    # kcal ~= kJ of work for cycling (~24% efficiency cancels the 4.184 kJ/kcal).
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"'
        ' xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">'
        f'<Activities><Activity Sport="Biking"><Id>{start}</Id><Lap StartTime="{start}">'
        f"<TotalTimeSeconds>{secs:.0f}</TotalTimeSeconds><DistanceMeters>{dist:.1f}</DistanceMeters>"
        f"<Calories>{joules / 1000:.0f}</Calories><Intensity>Active</Intensity>"
        f"<TriggerMethod>Manual</TriggerMethod><Track>{''.join(pts)}</Track></Lap>"
        "</Activity></Activities></TrainingCenterDatabase>\n"
    )
