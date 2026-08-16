# Changelog

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
