# Changelog

## 1.0.1

- **Fixed a real correctness bug in the power button's light handling.**
  The power button is a master toggle for the whole fixture, driven by
  the fan's own on/off state — pressing it turns everything on (fan to
  last speed, light on) unless both are already on, in which case it
  turns everything off. Light's own prior state never matters. The
  previous logic independently toggled light based on light's own prior
  state, which was wrong for the two mixed cases (fan on/light off, and
  fan off/light on) — confirmed against real wall-switch behavior
  2026-08-16.

## 1.0.0

- Live-validated against all 9 real wall-switch button combinations (3
  rooms × power/light/speed), zero errors, zero double-RF responses.
  Cut over from the previous MQTT + Home-Assistant-automation pipeline
  (see `rtl_433_fan`'s `FAN_WALLSWITCH_SYNC.md`) — this add-on is now the
  sole thing correcting Bond's believed fan/light state from wall-switch
  RF presses.

## 0.2.1

- Fixed Docker packaging: the built image flattened `app/`'s contents
  directly into `/app/`, breaking the codebase's `from app.X import ...`
  absolute imports (`ModuleNotFoundError: No module named 'app'` at
  startup). `app/` is now copied to `/app/app/` and run as a proper module
  (`python3 -m app.main`), matching the package layout the code expects.

## 0.2.0

- Decodes Ashby Park ceiling fan wall-switch RF presses (speed/power/light)
  via `rtl_433` and corrects Bond Bridge's believed device state through its
  belief-only local API — no RF is ever transmitted by this add-on.
- Supports either a local USB SDR dongle or a remote `rtl_tcp` source.
- Debounces repeated RF transmissions from a single button press before
  issuing a Bond correction.
- Restarts `rtl_433` with backoff on unexpected exit or spawn failure, and
  stops the child process cleanly on add-on shutdown/restart.
- Read-only ingress panel showing recent decoded events and current
  per-room believed state; `/healthz` endpoint for liveness checks.
- Fails loudly at startup on invalid configuration (bad `rtl433_source`,
  empty/orphaned `code_table` or `room_devices`, invalid `max_speed`, etc.).
- `dry_run` mode for verifying decoded events without sending Bond calls.

## 0.1.0

- Initial add-on skeleton.
