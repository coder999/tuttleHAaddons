from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfLength, UnitOfPower, UnitOfSpeed, UnitOfTime
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import SIGNAL
from .const import device_info

MEAS = SensorStateClass.MEASUREMENT
# key, name, device class, unit, state class, icon, value getter
SENSORS = [
    ("power", "Power", SensorDeviceClass.POWER, UnitOfPower.WATT, MEAS, None, lambda b: b.data["power"]),
    ("cadence", "Cadence", None, "rpm", MEAS, "mdi:rotate-right", lambda b: b.data["cadence"]),
    ("speed", "Speed", SensorDeviceClass.SPEED, UnitOfSpeed.KILOMETERS_PER_HOUR, MEAS, None,
     lambda b: b.data["speed"]),
    ("resistance", "Resistance", None, None, MEAS, "mdi:gauge", lambda b: b.data["resistance"]),
    ("ride_time", "Ride time", SensorDeviceClass.DURATION, UnitOfTime.SECONDS, None, None,
     lambda b: b.ride_time),
    ("ride_distance", "Ride distance", SensorDeviceClass.DISTANCE, UnitOfLength.METERS, None, None,
     lambda b: round(b.ride_distance)),
    ("status", "Status", SensorDeviceClass.ENUM, None, None, "mdi:bike", lambda b: b.status),
]


async def async_setup_entry(hass, entry, add_entities):
    add_entities(BikeSensor(entry.runtime_data, *s) for s in SENSORS)


class BikeSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True  # "Bike Power": device name + this name

    def __init__(self, bike, key, name, device_class, unit, state_class, icon, getter):
        self._bike = bike
        self._get = getter
        self._attr_unique_id = f"{bike.address}_{key}"
        self._attr_name = name
        self._attr_device_info = device_info(bike.address)
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_icon = icon
        if device_class == SensorDeviceClass.ENUM:
            self._attr_options = ["disconnected", "connecting", "connected", "riding"]

    @property
    def native_value(self):
        return self._get(self._bike)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL, self.async_write_ha_state))
