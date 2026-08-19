# Changelog

## 1.0.4

- **Code review follow-up on the 1.0.3 staleness watchdog** (automated
  review, both Important-severity items):
  - `rtl433_stale_timeout_seconds` now rejects `<= 0` at config-parse time
    (`ConfigError`). A non-positive value made `queue.Queue.get(timeout=...)`
    effectively non-blocking, spinning the restart loop and continuously
    killing/respawning `rtl_433` as fast as `restart_backoff_seconds`
    allowed.
  - Added a regression test
    (`test_lines_stop_returns_promptly_during_long_stale_wait`) for the
    property the watchdog's safety depends on most: `stop()` (called from
    another thread, as it is in production via the SIGTERM handler) must
    interrupt an in-progress stale-timeout wait immediately, not block
    until the timeout — potentially a full hour at the default — actually
    elapses. This was manually verified during 1.0.3's review but hadn't
    been captured as an automated test; confirmed the new test actually
    catches a regression by running it against a deliberately broken
    `stop()` (one that no longer calls `proc.terminate()`), where it hangs
    instead of returning in ~0.2s.

## 1.0.3

- **Added a staleness watchdog for the `rtl_433` subprocess.** Fixes a real
  incident (2026-08-17/18): when the `rtl_tcp` source pi's WiFi driver hung,
  `rtl_433 -d rtl_tcp:...` lost its connection but never exited or errored —
  it just went silent — so the existing exit-triggered restart never fired.
  The add-on sat blocked on a dead subprocess for over a day with no output
  and nothing logged, until it was manually restarted. `rtl_433`'s stdout is
  now read on a background thread through a queue with a timeout
  (`rtl433_stale_timeout_seconds`, default 3600s/1 hour); if nothing arrives
  within that window while the process is still nominally running, it's
  killed and restarted like any other failure. Default is deliberately
  generous since real button presses can legitimately be hours apart, so
  silence alone isn't a reliable "connection is dead" signal — this is a
  self-healing safety net, not a fast-failover mechanism.

## 1.0.2

- Added a custom add-on icon (`icon.svg`/`icon.png`) — a fan pinwheel with
  RF signal arcs sweeping toward it — replacing the default blank icon in
  the Add-on Store. Sidebar `panel_icon` changed from `mdi:fan-alert` to
  `mdi:radio-tower`, since this add-on doesn't touch the fan directly and
  `radio-tower` better reflects what it actually does (listens to RF).

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
