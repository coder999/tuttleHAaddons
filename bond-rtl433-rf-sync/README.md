# Bond-rtl_433 RF Sync

Corrects Bond Bridge's believed fan/light state from ceiling fan wall-switch
RF presses, without transmitting anything to the physical devices — replaces
an MQTT + Home-Assistant-automation pipeline with a single self-contained
add-on. Developed against Ashby Park ceiling fans, but nothing is specific to
them beyond the default `rtl433_frequency`.

> **The shipped `bond_host`, `code_table` and `room_devices` are examples, not
> working defaults.** They describe a made-up house so the shape of each option
> is visible in the add-on's Configuration tab. `bond_host` defaults to
> `192.0.2.10`, from RFC 5737's documentation range, so an unconfigured add-on
> cannot reach a real device on your network. See
> [Finding your own values](#finding-your-own-values).

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
- `rtl433_liveness_probe_interval_seconds` — how often, in `rtl_tcp` mode
  only, to directly check that the source *host* is still reachable (an
  ICMP ping — **not** a TCP connection to the source port; see the
  important note below), independent of RF activity. Defaults to `60`,
  minimum `5` (enforced — anything shorter risks killing a
  freshly-(re)spawned `rtl_433` before it has any real chance to
  reconnect, livelocking the restart loop). This is the *primary*
  detector for a lost/hung connection to a remote `rtl_tcp` source (e.g.
  the source pi's WiFi driver hanging) — it reacts within roughly one
  interval, and unlike stdout silence it can't be confused with a normal
  quiet period. No-op in `local` mode (nothing to probe). A probe that
  raises instead of returning true/false is treated as "couldn't confirm
  reachability" (logged, retried next interval) rather than "confirmed
  unreachable" — it does not by itself force a restart.

  **Why ping, not a TCP connection to the source port (2026-08-19
  incident):** `rtl_tcp` only accepts one client. An earlier version of
  this probe opened a *second* TCP connection to the exact host:port
  `rtl_433`'s real data connection already used — but that second
  connection could never cleanly succeed while the real one was healthy;
  it just hung until timeout. That falsely marked a perfectly healthy
  source as unreachable, forced a restart, and the resulting SDR re-tune
  generated noise that got misdecoded as fake wall-switch presses
  (confirmed live: a spurious `livingroom/light` Bond correction directly
  followed a probe-forced restart with no real button press). Pinging the
  host instead never touches `rtl_tcp`'s one connection slot, so it can't
  compete with the real client. Requires `iputils-ping` in the container
  (included in the Dockerfile).
- `rtl433_liveness_probe_timeout_seconds` — the probe's own ping
  timeout. Defaults to `10`. Rarely needs changing.
- `rtl433_stale_timeout_seconds` — last-resort safety net: how long
  `rtl_433` can go without producing *any* output before it's presumed
  hung and killed/restarted anyway, even if the liveness probe (when
  applicable) hasn't caught anything. Defaults to `21600` (6 hours) —
  deliberately long, since real wall-switch presses can legitimately be
  hours apart and this has no way to tell "nobody touched a switch" apart
  from "the connection died" the way the liveness probe can. History:
  originally added at a 1-hour default after a real incident
  (2026-08-17/18, `rtl_433 -d rtl_tcp:...` losing its connection silently
  without the process exiting, going undetected for over a day); that
  1-hour default then false-positived on nothing but normal overnight
  inactivity (2026-08-19), which is what prompted adding the liveness
  probe above as the real fix and loosening this to a pure fallback.
- `code_table` — maps each switch's decoded RF `stable_id` (a hex string) to a
  room/button. **Example values only; replace them.**
- `room_devices` — maps each room to its Bond `device_id` and `max_speed`. The
  `room` names must match the ones used in `code_table`. **Example values only;
  replace them.**
- `debounce_seconds` — quiet period (in seconds) after the last matching RF
  press before the corresponding Bond correction is sent, so repeated RF
  transmissions from a single physical button press coalesce into one call.
  Defaults to `3.0`.
- `burst_gap_seconds` — silence (in seconds) that marks the end of one
  physical press on a *toggle* button (`light`, `power`). Repeats within a
  single press are ~60ms apart and span at most ~0.8s, while distinct presses
  are seconds apart, so each burst becomes exactly one toggle. Defaults to
  `0.5`. Raising this towards `debounce_seconds` reintroduces press-count loss:
  two presses inside one quiet period collapse into a single correction and
  leave Bond's belief inverted.
- `bond_echo_ttl_seconds` — how long an expected-echo token stays valid.
  Defaults to `debounce_seconds + 3.0`. Too short and a real echo outlives its
  token and gets "corrected"; too long and a token left behind by a
  transmission that was never decoded can suppress a later genuine press.
- `dry_run` — when true, logs the Bond call that would be made without
  sending it. Echo suppression still runs, so a dry run exercises the same
  decision path the live add-on will take.

### Finding your own values

**`bond_host`** — the Bond Bridge's address on your LAN. Its IP is in the Bond
app under Bridge settings, or on your router's client list.

**`bond_token`** — the Bridge's Local Token, shown in the Bond app under
Bridge settings → Advanced → Local Integrations. It is per-bridge; there is no
account-wide token.

**`room_devices[].bond_device_id`** — ask the Bridge for its own device list:

```sh
curl -s -H "BOND-Token: <your token>" http://<bond_host>/v2/devices
```

That returns an object keyed by device id (`{"ce4d...": {...}, ...}`). Fetch
one to confirm which fan it is and read its speed count:

```sh
curl -s -H "BOND-Token: <your token>" http://<bond_host>/v2/devices/<device_id>
```

Use the device's `name` to match it to a room, and its
`properties.max_speed` for `max_speed`.

**`code_table[].stable_id`** — these come off the air, so discover them by
pressing buttons. Start the add-on with `dry_run: true` and watch its log. Any
transmission that matches nothing in `code_table` is logged as:

```
unmatched RF press: stable_id=1d9 counter=0 (add it to code_table to act on it)
```

Press one button on one switch, note the id, and repeat for each button in each
room. Ids are logged and configured as lowercase hex with no `0x` prefix.
Presses that *do* match are logged as `seen <room>/<button>` instead, which is
how you confirm an entry is right.

If nothing decodes at all, the frequency is the first thing to check —
`rtl433_frequency` defaults to 304.25 MHz, which is what the fans this was
built against use. Other brands commonly use 315 MHz or 433.92 MHz.

## Why it ignores some presses it hears

The Bond Bridge transmits the *same* RF codes the wall switches do, so its own
transmissions are indistinguishable from a button press on the air. Left alone,
the add-on "corrects" state in response to them and inverts whatever Bond just
set — an echo feedback loop.

To tell them apart, the add-on subscribes to the Bridge's push protocol (BPUP,
UDP port 30007) and takes one single-use token per transmission the Bridge
announces. A decode that finds a matching token is its own echo and is skipped,
logged as `ignored (bond self-TX echo)`; a decode that finds none is a real
press and is corrected.

Tokens are counted, not timed, so a genuine press moments after a Home
Assistant command is still honoured — a blanket "ignore everything for N
seconds" would swallow it. Belief-only state writes emit no `/actions/` push,
so the add-on's own corrections never produce tokens.

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
logged. **2026-08-19 follow-up:** the resulting stale-output watchdog's
1-hour default then false-positived on ordinary overnight RF silence — see
`rtl433_liveness_probe_interval_seconds` / `rtl433_stale_timeout_seconds`
above and `CHANGELOG.md`'s `1.0.3`/`1.0.5` entries for the full story.

**2026-08-29 incident:** an unrelated deadlock — `proc.wait()` after
`proc.terminate()` had no timeout, so a `rtl_433` that didn't die from
SIGTERM froze the whole manager silently for 22+ hours (missed a real
wall-switch press). Fixed in `1.0.8`; see `CHANGELOG.md`.
