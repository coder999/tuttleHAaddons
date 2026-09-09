# Changelog

## 0.2.0

- **The target console is now entirely configurable.** `host` was hard-coded to
  `"ha"` in the snapshot, and `ingest_url` defaulted to one specific
  deployment, so nobody but the original author could use this add-on: a
  console binds each ingest token to one host id, so a fixed id makes every
  push fail no matter what URL you set. `host_id` is a new option, and the
  `User-Agent` no longer carries the same fixed id.
- **`ingest_url` now defaults to an unusable placeholder**
  (`https://console.example.com/api/ingest`; `example.com` is reserved by
  RFC 2606 and cannot resolve). The add-on idles until you change it, so a
  fresh install can never post this host's metrics to somebody else's server.
- **The test suite runs without a console checkout.** The contract schema was
  read at module scope from one hard-coded path, so a missing file failed
  collection and took the 19 tests that need no schema down with it. The four
  contract tests now skip unless `CONSOLE_SCHEMA` points at a schema, and they
  take the host id from that schema's own `host` enum rather than assuming one.
- Documentation rewritten with no reference to a particular deployment.

## 0.1.2

- **CPU temperature.** `cpu_temp_c` was hard-coded to `null`; the host's
  `x86_pkg_temp` thermal zone (fallback: the `coretemp` hwmon) is visible to
  add-on containers on HAOS generic-x86-64, so the snapshot now carries it
  and the console shows it with the same mood label as the other hosts.

## 0.1.1

- **Null-safety across the Supervisor payload.** `a.get("name", a["slug"])`
  evaluated its default eagerly and raised `KeyError` on a slug-less entry, and
  a `null` (rather than absent) `operating_system` raised `AttributeError` on
  `.replace`. Every field the snapshot reads now tolerates both missing and
  present-but-null, and a `null` version no longer renders as the string
  `"None"`. Covered by a test that feeds a deliberately ragged add-on list.
- **The push loop no longer crashes the add-on.** `build_snapshot` and `push`
  run inside a `try/except`, so a programming error degrades to one
  `snapshot failed:` line per interval instead of a Supervisor restart loop
  that dies before its own log can be read.
- **No network throughput is reported.** `net_rx_bps` / `net_tx_bps` are now
  always `0`. `/proc/net/dev` is per network namespace and the add-on has no
  `host_network`, so the previous psutil delta measured the add-on's own
  traffic and presented it as the host's — a plausible-looking wrong number,
  which is worse than nothing on a dashboard. The contract requires the keys,
  so they are sent as zero.
- **The `/apps` fallback is now 404-only.** It previously caught every
  `HTTPError`, so a 401/403 from a wrong `hassio_role` was masked by a second,
  less informative failure against `/apps`. Non-404s are re-raised with their
  real status.
- **Add-on versions are visible again.** The console's container table renders
  `status` but not `image`, so `status` is now
  `"<state> · v<version> · <slug>"` (the `v…` segment is omitted when the
  version is empty). `image` still carries the version too, per the contract.
- `ingest_url` falls back to the documented default if the option is missing or
  empty; a corrupt or unreadable `/data/options.json` now logs a clear error and
  exits 2 rather than raising, since that is a misconfiguration rather than a
  transient fault.
- Added `.dockerignore` (`__pycache__/`, `.pytest_cache/`, `tests/`) so the
  build context carries only what the image needs.
- Docs: corrected the README's claim that the empty-token notice prints once per
  interval (it prints once, at startup), and dropped its "cannot drift apart
  silently" claim about the contract tests — nothing runs them automatically.

## 0.1.0

- Initial release. Pushes a contract-valid `host: "ha"` snapshot to
  `console.marktuttle.dev` every `interval_seconds` (default 30).
- Host CPU, RAM, load, swap and network come from `psutil`; inside an add-on
  container `/proc` is the host's, so these need no Supervisor call.
- Disk, uptime, kernel/OS/Core versions and the add-on list come from the
  Supervisor API (`GET` only: `/host/info`, `/core/info`, `/addons`,
  `/addons/<slug>/stats`). Falls back to `/apps` on a 404 — the Supervisor CLI
  already deprecates `addons` in favour of `apps`, though the REST path still
  works as of Supervisor 2026-09. The fallback is untested against a real
  `/apps` payload.
- Degrades instead of crashing: any failed Supervisor call logs one line and
  leaves that part of the snapshot at its zero value. Any failed push logs one
  line and the loop continues — the console's `SIGNAL LOST` is the liveness
  signal, not the add-on's exit code. The one hard failure is a missing
  `SUPERVISOR_TOKEN`, which exits 2 so the Supervisor marks the add-on failed.
- `icon.png` is a placeholder copied from the Markdown Wiki add-on; it is not
  yet artwork specific to this add-on.
