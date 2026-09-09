# Console Agent

Pushes this Home Assistant host's state to a console endpoint of your choosing
every 30 seconds, so the HA box appears there alongside your other machines.

Nothing in this add-on is tied to a particular console: set `ingest_url`,
`ingest_token` and `host_id` in the Configuration tab and it posts to yours.
Until `ingest_url` is changed from its example placeholder the add-on starts,
says so in the log, and idles without pushing anything.

It is **read-only and outbound-only**: it makes only `GET` calls to the
Supervisor, nothing listens on a port, and no folders are mapped.

## What it sends

One JSON document per interval, `POST`ed to `ingest_url` with
`Authorization: Bearer <ingest_token>`. Your console decides what it will
accept; this add-on was built against a contract published at
`<your-console>/contract/snapshot.schema.json`, and its tests validate the
document it builds against that file when you point `CONSOLE_SCHEMA` at a copy
(see Development). Nothing runs them automatically, so that check is only as
good as the last time someone ran `pytest`.

| Field | Where it comes from |
| --- | --- |
| `host` | the `host_id` option verbatim — see below |
| `metrics.cpu_pct`, `load1/5/15`, `mem_*`, `swap_used_mb` | `psutil`, i.e. `/proc`. Inside an add-on container those files describe the **host**, so these need no API at all. |
| `metrics.net_rx_bps` / `net_tx_bps` | always `0` — **this host reports no network throughput.** `/proc/net/dev` is per network namespace and the add-on deliberately has no `host_network`, so any figure here would describe the add-on's own traffic, not the host's. The contract requires the keys, so they are sent as an honest zero rather than a plausible wrong number. |
| `metrics.disk_root_total_gb` / `disk_root_used_gb` | Supervisor `GET /host/info` (the data disk) |
| `metrics.uptime_s` | now − `boot_timestamp` from `GET /host/info` |
| `metrics.cpu_temp_c` | the host's `x86_pkg_temp` thermal zone, else the `coretemp` hwmon package sensor, else `null` |
| `metrics.top_process` | always `null` — HAOS does not expose it to an add-on |
| `kernel` | `"<kernel> · HAOS <os version> · Core <core version>"`, from `GET /host/info` and `GET /core/info` |
| `containers` | one row per add-on from `GET /addons`, with `cpu_pct` / `mem_mb` from `GET /addons/<slug>/stats` for **started** add-ons only. `status` is `"<state> · v<version> · <slug>"` — the version is repeated there because a console's container table typically renders `status` but not `image`. |
| `timers`, `failed_units`, `heartbeats`, `logs` | always empty — this host reports none of them |

## Options

| Option | Default | Notes |
| --- | --- | --- |
| `ingest_url` | `https://console.example.com/api/ingest` | **Placeholder — change it.** `example.com` is reserved by RFC 2606 and cannot resolve, so an unconfigured add-on never posts your metrics to someone else's server. While it is unchanged the add-on idles. |
| `ingest_token` | *(empty)* | **Required.** The token your console issues for this host. While it is empty the add-on starts, logs one line saying so, and then idles. |
| `host_id` | `homeassistant` | The identifier this host is known by on your console, sent as the document's `host` field. Consoles commonly bind each token to exactly one host id and reject a mismatch (typically `422`), and some restrict `host` to a fixed list of known hosts — so this usually has to match a name you registered, not one you invent here. |
| `interval_seconds` | `30` | 10–600. A console that flags a host as offline after 90 s will show this one as permanently down at anything above ~80. |
| `addon_stats` | `true` | Off skips the per-add-on `stats` calls; the add-on list still appears, without CPU/memory. |

### About `SUPERVISOR_TOKEN`

`SUPERVISOR_TOKEN` is injected by the Supervisor because the manifest sets
`hassio_api: true`. You never set it. If it is missing the add-on exits 2, so
the Supervisor shows it as failed rather than looping silently.
`hassio_role: manager` is required only to read *other* add-ons' stats.

## Reading its log

Settings → Add-ons → Console Agent → **Log**. One line per push:

```
console-agent: 204 (3184 bytes)                       <- success
console-agent: HTTP 422 from console: {"errors":[...]}  <- contract violation, body shown
console-agent: console unreachable: ...                <- network/DNS, will retry
console-agent: supervisor call failed: ...             <- degraded: that field falls back
```

A `422` naming the `host` field almost always means `host_id` does not match
what your console expects for this box.

**It never exits on a push failure.** A crash-looping add-on would be a worse
liveness signal than a console's own offline banner, which is what you should
watch instead. A `supervisor call failed` line means one part of the snapshot
degraded (missing disk figures, or an empty add-on list) while the rest still
went out.

## Development

Tests run on a workstation, not in the container:

```sh
cd console-agent && python3 -m pytest -q
```

The contract tests read your console's schema from the path in the
`CONSOLE_SCHEMA` environment variable. That schema is deliberately **not**
vendored into this repo — a copy could not notice the console changing
underneath it. Without `CONSOLE_SCHEMA` those four tests skip and the rest of
the suite still runs:

```sh
CONSOLE_SCHEMA=/path/to/snapshot.schema.json python3 -m pytest -q
```
