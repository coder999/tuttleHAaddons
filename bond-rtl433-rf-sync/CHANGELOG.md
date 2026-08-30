# Changelog

## 1.0.8

- **Fixed a deadlock that could freeze the whole add-on silently: the
  restart path called `proc.terminate()` then `proc.wait()` with no
  timeout.** If `rtl_433` didn't actually exit in response to SIGTERM —
  which happens when it's blocked on a dead/stale `rtl_tcp` connection —
  `proc.wait()` blocked forever. Since that's the *only* code path that
  spawns a fresh `rtl_433` and logs anything, the entire manager froze:
  no more restarts, no more log lines, nothing, indefinitely.

  Confirmed live, 2026-08-29: the add-on went completely silent for 22+
  hours (last log line 08-28 21:03), missing wall-switch presses
  including a dining-room light turn-on that never reached Bond/HomeKit.
  On the pi side, `rtl_tcp`'s socket to the add-on was still `ESTAB`
  with **Send-Q actively growing** (44944 → 144856 bytes in 3s) — the pi
  kept streaming SDR data into a connection nobody on the add-on side
  was reading, the exact stuck-consumer signature you'd expect from a
  process wedged in `proc.wait()`. A manual add-on restart recovered it
  immediately.

  **Fix:** `proc.wait()` now takes a bounded `terminate_timeout_seconds`
  (default 5s); if the process hasn't exited by then, escalate to
  `proc.kill()`. Regression test drives a fake subprocess that installs
  `SIGTERM, SIG_IGN` and confirms the manager still recovers (kills it,
  spawns a fresh one) instead of hanging.

## 1.0.7

