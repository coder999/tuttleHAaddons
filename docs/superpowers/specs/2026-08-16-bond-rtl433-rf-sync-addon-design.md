# Bond Wall-Switch Sync Add-on — Design

**Status:** approved by user 2026-08-16, ready for implementation planning.

## Goal

Replace the current Home-Assistant-centric pipeline for keeping Bond Bridge's
believed fan/light state in sync with physical RF wall-switch presses (currently:
Pi's `rtl_433` + `fan_wallswitch_bridge.py` → MQTT → 9 HA automations → `rest_command`
→ Bond's local API) with a single self-contained HA add-on that owns the whole
pipeline end to end: decode RF → match → debounce → correct Bond's belief. No MQTT,
no HA automations, no `rest_command`. Home Assistant's Bond integration becomes a
pure passive consumer of Bond's state, same as any other entity.

This is a **simplification, not a new capability** — the working, live-validated
system built earlier today (2026-08-16, see `rtl_433_fan/FAN_WALLSWITCH_SYNC.md`) is
the fallback throughout development and stays untouched until this add-on is proven.

## Background this design depends on (established earlier today, in `rtl_433_fan`)

- Bond's RF protocol is bit-identical to the wall switches' own RF — any *real* Bond
  control command sent in response to a detected wall-switch press double-transmits
  and either loops or undoes the user's press. **Only Bond's belief-only
  `PATCH /v2/devices/<id>/state` local API is safe to call from an automated
  response** — this constraint carries over unchanged into the add-on design.
- The physical fan fixtures have their own hardware-level last-speed memory
  (confirmed live via a real Bond `TurnOn`/`TurnOff` test that never touched the wall
  switch) — this only affects what the add-on needs to track for *Bond's own belief*
  accuracy on power-on, not for physical correctness, which the hardware already
  handles itself.
- `rtl_433` is a standard apt package (`rtl-433`) on both Debian and Raspbian, and
  natively supports `-d rtl_tcp:host:port` as an input source alongside local USB
  devices — confirmed via the Pi's existing install and `rtl_433 -h` output.
- The existing third-party `rtl433-next` add-on (already installed, currently
  `state: error`, on this HA instance) was evaluated and rejected as a decode-layer
  dependency: its custom-conf-template mechanism *can* point at a remote `rtl_tcp`
  source, but its output is MQTT-first (fighting the "drop MQTT" decision), it has no
  knowledge of this project's fan-specific flex decoder or matching logic (which would
  need to be written regardless), and it's an external dependency currently broken on
  this host. Its `usb: true` config flag (Supervisor's Hardware-tab device picker) is
  worth reusing directly in this add-on's own manifest — that flag isn't exclusive to
  their add-on.

## Architecture

Single Python service, packaged as a standard HA add-on matching this repo's existing
`markdown-wiki` conventions (`python:3.12-slim` base, not the heavier official
s6-overlay/bashio base images — this is one process, not several).

```
RF Source Manager ──spawns──> rtl_433 subprocess (-F json, -X <flex decoder>)
  (local USB [usb: true]              │
   or rtl_tcp://<pi-ip>:1234)         │ JSON lines (stdout)
                                       ▼
Decoder/Matcher ──> match against configurable code_table
  (mirrors fan_wallswitch_bridge.py's matching logic)
                                       │
                                       ▼
Debouncer (per room+button quiet-period coalescing, same pattern as today)
                                       │
                                       ▼
Bond Client ──PATCH .../state──> Bond Bridge (belief-only, never a real action)
  (reads Last-Speed Store for power-on resume target)
                    │                                │
                    ▼                                ▼
    Last-Speed Store (/data/*.json,        Event Log (in-memory ring
    replaces input_number helpers)         buffer, feeds ingress panel)

Ingress Panel (Flask + gunicorn) ──> read-only: event history +
                                      current per-room believed state

Structured logging throughout ──> Supervisor's Log tab
```

The Pi's role shrinks to running bare `rtl_tcp` (once this add-on is validated,
retiring `fan_wallswitch_bridge.py` and `rtl433-mqtt.service`).

## Components

- **RF Source Manager** — spawns/supervises the `rtl_433` subprocess, restarts with
  backoff on crash or SDR disconnect (local unplug or remote `rtl_tcp` drop), streams
  JSON lines from stdout.
- **Decoder/Matcher** — parses each JSON event, matches against `code_table`.
- **Debouncer** — coalesces repeated raw "seen" events into one logical "firing" event
  per `(room, button)` key within a quiet period, same as today's `fan_wallswitch_bridge.py`.
- **Last-Speed Store** — small persisted JSON file(s) under `/data`, one value per room,
  functionally replacing the `input_number.<room>_last_fan_speed` HA helpers.
- **Bond Client** — wraps `GET`/`PATCH .../state` calls (belief-only, never a real
  transmit-type action), holds timeout/retry logic.
- **Event Log** — in-memory ring buffer (recent N events) + current per-room believed
  state snapshot, feeds the ingress panel.
