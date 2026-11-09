# iFit Bike (Home Assistant custom integration)

Not an add-on: this is a custom integration, so the add-on store doesn't list or install it. It
lives here so all of this repo owner's Home Assistant work is in one place.

Reads a ProForm/iFit exercise bike over Bluetooth through Home Assistant's own Bluetooth stack
(so an ESPHome Bluetooth proxy near the bike also works), shows live sensors, saves each ride as
a TCX file and uploads it to Strava. Built for a ProForm Sport CX (PFEX33921.0), which advertises
as `I_EB` and speaks iFit's proprietary protocol, not FTMS.

- Live sensors: `sensor.bike_power`, `_cadence`, `_speed`, `_resistance`, `_ride_time`,
  `_ride_distance`, `_status` (entity ids gain the device's area prefix, e.g. `basement_`).
- `number.bike_resistance_level` (1-16) sets the console's resistance; the dashboard has +/-
  buttons for it. Works on the Sport CX (verified 2026-11-08: levels 4, 10, 11 set from HA). The bike sends one data frame per 7-message poll cycle
  (~1.4 s at the 200 ms poll; measured 2026-11-07 on the Sport CX), so values move about that often.
- `switch.bike_connection`: off releases the bike so the iFit app can connect (the bike accepts
  one BLE connection at a time). Pressing the bike's own disconnect only drops HA for ~60 s.
- Battery: after 5 min connected with no pedaling, HA lets go of the bike (status `idle`) so its
  console can sleep, and connects again only after the bike has gone quiet and woken up.
  Toggling `switch.bike_connection` off/on connects at once.
- Rides start on the first pedal stroke and end after 2 min idle or a disconnect. Each ride over
  60 s is saved to `/config/ifit_rides/<start>.tcx` and uploaded to Strava as an indoor ride.
- `dashboard.py` creates a "Bike" dashboard (`/dashboard-bike`) with gauges and graphs.

Protocol frames are QZ's default `proformbike` profile; see the header of `protocol.py`. Other
iFit bikes may need a different QZ profile. Ride distance is the console's own
odometer (data-frame bytes 14-15, meters; not in QZ), so it matches the console: checked live
2026-11-07 (8.37 mi) and 2026-11-08 (3.52 mi vs the console's ~3.3-3.5 mi readout). A ride stays
open across a Bluetooth dropout and the odometer covers the gap. Speed is still QZ's estimate
(`wheel_ratio` x cadence); the bike reports none. Tune `wheel_ratio` against the console.

## Install

Copy the integration into HA (for example over the SSH add-on) and restart HA fully; custom code
only loads at startup, and a restart mid-ride ends that ride:

```sh
tar -C custom_components -c --exclude=__pycache__ ifit_bike | ssh <ha-host> 'tar -C /config/custom_components -x'
```

Then wake the bike's console. HA discovers it (Bluetooth name `I_EB...`) and offers **iFit Bike**
under Settings > Devices & services; or add it there by hand. No YAML.

- **Settings** (Configure on the integration): `wheel_ratio`, applied live.
- **Strava**: offered during setup, or later via Reconfigure (connect, reconnect, disconnect).

Dashboard (optional): `TOKEN=<HA long-lived token> python3 dashboard.py ws://<ha-host>:8123/api/websocket`

## Strava

1. Create an API app at https://www.strava.com/settings/api. Website can be any URL you own; set
   the **Authorization Callback Domain to `my.home-assistant.io`** (HA's OAuth redirect when the
   `my` integration is loaded, which `default_config` does). It requires an icon: `icon.png` works.
   Ignore the access/refresh tokens on that page (read-only scope).
2. Choose **Connect Strava** in setup or Reconfigure. The first time, HA asks for the app's Client
   ID and Secret (stored in Settings > Application credentials), then sends you to Strava to approve.
   If approving lands on an unreachable `http://<ip>:8123/auth/external/callback...` page, set
   your Home Assistant URL at https://my.home-assistant.io to one this browser can reach.
3. A ride that couldn't upload stays in `/config/ifit_rides/`; retry with `ifit_bike.upload_ride`.

Rides reach Apple Health only through Strava's own "Send to Health" (Strava app > Settings >
Health); uploaded rides are forwarded once that is on.

## Check

`python3 test_protocol.py` covers the frame parser (including frames captured from a real bike)
and the TCX writer. No HA needed.
