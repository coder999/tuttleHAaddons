# Changelog

## 0.1.0

- Initial release. Pushes a contract-valid `host: "ha"` snapshot to
  `console.marktuttle.dev` every `interval_seconds` (default 30).
- Host CPU, RAM, load, swap and network come from `psutil`; inside an add-on
  container `/proc` is the host's, so these need no Supervisor call.
- Disk, uptime, kernel/OS/Core versions and the add-on list come from the
  Supervisor API (`GET` only: `/host/info`, `/core/info`, `/addons`,
  `/addons/<slug>/stats`). `/apps` is used as a fallback if `/addons` ever
  starts returning an HTTP error — the Supervisor CLI already deprecates
  `addons` in favour of `apps`, but the REST path still works as of Supervisor
  2026-09.
- Degrades instead of crashing: any failed Supervisor call logs one line and
  leaves that part of the snapshot at its zero value. Any failed push logs one
  line and the loop continues — the console's `SIGNAL LOST` is the liveness
  signal, not the add-on's exit code. The one hard failure is a missing
  `SUPERVISOR_TOKEN`, which exits 2 so the Supervisor marks the add-on failed.
- `icon.png` is a placeholder copied from the Markdown Wiki add-on; it is not
  yet artwork specific to this add-on.
