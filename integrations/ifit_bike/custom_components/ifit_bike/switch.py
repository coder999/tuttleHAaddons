"""Off = leave the bike alone, so the iFit app can have its single BLE connection."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity

from . import DOMAIN


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    if discovery_info is not None:
        add_entities([BikeSwitch(hass.data[DOMAIN])])


class BikeSwitch(SwitchEntity, RestoreEntity):
    _attr_should_poll = False
    _attr_name = "Bike connection"
    _attr_icon = "mdi:bluetooth"

    def __init__(self, bike) -> None:
        self._bike = bike
        self._attr_unique_id = f"{bike.address}_connection"

    @property
    def is_on(self) -> bool:
        return self._bike.enabled

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) is not None:
            self._bike.enabled = last.state != "off"

    async def async_turn_on(self, **kwargs) -> None:
        self._bike.enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._bike.enabled = False  # the poll loop sees this within 200 ms and disconnects
        self.async_write_ha_state()
