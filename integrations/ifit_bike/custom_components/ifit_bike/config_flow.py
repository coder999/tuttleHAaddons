"""Setup: pick the bike (Bluetooth discovery or a list), then optionally connect Strava.

Strava rides on HA's OAuth2 helper: credentials live in Application Credentials and the
token in the entry. Reconfigure connects, reconnects or disconnects Strava later.
"""

from __future__ import annotations

import logging
from typing import Any

import probatio as vol  # HA 2026.11 replaced voluptuous with probatio (same API)
from homeassistant.components import bluetooth
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from . import protocol
from .const import DEFAULT_WHEEL_RATIO, DOMAIN, WHEEL_RATIO

# Match iFit's service, not the name: the name (I_EB...) rides in the scan response, which HA
# doesn't always get (seen 2026-11-07: same bike listed only by its address).
NOT_A_BIKE = ("I_TL", "I_IT")  # iFit treadmills: same service, different protocol


class IfitBikeFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._address: str | None = None

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    @property
    def extra_authorize_data(self) -> dict:
        return {"scope": "activity:write", "approval_prompt": "auto"}

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return IfitBikeOptions()

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address.upper()
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_strava()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # raise_on_progress=False: the Bluetooth discovery flow for the same bike may be
            # open too; creating this entry aborts it.
            await self.async_set_unique_id(user_input[CONF_ADDRESS], raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._address = user_input[CONF_ADDRESS]
            return await self.async_step_strava()
        configured = self._async_current_ids(include_ignore=False)
        bikes = {
            info.address.upper(): f"{info.name} ({info.address})"
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if protocol.SERVICE_UUID in info.service_uuids
            and not (info.name or "").startswith(NOT_A_BIKE)
            and info.address.upper() not in configured
        }
        if not bikes:
            # Add integration always looks for a new bike first; with one already set up that
            # read as "not in range" when the user only wanted Strava (2026-11-07).
            return self.async_abort(reason="use_reconfigure" if configured else "no_devices_found")
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(bikes)})
        )

    async def async_step_strava(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="strava", menu_options=["pick_implementation", "skip"])

    async def async_step_skip(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(title="Bike", data={CONF_ADDRESS: self._address})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="reconfigure", menu_options=["pick_implementation", "disconnect_strava"]
        )

    async def async_step_disconnect_strava(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        return self.async_update_reload_and_abort(
            entry, data={CONF_ADDRESS: entry.data[CONF_ADDRESS]}
        )

    async def async_oauth_create_entry(self, data: dict) -> ConfigFlowResult:
        """Strava authorized: data is {auth_implementation, token}."""
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
        return self.async_create_entry(title="Bike", data={CONF_ADDRESS: self._address, **data})


class IfitBikeOptions(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(WHEEL_RATIO): NumberSelector(
                    NumberSelectorConfig(
                        min=0.05, max=2.0, step=0.01, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="km/h per rpm",
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, {WHEEL_RATIO: self.config_entry.options.get(WHEEL_RATIO, DEFAULT_WHEEL_RATIO)}
            ),
        )
