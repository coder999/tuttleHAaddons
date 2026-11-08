from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

DOMAIN = "ifit_bike"
WHEEL_RATIO = "wheel_ratio"  # km/h per rpm; the bike reports no speed (QZ's estimate)
DEFAULT_WHEEL_RATIO = 0.33
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


def device_info(address: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, address)},
        connections={(CONNECTION_BLUETOOTH, address)},
        name="Bike",
        manufacturer="ProForm / iFit",
        model="iFit bike (I_EB)",
    )
