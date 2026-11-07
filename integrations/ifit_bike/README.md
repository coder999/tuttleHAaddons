# iFit Bike (Home Assistant custom integration)

Not an add-on: this is a custom integration, so the add-on store doesn't list or install it. It
lives here so all of this repo owner's Home Assistant work is in one place.

Reads a ProForm/iFit exercise bike over Bluetooth through Home Assistant's own Bluetooth stack
(so an ESPHome Bluetooth proxy near the bike also works), shows live sensors, saves each ride as
a TCX file and uploads it to Strava. Built for a ProForm Sport CX (PFEX33921.0), which advertises
as `I_EB` and speaks iFit's proprietary protocol, not FTMS.

- Live sensors: `sensor.bike_power`, `_cadence`, `_speed`, `_resistance`, `_ride_time`,
  `_ride_distance`, `_status`. The bike sends one data frame per 7-message poll cycle
  (~1.4 s at the 200 ms poll; measured 2026-11-07 on the Sport CX), so values move about that often.
- `switch.bike_connection`: off releases the bike so the iFit app can connect (the bike accepts
  one BLE connection at a time). Pressing the bike's own disconnect only drops HA for ~60 s.
- Rides start on the first pedal stroke and end after 2 min idle or a disconnect. Each ride over
  60 s is saved to `/config/ifit_rides/<start>.tcx` and uploaded to Strava as an indoor ride.
- `dashboard.py` creates a "Bike" dashboard (`/dashboard-bike`) with gauges and graphs.

Protocol frames are QZ's default `proformbike` profile; see the header of `protocol.py`. Other
iFit bikes may need a different QZ profile. Speed and distance are QZ's estimate
(`wheel_ratio` x cadence); the bike reports neither. Tune `wheel_ratio` against the console.

## Install

Find the bike's Bluetooth address (it advertises as `I_EB`; HA's Bluetooth settings page lists
advertisements). Copy the integration into HA, for example over the SSH add-on:

```sh
tar -C custom_components -c --exclude=__pycache__ ifit_bike | ssh <ha-host> 'tar -C /config/custom_components -x'
```

Add a package such as `/config/packages/ifit_bike.yaml`, then restart HA fully (custom code only
loads at startup; a restart mid-ride ends that ride):

```yaml
ifit_bike:
  address: AA:BB:CC:DD:EE:FF
  # wheel_ratio: 0.33
  strava_client_id: !secret strava_client_id        # omit both lines to skip Strava
  strava_client_secret: !secret strava_client_secret
```

Dashboard (optional): `TOKEN=<HA long-lived token> python3 dashboard.py ws://<ha-host>:8123/api/websocket`

## Strava

1. Create an API app at https://www.strava.com/settings/api. Website can be any URL you own;
   set the callback domain to `localhost`. It requires an icon: `icon.png` here works.
   Ignore the access/refresh tokens on that page (read-only scope).
2. Put its client ID and secret in HA's `secrets.yaml` (keys above) and restart.
3. HA shows an "Authorize Strava" notification. Approve (keep "upload activities" ticked); the
   browser lands on a dead localhost page. Copy `code=` from its address bar into the
   `ifit_bike.strava_authorize` action within a few minutes (codes are single-use).
4. A ride that couldn't upload stays in `/config/ifit_rides/`; retry with `ifit_bike.upload_ride`.

## Check

`python3 test_protocol.py` covers the frame parser (including frames captured from a real bike)
and the TCX writer. No HA needed.
