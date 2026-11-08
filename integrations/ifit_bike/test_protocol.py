"""python3 test_protocol.py -- parser + TCX checks; no HA needed."""
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent / "custom_components/ifit_bike"))
import protocol as p


def frame(res=0x13, watts=150, cad=80, tail=None):
    b = bytearray(b"\x00\x12\x01\x04\x02\x32" + bytes(14))
    b[11], b[12], b[13], b[18] = res, watts & 0xFF, watts >> 8, cad
    if tail:
        b[12:] = tail
    return bytes(b)


assert p.parse(frame(), 0.33) == {"power": 150, "cadence": 80, "speed": 26.4, "resistance": 8}
assert p.parse(frame(res=0x14), 0.33).get("resistance") is None  # mid-change byte: keep previous
assert p.parse(frame(watts=3001), 0.33) == {"power": 0}
assert p.parse(frame(tail=b"\xff" * 8), 0.33) is None
assert p.parse(b"\x01" + frame()[1:], 0.33) is None
assert p.parse(frame()[:19], 0.33) is None
# init-burst response from the live capture: same header, type 1d -> not data
assert p.parse(bytes.fromhex("00120104021d071d8102530103000000000000 0fbc".replace(" ", "")), 0.33) is None
# steady-state frame from the live capture: 262 W, 59 rpm, resistance 11
assert p.parse(bytes.fromhex("0012010402320732 0202da1a0601af3400003b00".replace(" ", "")), 0.33) == {
    "power": 262, "cadence": 59, "speed": 19.47, "resistance": 11}
assert all(len(f) in (4, 20) for f in p.INIT + p.POLL + p.SET_RESISTANCE)
# Set and read use one scale: each command's level byte decodes back to its own level.
assert [p.RESISTANCE[f[12]] for f in p.SET_RESISTANCE] == list(range(1, 17))
assert p.POLL[p.RESISTANCE_AFTER_POLL] == bytes.fromhex("fe020d02")

# 10 min at 200 W, 90 rpm, 30 km/h, 1 Hz
t0 = 1_762_500_000
xml = p.tcx([(t0 + i, 200, 90, 30.0) for i in range(601)])
ns = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
      "x": "http://www.garmin.com/xmlschemas/ActivityExtension/v2"}
root = ET.fromstring(xml.encode())
pts = root.findall(".//t:Trackpoint", ns)
lap = root.find(".//t:Lap", ns)
assert len(pts) == 601
assert lap.find("t:TotalTimeSeconds", ns).text == "600"
assert abs(float(lap.find("t:DistanceMeters", ns).text) - 5000) < 1  # 30 km/h * 10 min
assert lap.find("t:Calories", ns).text == "120"  # 200 W * 600 s = 120 kJ
assert pts[5].find(".//x:Watts", ns).text == "200"
assert pts[5].find("t:Cadence", ns).text == "90"
print("ok")
