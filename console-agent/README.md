# Console Agent

Pushes this Home Assistant host's state to
[`console.marktuttle.dev`](https://console.marktuttle.dev) every 30 seconds, so
the HA box appears there next to the VPS and nexus.

It is **read-only and outbound-only**: it makes only `GET` calls to the
Supervisor, nothing listens on a port, and no folders are mapped.

## What it sends

One JSON document per interval, `POST`ed to `ingest_url` with
`Authorization: Bearer <ingest_token>`. The document must validate against the
console's published contract at
<https://console.marktuttle.dev/contract/snapshot.schema.json> — the add-on's
tests validate against the console checkout's contract when run on nexus.
Nothing runs them automatically, so that check is only as good as the last
time someone ran `pytest`.

| Field | Where it comes from |
| --- | --- |
| `metrics.cpu_pct`, `load1/5/15`, `mem_*`, `swap_used_mb` | `psutil`, i.e. `/proc`. Inside an add-on container those files describe the **host**, so these need no API at all. |
| `metrics.net_rx_bps` / `net_tx_bps` | always `0` — **this host reports no network throughput.** `/proc/net/dev` is per network namespace and the add-on deliberately has no `host_network`, so any figure here would describe the add-on's own traffic, not the host's. The contract requires the keys, so they are sent as an honest zero rather than a plausible wrong number. |
| `metrics.disk_root_total_gb` / `disk_root_used_gb` | Supervisor `GET /host/info` (the data disk) |
| `metrics.uptime_s` | now − `boot_timestamp` from `GET /host/info` |
| `metrics.cpu_temp_c`, `metrics.top_process` | always `null` — HAOS exposes neither to an add-on |
| `kernel` | `"<kernel> · HAOS <os version> · Core <core version>"`, from `GET /host/info` and `GET /core/info` |
| `containers` | one row per add-on from `GET /addons`, with `cpu_pct` / `mem_mb` from `GET /addons/<slug>/stats` for **started** add-ons only. `status` is `"<state> · v<version> · <slug>"` — the version is repeated there because the console's container table renders `status` but not `image`. |
| `timers`, `failed_units`, `heartbeats`, `logs` | always empty — this host reports none of them |

## Options

| Option | Default | Notes |
| --- | --- | --- |
| `ingest_url` | `https://console.marktuttle.dev/api/ingest` | |
| `ingest_token` | *(empty)* | **Required.** The console's per-host token for `ha`. While it is empty the add-on starts, logs one line saying so, and then idles without pushing anything. |
| `interval_seconds` | `30` | 10–600. The console flags a host as `SIGNAL LOST` after 90 s, so anything above ~80 will look permanently offline. |
| `addon_stats` | `true` | Off skips the per-add-on `stats` calls; the add-on list still appears, without CPU/memory. |

### Where the tokens come from

- **`SUPERVISOR_TOKEN`** is injected by the Supervisor because the manifest sets
  `hassio_api: true`. You never set it. If it is missing the add-on exits 2, so
  the Supervisor shows it as failed rather than looping silently.
  `hassio_role: manager` is required only to read *other* add-ons' stats.
- **`ingest_token`** is yours to paste into the add-on's Configuration tab. It
  is stored in 1Password as `hal9000/console-ingest-token-ha` and on the console
  side as the GitHub secret `CONSOLE_INGEST_TOKEN_HA`. It can only post
  snapshots claiming `host: "ha"` — a body claiming any other host is rejected
  with 422 — so revoking it affects nothing but this host.

## Reading its log

Settings → Add-ons → Console Agent → **Log**. One line per push:

```
console-agent: 204 (3184 bytes)                       <- success
console-agent: HTTP 422 from console: {"errors":[...]}  <- contract violation, body shown
console-agent: console unreachable: ...                <- network/DNS, will retry
console-agent: supervisor call failed: ...             <- degraded: that field falls back
```

**It never exits on a push failure.** A crash-looping add-on would be a worse
liveness signal than the console's own `SIGNAL LOST` banner, which is what
you should watch instead. A `supervisor call failed` line means one part of
the snapshot degraded (missing disk figures, or an empty add-on list) while the
rest still went out.

## Development

Tests run on nexus, not in the container:

```sh
cd console-agent && python3 -m pytest -q
```

They read the console's contract from
`~/docker/html-local/console/htdocs/contract/snapshot.schema.json`; override
with the `CONSOLE_SCHEMA` environment variable if that path moves.
