"""Constants used by the SmartThings component and platforms."""
from datetime import timedelta

from homeassistant.const import (
    UnitOfElectricPotential,
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
)

DOMAIN = "smartthings"

# OAuth2 scopes for SmartThings API
SCOPES = [
    "r:devices:*",
    "w:devices:*",
    "x:devices:*",
    "r:hubs:*",
    "r:locations:*",
    "w:locations:*",
    "x:locations:*",
    "r:scenes:*",
    "x:scenes:*",
    "r:rules:*",
    "w:rules:*",
    "sse",
]

REQUESTED_SCOPES = [
    *SCOPES,
    "r:installedapps",
    "w:installedapps",
]

# Legacy config keys (for migration compatibility)
APP_OAUTH_CLIENT_NAME = "Home Assistant"
APP_OAUTH_SCOPES = ["r:devices:*"]
APP_NAME_PREFIX = "homeassistant."

CONF_APP_ID = "app_id"
CONF_CLOUDHOOK_URL = "cloudhook_url"
CONF_INSTALLED_APP_ID = "installed_app_id"
CONF_INSTANCE_ID = "instance_id"
CONF_LOCATION_ID = "location_id"
CONF_REFRESH_TOKEN = "refresh_token"

# Used for migration from old data format
OLD_DATA = "old_data"

DATA_MANAGER = "manager"
DATA_BROKERS = "brokers"
EVENT_BUTTON = "smartthings.button"

SIGNAL_SMARTTHINGS_UPDATE = "smartthings_update"
SIGNAL_SMARTAPP_PREFIX = "smartthings_smartap_"

SETTINGS_INSTANCE_ID = "hassInstanceId"

SUBSCRIPTION_WARNING_LIMIT = 40

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

# Ordered 'specific to least-specific platform' in order for capabilities
# to be drawn-down and represented by the most appropriate platform.
PLATFORMS = [
    "climate",
    "fan",
    "light",
    "lock",
    "cover",
    "number",
    "select",
    "button",
    "switch",
    "binary_sensor",
    "sensor",
    "scene",
]

IGNORED_CAPABILITIES = [
    "healthCheck",
    "ocf",
]

UNIT_MAP = {
    "C": UnitOfTemperature.CELSIUS,
    "F": UnitOfTemperature.FAHRENHEIT,
    "Hour": "Hour",
    "minute": "Minute",
    "%": PERCENTAGE,
    "W": UnitOfPower.WATT,
    "V": UnitOfElectricPotential.VOLT,
}

TOKEN_REFRESH_INTERVAL = timedelta(days=14)
