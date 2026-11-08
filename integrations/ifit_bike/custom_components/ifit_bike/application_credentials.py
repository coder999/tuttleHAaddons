"""Strava app credentials, entered in HA's Application Credentials screen."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import STRAVA_AUTHORIZE_URL, STRAVA_TOKEN_URL


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    return AuthorizationServer(authorize_url=STRAVA_AUTHORIZE_URL, token_url=STRAVA_TOKEN_URL)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    return {"strava_api_url": "https://www.strava.com/settings/api"}
