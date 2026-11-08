"""Resistance control: set the console's level (1-16) from HA; shows the level the bike reports."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import SIGNAL, protocol
from .const import device_info


async def async_setup_entry(hass, entry, add_entities):
    add_entities([BikeResistance(entry.runtime_data)])


class BikeResistance(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Resistance level"
    _attr_icon = "mdi:gauge"
    _attr_native_min_value = 1
    _attr_native_max_value = len(protocol.SET_RESISTANCE)
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, bike) -> None:
        self._bike = bike
        self._attr_unique_id = f"{bike.address}_set_resistance"
        self._attr_device_info = device_info(bike.address)

    @property
    def available(self) -> bool:
        return self._bike.status in ("connected", "riding")

    @property
    def native_value(self):
        return self._bike.data["resistance"]

    async def async_set_native_value(self, value: float) -> None:
        self._bike.want_resistance = int(value)  # the poll loop sends it within ~1.5 s

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL, self.async_write_ha_state))
