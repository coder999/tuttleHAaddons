"""Strava upload. HA's OAuth2Session refreshes the token and stores it in the config entry
(Strava rotates the refresh token; the session persists each new one)."""

from __future__ import annotations

import asyncio

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

API = "https://www.strava.com/api/v3"


class Strava:
    def __init__(self, hass: HomeAssistant, session: OAuth2Session) -> None:
        self.hass = hass
        self.session = session

    async def upload(self, name: str, tcx: str) -> str:
        """Upload a TCX as an indoor ride; returns the activity URL. Raises on any failure."""
        await self.session.async_ensure_token_valid()
        headers = {"Authorization": f"Bearer {self.session.token['access_token']}"}
        http = async_get_clientsession(self.hass)
        form = aiohttp.FormData()
        form.add_field("file", tcx.encode(), filename=name, content_type="application/xml")
        form.add_field("data_type", "tcx")
        form.add_field("trainer", "1")
        form.add_field("external_id", name)  # Strava rejects a second upload of the same file
        async with http.post(f"{API}/uploads", data=form, headers=headers) as resp:
            body = await resp.json()
            if resp.status >= 300:
                raise RuntimeError(f"Strava upload failed ({resp.status}): {body}")
        # Strava processes asynchronously; a bad file only shows up as an error on this poll.
        for _ in range(10):
            if body.get("error"):
                raise RuntimeError(f"Strava rejected {name}: {body['error']}")
            if body.get("activity_id"):
                return f"https://www.strava.com/activities/{body['activity_id']}"
            await asyncio.sleep(3)
            async with http.get(f"{API}/uploads/{body['id']}", headers=headers) as resp:
                body = await resp.json()
        raise RuntimeError(f"Strava still processing {name} after 30 s: {body.get('status')}")
