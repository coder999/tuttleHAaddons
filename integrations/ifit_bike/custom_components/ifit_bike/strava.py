"""Strava upload. Tokens live in HA's .storage (Strava rotates the refresh token)."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)
API = "https://www.strava.com/api/v3"
REDIRECT = "http://localhost/exchange_token"  # nothing listens; the user copies ?code= from the URL bar


class NotAuthorized(Exception):
    """No Strava token yet: run the ifit_bike.strava_authorize service first."""


class Strava:
    def __init__(self, hass: HomeAssistant, client_id: str, client_secret: str) -> None:
        self.hass = hass
        self.client_id = client_id
        self.client_secret = client_secret
        self.store = Store(hass, 1, "ifit_bike.strava")

    @property
    def authorize_url(self) -> str:
        return (
            f"https://www.strava.com/oauth/authorize?client_id={self.client_id}"
            f"&response_type=code&redirect_uri={REDIRECT}&approval_prompt=force&scope=activity:write"
        )

    async def authorized(self) -> bool:
        return bool(await self.store.async_load())

    async def exchange(self, code: str) -> None:
        await self._token(grant_type="authorization_code", code=code)

    async def _token(self, **params: str) -> dict:
        session = async_get_clientsession(self.hass)
        data = {"client_id": self.client_id, "client_secret": self.client_secret, **params}
        async with session.post("https://www.strava.com/oauth/token", data=data) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"Strava token request failed ({resp.status}): {body}")
        tok = {k: body[k] for k in ("access_token", "refresh_token", "expires_at")}
        await self.store.async_save(tok)
        return tok

    async def _access_token(self) -> str:
        tok = await self.store.async_load()
        if not tok:
            raise NotAuthorized
        if tok["expires_at"] < time.time() + 60:
            tok = await self._token(grant_type="refresh_token", refresh_token=tok["refresh_token"])
        return tok["access_token"]

    async def upload(self, name: str, tcx: str) -> str:
        """Upload a TCX as an indoor ride; returns the activity URL. Raises on any failure."""
        headers = {"Authorization": f"Bearer {await self._access_token()}"}
        session = async_get_clientsession(self.hass)
        form = aiohttp.FormData()
        form.add_field("file", tcx.encode(), filename=name, content_type="application/xml")
        form.add_field("data_type", "tcx")
        form.add_field("trainer", "1")
        form.add_field("external_id", name)  # Strava rejects a second upload of the same file
        async with session.post(f"{API}/uploads", data=form, headers=headers) as resp:
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
            async with session.get(f"{API}/uploads/{body['id']}", headers=headers) as resp:
                body = await resp.json()
        raise RuntimeError(f"Strava still processing {name} after 30 s: {body.get('status')}")
