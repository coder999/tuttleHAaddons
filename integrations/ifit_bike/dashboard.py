"""Create/refresh the Bike dashboard and display units in HA. TOKEN env = HA long-lived token.

Usage: TOKEN=... python3 dashboard.py ws://<ha-host>:8123/api/websocket
Idempotent: re-running overwrites the dashboard config with the one below.
Entity ids below are placeholders (sensor.bike_<key>); the real ids are looked up in the
entity registry by unique id, since HA prefixes the area (e.g. sensor.basement_bike_power).
"""

import asyncio
import json
import os
import sys

import websockets

URL = sys.argv[1]


def tile(entity, name=None, **kw):
    return {"type": "tile", "entity": entity, **({"name": name} if name else {}), **kw}


VIEW = {
    "title": "Bike",
    "path": "bike",
    "icon": "mdi:bike",
    "type": "sections",
    "max_columns": 2,
    "sections": [
        {
            "type": "grid",
            "cards": [
                {"type": "heading", "heading": "Live", "icon": "mdi:bike"},
                tile("sensor.bike_status", "Status"),
                tile("switch.bike_connection", "HA connection",
                     features=[{"type": "toggle"}]),
                {"type": "gauge", "entity": "sensor.bike_power", "name": "Power",
                 "min": 0, "max": 500, "needle": True,
                 "severity": {"green": 0, "yellow": 200, "red": 350}},
                {"type": "gauge", "entity": "sensor.bike_cadence", "name": "Cadence",
                 "min": 0, "max": 120, "needle": True,
                 "severity": {"red": 0, "yellow": 60, "green": 80}},
                tile("sensor.bike_resistance", "Resistance"),
                tile("sensor.bike_speed", "Speed"),
                tile("sensor.bike_ride_time", "Ride time"),
                tile("sensor.bike_ride_distance", "Distance"),
            ],
        },
        {
            "type": "grid",
            "cards": [
                {"type": "heading", "heading": "Last hour", "icon": "mdi:chart-line"},
                {"type": "history-graph", "hours_to_show": 1, "grid_options": {"columns": 12},
                 "entities": ["sensor.bike_power"]},
                {"type": "history-graph", "hours_to_show": 1, "grid_options": {"columns": 12},
                 "entities": ["sensor.bike_cadence", "sensor.bike_resistance"]},
            ],
        },
    ],
}

# Entity-registry display options: what a user would set in the entity's settings dialog.
DISPLAY = {
    "sensor.bike_speed": {"display_precision": 1},
    "sensor.bike_ride_distance": {"unit_of_measurement": "mi", "display_precision": 2},
}


async def main():
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": os.environ["TOKEN"]}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        n = 0

        async def call(**msg):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, **msg}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == n:
                    return r

        # unique_id is "<bike address>_<key>"; the address has no underscores.
        real = {
            f'{e["entity_id"].split(".")[0]}.bike_{e["unique_id"].split("_", 1)[1]}': e["entity_id"]
            for e in (await call(type="config/entity_registry/list"))["result"]
            if e["platform"] == "ifit_bike"
        }
        assert real, "no ifit_bike entities: set the bike up first"

        def resolve(obj):
            text = json.dumps(obj)
            for placeholder, entity_id in real.items():
                text = text.replace(f'"{placeholder}"', f'"{entity_id}"')
            return json.loads(text)

        dashboards = (await call(type="lovelace/dashboards/list"))["result"]
        if not any(d["url_path"] == "dashboard-bike" for d in dashboards):
            r = await call(type="lovelace/dashboards/create", url_path="dashboard-bike",
                           title="Bike", icon="mdi:bike", show_in_sidebar=True,
                           require_admin=False, mode="storage")
            assert r["success"], r
            print("created dashboard /dashboard-bike")
        r = await call(type="lovelace/config/save", url_path="dashboard-bike",
                       config={"title": "Bike", "views": [resolve(VIEW)]})
        assert r["success"], r
        print("saved dashboard config")
        for entity_id, options in resolve(DISPLAY).items():
            r = await call(type="config/entity_registry/update", entity_id=entity_id,
                           options_domain="sensor", options=options)
            assert r["success"], r
            print("display options", entity_id, options)


asyncio.run(main())