- **Fixed a critical, self-inflicted bug in the 1.0.5/1.0.6 liveness
  probe: it opened a second TCP connection to the same rtl_tcp host:port
  that `rtl_433`'s real data connection already used.** `rtl_tcp` only
  ever accepts one client. That second connection could never cleanly
  succeed while the real one was healthy — it just hung until timeout
  every single check, meaning the probe was guaranteed to eventually
  (mis)report a perfectly healthy source as unreachable and force a
  restart, over and over. Each forced restart made the SDR re-tune,
  which generated noise the flex decoder sometimes misread as a real
  wall-switch press.

  Confirmed live, 2026-08-19: after a manual add-on restart, three
  spurious `livingroom/light` Bond corrections fired within about two
  minutes with no real button press — the user's actual, concrete bug
  report ("turning the light off in Bond, then its state flips back to
  on a few seconds later"). Reproducing the probe's own connection
  attempt by hand against the live, healthy system confirmed the hang
  directly: it timed out after the full probe timeout with `rtl_433`'s
  real connection sitting right there, established and working. Also
  found direct evidence of a resulting resource leak — abandoned
  `CLOSE-WAIT` connections left on `rtl_tcp`'s side from failed probe
  attempts.

  This also very plausibly accounts for a chunk of the "pi network
  degraded" restart-loop chaos earlier the same day (2026-08-18/19,
  1.0.5's own incident writeup) — that diagnosis wasn't wrong that
  *something* was broken, but the probe's own architecture meant it
  would have kept forcing restarts even once the pi's network had fully
  recovered, since it could never get a second connection slot while
  `rtl_433` held the only one.

  **Fix: check host reachability via ICMP ping instead**, which never
  touches `rtl_tcp`'s one connection slot at all and so can never compete
  with the real client. `default_liveness_probe()` now shells out to the
  system `ping` binary rather than opening a socket;
  `rtl433_source_port` is no longer used for liveness checking at all
  (still used, as always, for the actual `rtl_433 -d rtl_tcp:host:port`
  invocation). Added `iputils-ping` to the Dockerfile. Tests mock
  `subprocess.run` for deterministic pass/fail cases (matching this
  repo's existing precedent for mocking `subprocess.Popen`), plus one
  real, unmocked smoke test against `127.0.0.1` so the feature is proven
  against the actual `ping` binary at least once.

  **Lesson for next time:** an active liveness check must never contend
  for the exact same limited resource (here, `rtl_tcp`'s single client
  slot) that the thing it's protecting also needs — that guarantees the
  check interferes with the very system it's meant to monitor.

## 1.0.6

- **Code review follow-up on the 1.0.5 liveness probe** (automated
  review, both Important-severity items plus three of four Minor items;
  the fourth - pre-existing fixed 5s restart backoff during an extended
  fast-refusing-connection outage - was left as-is, since it's unchanged
  from 4059140/fa7a83b, not a regression, and the reviewer confirmed the
  timing is fine for the actual hung-connection failure mode this feature
  targets):
  - **`_run_liveness_prober` no longer dies silently on an unexpected
    probe exception.** Previously, any exception other than `OSError`
    from the (possibly test-injected) probe function killed the daemon
    thread on the spot, permanently and silently falling back to the
    6-hour stale-timeout for the rest of the process's life - the exact
    failure mode this feature exists to move away from. Now caught,
    logged, and retried next interval; treated as "couldn't confirm
    reachability", not "confirmed unreachable", so it doesn't itself
    force a restart.
  - **Added a real end-to-end test for the local-mode no-op path**
    through `RFSourceManager`'s actual default wiring (previously only
    tested `default_liveness_probe()` in isolation and inferred the
    manager-level behavior transitively).
  - **`rtl433_liveness_probe_interval_seconds` now has an enforced
    minimum of 5s** (previously only `> 0`), closing off a reproduced
    livelock at pathologically small intervals (e.g. 1ms) where the
    prober kills a freshly-(re)spawned `rtl_433` before it can ever
    produce output.
  - **New `rtl433_liveness_probe_timeout_seconds`** (default 10s) makes
    the probe's own connect timeout a proper config option, following the
    same parse/default/validate/schema/README pattern as every other
    tunable, instead of being a constructor-only default.
  - **The exit-path log line now distinguishes a probe-triggered restart
    from a genuine crash** (`"...exited (code=...) after a liveness probe
    failure, restarting..."`), so a reader skimming only that line - not
    the prober's separate "forcing restart" line just before it - can
    still tell the two apart.

## 1.0.5

- **Added an active liveness probe for `rtl_tcp` mode; demoted the
  stale-output watchdog to a last-resort fallback.** Real-world follow-up
  to 1.0.3/1.0.4 (2026-08-19): overnight, the log showed "no rtl_433
  output for 3600.0s, presumed hung, restarting" — but nobody had touched
  a wall switch, so nothing was actually wrong. RF silence and "the
  connection is dead" are two different things, and stdout inactivity
  alone can't tell them apart in a household that can legitimately go
  hours between button presses.
  - New: `rtl433_liveness_probe_interval_seconds` (default `60`). In
    `rtl_tcp` mode, a background thread directly probes the source
    host:port (plain TCP connect-and-close) on this interval, independent
    of RF activity, and forces a restart if it fails. This is now the
    primary detector for a lost/hung `rtl_tcp` connection - it reacts in
    roughly one interval and can't be fooled by a quiet night. No-op in
    `local` mode (nothing to probe).
  - `rtl433_stale_timeout_seconds` default raised `3600` → `21600` (1 hour
    → 6 hours), repositioning it as a backstop behind the liveness probe
    rather than the primary mechanism, and validated `> 0` (mirrors the
    same guard added for the probe interval).
  - `default_liveness_probe()`/the manager's new `liveness_probe`
    constructor param follow the same dependency-injection pattern as the
    existing `command` override, so the probe is real-socket-tested
    (`test_default_liveness_probe_true/false_when_host_*reachable`, a
    real local TCP server, no mocking) while `RFSourceManager`'s own tests
    inject a fake probe function and stay fast/deterministic.
  - Also applied the two Minor cleanups from the 1.0.3 code review: the
    unenforced `# type: ignore[misc]` (no type-checker configured in this
    repo) and the redundant quoted-string type annotations (already
    covered by `from __future__ import annotations`) are gone.

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