- **Ingress Panel** — read-only Flask+gunicorn web UI (event history table, per-room
  state), matching `markdown-wiki`'s pattern. No config editing in v1 — Supervisor's
  standard options UI handles that.

## Config schema (Supervisor options)

- `bond_host`, `bond_token` (password-type field)
- `rtl433_source`: `local` | `rtl_tcp` selector
- `rtl433_source_host`, `rtl433_source_port` — only used in `rtl_tcp` mode
- `rtl433_frequency`, `rtl433_sample_rate`, `rtl433_gain` — default to today's known-good
  values (304.25MHz / 2048000 / 49.6) but configurable, since other households' switches
  will differ
- `code_table` — list of `{room, button, match, target_percent?, bond_device_id}` entries,
  a nested list in the addon schema, editable via Supervisor's standard options UI
- `debounce_seconds` — defaults to today's quiet-period value
- Local mode (`rtl433_source: local`) sets `usb: true` in `config.json` for Supervisor's
  Hardware-tab device picker.

## Data flow (worked example: living room speed → 66%)

1. `rtl_433` decodes RF, emits a JSON line.
2. RF Source Manager reads it, hands to Decoder/Matcher.
3. Matcher finds `{room: livingroom, button: speed, target_percent: 66}`.
4. Debouncer coalesces repeated raw events within the quiet period into one logical event.
5. On firing: Bond Client computes the native speed step
   (`ceil(target_percent/100 * max_speed)`) and `PATCH`es Bond's local API —
   `{"power":1,"speed":2}` for that room's `device_id`. No RF transmitted.
6. Last-Speed Store updates `livingroom → 66`.
7. Event logged (raw code, match, Bond call + result) → ingress panel + Supervisor log.

Power/light events follow the same shape but read current believed state first (via
`GET .../state` or a maintained in-memory mirror) to decide toggle direction, instead
of carrying an explicit target — same logic today's HA automations implement.

## Error handling

- `rtl_433` subprocess crash / SDR disconnect (local unplug, remote `rtl_tcp` drop on
  Pi reboot or network blip): restart with backoff, log clearly.
- Bond Bridge unreachable/timeout on a `PATCH` call: log the failure (room/button/body
  attempted), skip it, don't crash the add-on or retry aggressively — a missed
  correction self-heals on the next real event (same behavior observed live today with
  the stale bedroom helper).
- Invalid `code_table` / a `bond_device_id` that doesn't respond at startup: validate
  at startup, fail loudly in the log.
- Debounce timers are keyed per `(room, button)` — no cross-room interference.

## Testing & rollout

The existing HA-automation-based system stays running, untouched, throughout — it's
the safety net until the add-on is proven, exactly like every other change made in
this project so far.

1. **Unit tests, no hardware:** capture real `rtl_433` JSON output from today's Pi as
   fixtures; test matcher/debouncer/Bond-call-body-construction logic against them
   offline.
2. **Dry-run mode:** a config flag that logs the Bond call the add-on *would* make
   without sending it — validates decode/match accuracy against real presses before
   the add-on ever touches Bond.
3. **Live validation, one room at a time:** press each button, confirm the add-on's log
   shows correct match → Bond call → success, confirm Bond's belief matches physical
   reality, confirm no double RF response. Old HA automations run in parallel
   throughout (harmless redundant belief-only writes, both are last-write-wins safe).
4. **Cutover:** only after all 9 combinations are validated live: disable the 9 HA
   automations, flip the Pi from `rtl433-mqtt.service` to plain `rtl_tcp`, retire
   `fan_wallswitch_bridge.py` and the `input_number` helpers.

## Open questions / risks for the implementation plan to address

- **`rtl_tcp` multi-client support on the Pi:** the Pi already runs a separate
  `rtl-tcp.service` for the unrelated gas-meter project, currently mutually exclusive
  with `rtl433-mqtt.service` via `Conflicts=` (only one process can own the physical
  SDR dongle at a time). Whether this add-on's `rtl_433 -d rtl_tcp:...` client can
  share a *single* `rtl_tcp` server concurrently with the gas-meter project's own
  client needs verification — `rtl_tcp` may only support one active reader. If not,
  the Pi-side `Conflicts=`-style mutual exclusion pattern needs to carry forward in
  some form.
- **USB passthrough specifics for local mode:** `usb: true` is the right Supervisor
  flag, but exact container permissions for RTL-SDR (a generic USB device, not serial)
  should be validated against a real local dongle during implementation — some
  community add-ons additionally need explicit `udev: true` or device cgroup mappings.
- **Add-on name/slug:** working name "Bond Wall-Switch Sync" — easy to change, not
  load-bearing on any of the above.
- **`code_table` schema depth:** HA add-on option schemas support nested lists, but
  the exact nesting (list-of-objects with an optional field for `target_percent`)
  should be validated against Supervisor's schema DSL early, since its expressiveness
  has edge cases.
