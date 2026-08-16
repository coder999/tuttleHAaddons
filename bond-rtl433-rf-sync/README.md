# Bond-rtl_433 RF Sync

Corrects Bond Bridge's believed fan/light state from Ashby Park ceiling fan
wall-switch RF presses, without transmitting anything to the physical
devices — replaces an MQTT + Home-Assistant-automation pipeline with a
single self-contained add-on.

## Configuration

- `bond_host` / `bond_token` — Bond Bridge local API address and token.
- `rtl433_source` — `local` (USB dongle attached to this host, pick it in
  the Hardware tab) or `rtl_tcp` (point at a remote `rtl_tcp` server, e.g.
  a Raspberry Pi elsewhere on the network).
- `rtl433_frequency` — receive frequency in Hz passed to `rtl_433 -f`.
  Defaults to `304250000` (304.25 MHz), matching the Ashby Park wall
  switches; change only if your switches transmit on a different band.
- `rtl433_sample_rate` — SDR sample rate in Hz passed to `rtl_433 -s`.
  Defaults to `2048000`; rarely needs changing.
- `rtl433_gain` — SDR tuner gain in dB passed to `rtl_433 -g`. Defaults to
  `49.6`; raise or lower it if presses are being missed or the receiver is
  overloaded.
- `code_table` — maps each switch's decoded RF `stable_id` to a room/button.
- `room_devices` — maps each room to its Bond `device_id` and `max_speed`.
- `debounce_seconds` — quiet period (in seconds) after the last matching RF
  press before the corresponding Bond correction is sent, so repeated RF
  transmissions from a single physical button press coalesce into one call.
  Defaults to `3.0`.
- `dry_run` — when true, logs the Bond call that would be made without
  sending it.

## Status

**Live and in production (2026-08-16).** All 9 wall-switch button
combinations (3 rooms × power/light/speed) validated live against real
Bond corrections with zero errors and zero double-RF responses. This
add-on is now the sole thing correcting Bond's believed fan/light state
from wall-switch RF presses — the original MQTT + Home-Assistant-automation
pipeline (see the sibling `rtl_433_fan` project's `FAN_WALLSWITCH_SYNC.md`)
has been retired, including the automations, `input_number` helpers, and
their entity registry entries. See `CHANGELOG.md` for the version history,
or this repo's git history (tag `bond-rtl433-rf-sync-1.0.0`) for the full
design/implementation/validation record.
