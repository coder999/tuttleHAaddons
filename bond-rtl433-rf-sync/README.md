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
- `rtl433_stale_timeout_seconds` — how long `rtl_433` can go without
  producing any output before it's presumed hung and killed/restarted.
  Defaults to `3600` (1 hour). This is a watchdog for a real incident
  (2026-08-17/18): when the `rtl_433 -d rtl_tcp:...` source lost its
  connection to a remote `rtl_tcp` server (the source pi's WiFi driver
  hung), the `rtl_433` process itself never exited or errored — it just
  went silent — so the existing exit-triggered restart never fired and the
  add-on sat blocked for over a day with no output and no error logged.
  This is *not* a signal of normal RF quiet periods (real button presses
  can be hours apart), so keep it generous; lower it only if you need
  faster recovery and can tolerate more frequent proactive reconnects.
- `code_table` — maps each switch's decoded RF `stable_id` to a room/button.
- `room_devices` — maps each room to its Bond `device_id` and `max_speed`.
- `debounce_seconds` — quiet period (in seconds) after the last matching RF
  press before the corresponding Bond correction is sent, so repeated RF
  transmissions from a single physical button press coalesce into one call.
  Defaults to `3.0`.
- `dry_run` — when true, logs the Bond call that would be made without
  sending it.

## Power button behavior

The physical power button is **not** an independent per-entity toggle of
fan and light. It's a master toggle for the whole fixture, driven entirely
by the fan's own on/off state:

- If the fan and light are **both already on**, pressing power turns
  **both off**.
- Otherwise (fan off, regardless of light's state), pressing power turns
  **both on** — fan resumes its last known non-zero speed, light turns on.

Light's own prior state never matters — it always ends up matching the
fan's *new* resulting state. This was confirmed against real hardware
(both mixed cases: fan-on/light-off and fan-off/light-on) and is what
`build_power_toggle_body` in `app/bond_client.py` implements.

## Status

**Live and in production (2026-08-16, v1.0.1).** All 9 wall-switch button
combinations (3 rooms × power/light/speed) validated live against real
Bond corrections with zero errors and zero double-RF responses, including
both mixed power-button states described above. This add-on is now the
sole thing correcting Bond's believed fan/light state from wall-switch RF
presses — the original MQTT + Home-Assistant-automation pipeline (see the
sibling `rtl_433_fan` project's `FAN_WALLSWITCH_SYNC.md`) has been
retired, including the automations, `input_number` helpers, and their
entity registry entries. See `CHANGELOG.md` for the version history, or
this repo's git tags (`bond-rtl433-rf-sync-1.0.0`, `-1.0.1`) for the full
design/implementation/validation record.

**2026-08-17/18 incident:** the `rtl_tcp` source pi's WiFi driver hung,
silently killing this add-on's data feed for over a day with nothing
logged — see `rtl433_stale_timeout_seconds` above and `CHANGELOG.md`'s
`1.0.3` entry for the watchdog fix.
