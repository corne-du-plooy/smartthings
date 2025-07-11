"""Support for SmartThings Cloud."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
from http import HTTPStatus
import importlib
import logging

from aiohttp.client_exceptions import ClientConnectionError, ClientResponseError
from pysmartapp.event import EVENT_TYPE_DEVICE
from pysmartthings import Attribute, Capability, SmartThings
from pysmartthings.device import DeviceEntity

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .config_flow import SmartThingsConfigFlow  # noqa: F401
from .const import (
    CONF_APP_ID,
    CONF_INSTALLED_APP_ID,
    CONF_LOCATION_ID,
    CONF_REFRESH_TOKEN,
    DATA_BROKERS,
    DATA_MANAGER,
    DOMAIN,
    EVENT_BUTTON,
    PLATFORMS,
    SIGNAL_SMARTTHINGS_UPDATE,
    TOKEN_REFRESH_INTERVAL,
)
from .smartapp import (
    format_unique_id,
    setup_smartapp,
    setup_smartapp_endpoint,
    smartapp_sync_subscriptions,
    unload_smartapp_endpoint,
    validate_installed_app,
    validate_webhook_requirements,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialize the SmartThings platform."""
    # Initialize the domain data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(DATA_MANAGER, None)
    hass.data[DOMAIN].setdefault(DATA_BROKERS, {})
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle migration of a previous version config entry.

    A config entry created under a previous version must go through the
    integration setup again so we can properly retrieve the needed data
    elements. Force this by removing the entry and triggering a new flow.
    """
    # Remove the entry which will invoke the callback to delete the app.
    hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
    # only create new flow if there isn't a pending one for SmartThings.
    if not hass.config_entries.flow.async_progress_by_handler(DOMAIN):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}
            )
        )

    # Return False because it could not be migrated.
    return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize config entry which represents an installed SmartApp."""
    # For backwards compat - only for legacy entries
    if entry.unique_id is None and CONF_APP_ID in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            unique_id=format_unique_id(
                entry.data[CONF_APP_ID], entry.data[CONF_LOCATION_ID]
            ),
        )

    # Webhook validation only needed for legacy SmartApp entries
    if CONF_TOKEN not in entry.data:
        if not validate_webhook_requirements(hass):
            _LOGGER.warning(
                "The 'base_url' of the 'http' integration must be configured and start with 'https://'"
            )
            return False

    # Get access token from OAuth2 token or legacy access token
    if CONF_TOKEN in entry.data:
        access_token = entry.data[CONF_TOKEN][CONF_ACCESS_TOKEN]
    else:
        # Legacy entry with direct access token
        access_token = entry.data[CONF_ACCESS_TOKEN]
    
    api = SmartThings(async_get_clientsession(hass), access_token)

    remove_entry = False
    try:
        # Handle OAuth vs legacy setup
        if CONF_TOKEN in entry.data:
            # OAuth setup - simpler flow
            scenes = await async_get_entry_scenes(entry, api)
            devices = await api.devices(location_ids=[entry.data[CONF_LOCATION_ID]])
            smart_app = None
            token = None
        else:
            # Legacy setup with SmartApp
            # See if the app is already setup. This occurs when there are
            # installs in multiple SmartThings locations (valid use-case)
            manager = hass.data[DOMAIN][DATA_MANAGER]
            smart_app = manager.smartapps.get(entry.data[CONF_APP_ID])
            if not smart_app:
                # Validate and setup the app.
                app = await api.app(entry.data[CONF_APP_ID])
                smart_app = setup_smartapp(hass, app)

            # Validate and retrieve the installed app.
            installed_app = await validate_installed_app(
                api, entry.data[CONF_INSTALLED_APP_ID]
            )

            # Get scenes
            scenes = await async_get_entry_scenes(entry, api)

            # Get SmartApp token to sync subscriptions
            token = await api.generate_tokens(
                entry.data[CONF_CLIENT_ID],
                entry.data[CONF_CLIENT_SECRET],
                entry.data[CONF_REFRESH_TOKEN],
            )
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_REFRESH_TOKEN: token.refresh_token}
            )

            # Get devices and their current status
            devices = await api.devices(location_ids=[installed_app.location_id])

        async def retrieve_device_status(device):
            try:
                await device.status.refresh()
            except ClientResponseError:
                _LOGGER.debug(
                    "Unable to update status for device: %s (%s), the device will be excluded",
                    device.label,
                    device.device_id,
                    exc_info=True,
                )
                devices.remove(device)

        await asyncio.gather(*(retrieve_device_status(d) for d in devices.copy()))

        # Sync device subscriptions (only for legacy setup)
        if CONF_TOKEN not in entry.data:
            await smartapp_sync_subscriptions(
                hass,
                token.access_token,
                installed_app.location_id,
                installed_app.installed_app_id,
                devices,
            )

        # Setup device broker
        broker = DeviceBroker(hass, entry, token, smart_app, devices, scenes)
        broker.connect()
        hass.data[DOMAIN][DATA_BROKERS][entry.entry_id] = broker

    except ClientResponseError as ex:
        if ex.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            _LOGGER.exception(
                "Unable to setup configuration entry '%s' - please reconfigure the integration",
                entry.title,
            )
            remove_entry = True
        else:
            _LOGGER.debug(ex, exc_info=True)
            raise ConfigEntryNotReady from ex
    except (ClientConnectionError, RuntimeWarning) as ex:
        _LOGGER.debug(ex, exc_info=True)
        raise ConfigEntryNotReady from ex

    if remove_entry:
        hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
        # only create new flow if there isn't a pending one for SmartThings.
        if not hass.config_entries.flow.async_progress_by_handler(DOMAIN):
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}
                )
            )
        return False

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )
    return True


async def async_get_entry_scenes(entry: ConfigEntry, api):
    """Get the scenes within an integration."""
    try:
        return await api.scenes(location_id=entry.data[CONF_LOCATION_ID])
    except ClientResponseError as ex:
        if ex.status == HTTPStatus.FORBIDDEN:
            _LOGGER.exception(
                "Unable to load scenes for configuration entry '%s' because the access token does not have the required access",
                entry.title,
            )
        else:
            raise
    return []


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    broker = hass.data[DOMAIN][DATA_BROKERS].pop(entry.entry_id, None)
    if broker:
        broker.disconnect()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Perform clean-up when entry is being removed."""
    # Get access token from OAuth2 token or legacy access token
    if CONF_TOKEN in entry.data:
        access_token = entry.data[CONF_TOKEN][CONF_ACCESS_TOKEN]
    else:
        # Legacy entry with direct access token
        access_token = entry.data[CONF_ACCESS_TOKEN]
    
    api = SmartThings(async_get_clientsession(hass), access_token)

    # For OAuth entries, no app cleanup is needed
    if CONF_TOKEN in entry.data:
        _LOGGER.debug("OAuth entry removed, no app cleanup needed")
        return

    # Legacy entry cleanup - Remove the installed_app
    installed_app_id = entry.data[CONF_INSTALLED_APP_ID]
    try:
        await api.delete_installed_app(installed_app_id)
    except ClientResponseError as ex:
        if ex.status == HTTPStatus.FORBIDDEN:
            _LOGGER.debug(
                "Installed app %s has already been removed",
                installed_app_id,
                exc_info=True,
            )
        else:
            raise
    _LOGGER.debug("Removed installed app %s", installed_app_id)

    # Remove the app if not referenced by other entries, which if already
    # removed raises a HTTPStatus.FORBIDDEN error.
    all_entries = hass.config_entries.async_entries(DOMAIN)
    app_id = entry.data[CONF_APP_ID]
    app_count = sum(1 for entry in all_entries if entry.data[CONF_APP_ID] == app_id)
    if app_count > 1:
        _LOGGER.debug(
            "App %s was not removed because it is in use by other configuration entries",
            app_id,
        )
        return
    # Remove the app
    try:
        await api.delete_app(app_id)
    except ClientResponseError as ex:
        if ex.status == HTTPStatus.FORBIDDEN:
            _LOGGER.debug("App %s has already been removed", app_id, exc_info=True)
        else:
            raise
    _LOGGER.debug("Removed app %s", app_id)

    if len(all_entries) == 1:
        await unload_smartapp_endpoint(hass)


class DeviceBroker:
    """Manages an individual SmartThings config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        token,
        smart_app,
        devices: Iterable,
        scenes: Iterable,
    ):
        """Create a new instance of the DeviceBroker."""
        self._hass = hass
        self._entry = entry
        self._installed_app_id = entry.data.get(CONF_INSTALLED_APP_ID)
        self._smart_app = smart_app
        self._token = token
        self._event_disconnect = None
        self._regenerate_token_remove = None
        self._assignments = self._assign_capabilities(devices)
        self.devices = {device.device_id: device for device in devices}
        self.scenes = {scene.scene_id: scene for scene in scenes}

    def _assign_capabilities(self, devices: Iterable):
        """Assign platforms to capabilities."""
        assignments = {}
        for device in devices:
            capabilities = device.capabilities.copy()
            slots = {}
            for platform in PLATFORMS:
                platform_module = importlib.import_module(
                    f".{platform}", self.__module__
                )
                if not hasattr(platform_module, "get_capabilities"):
                    continue
                assigned = platform_module.get_capabilities(capabilities)
                if not assigned:
                    continue
                # Draw-down capabilities and set slot assignment
                for capability in assigned:
                    if capability not in capabilities:
                        continue
                    capabilities.remove(capability)
                    slots[capability] = platform
            assignments[device.device_id] = slots
        return assignments

    def connect(self):
        """Connect handlers/listeners for device/lifecycle events."""
        # Only setup token refresh for legacy entries
        if self._token and CONF_TOKEN not in self._entry.data:
            # Setup interval to regenerate the refresh token on a periodic basis.
            # Tokens expire in 30 days and once expired, cannot be recovered.
            async def regenerate_refresh_token(now):
                """Generate a new refresh token and update the config entry."""
                await self._token.refresh(
                    self._entry.data[CONF_CLIENT_ID],
                    self._entry.data[CONF_CLIENT_SECRET],
                )
                self._hass.config_entries.async_update_entry(
                    self._entry,
                    data={
                        **self._entry.data,
                        CONF_REFRESH_TOKEN: self._token.refresh_token,
                    },
                )
                _LOGGER.debug(
                    "Regenerated refresh token for installed app: %s",
                    self._installed_app_id or "OAuth entry",
                )

            self._regenerate_token_remove = async_track_time_interval(
                self._hass, regenerate_refresh_token, TOKEN_REFRESH_INTERVAL
            )

        # Connect handler to incoming device events (only for legacy SmartApp)
        if self._smart_app:
            self._event_disconnect = self._smart_app.connect_event(self._event_handler)

    def disconnect(self):
        """Disconnects handlers/listeners for device/lifecycle events."""
        if self._regenerate_token_remove:
            self._regenerate_token_remove()
        if self._event_disconnect:
            self._event_disconnect()

    def get_assigned(self, device_id: str, platform: str):
        """Get the capabilities assigned to the platform."""
        slots = self._assignments.get(device_id, {})
        return [key for key, value in slots.items() if value == platform]

    def any_assigned(self, device_id: str, platform: str):
        """Return True if the platform has any assigned capabilities."""
        slots = self._assignments.get(device_id, {})
        return any(value for value in slots.values() if value == platform)

    async def _event_handler(self, req, resp, app):
        """Broker for incoming events."""
        # Do not process events received from a different installed app
        # under the same parent SmartApp (valid use-scenario)
        # Skip this check for OAuth entries (no installed app id)
        if self._installed_app_id and req.installed_app_id != self._installed_app_id:
            return

        updated_devices = set()
        for evt in req.events:
            if evt.event_type != EVENT_TYPE_DEVICE:
                continue
            if not (device := self.devices.get(evt.device_id)):
                continue
            device.status.apply_attribute_update(
                evt.component_id,
                evt.capability,
                evt.attribute,
                evt.value,
                data=evt.data,
            )

            # Fire events for buttons
            if (
                evt.capability == Capability.button
                and evt.attribute == Attribute.button
            ):
                data = {
                    "component_id": evt.component_id,
                    "device_id": evt.device_id,
                    "location_id": evt.location_id,
                    "value": evt.value,
                    "name": device.label,
                    "data": evt.data,
                }
                self._hass.bus.async_fire(EVENT_BUTTON, data)
                _LOGGER.debug("Fired button event: %s", data)
            else:
                data = {
                    "location_id": evt.location_id,
                    "device_id": evt.device_id,
                    "component_id": evt.component_id,
                    "capability": evt.capability,
                    "attribute": evt.attribute,
                    "value": evt.value,
                    "data": evt.data,
                }
                _LOGGER.debug("Push update received: %s", data)

            updated_devices.add(device.device_id)

        async_dispatcher_send(self._hass, SIGNAL_SMARTTHINGS_UPDATE, updated_devices)


class SmartThingsEntity(Entity):
    """Defines a SmartThings entity."""

    def __init__(self, device: DeviceEntity) -> None:
        """Initialize the instance."""
        self._device = device
        self._dispatcher_remove = None

    async def async_added_to_hass(self):
        """Device added to hass."""

        async def async_update_state(devices):
            """Update device state."""
            if self._device.device_id in devices:
                await self.async_update_ha_state(True)

        self._dispatcher_remove = async_dispatcher_connect(
            self.hass, SIGNAL_SMARTTHINGS_UPDATE, async_update_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect the device when removed."""
        if self._dispatcher_remove:
            self._dispatcher_remove()

    @property
    def device_info(self):
        """Get attributes about the device."""
        if self._device.type == "OCF":
            model = self._device.status.attributes[Attribute.mnmo].value
            model = model.split("|")[0]
            return {
                "identifiers": {(DOMAIN, self._device.device_id)},
                "name": self._device.label,
                "model": model,
                "manufacturer": self._device.status.attributes[Attribute.mnmn].value,
                "sw_version": self._device.status.attributes[Attribute.mnfv].value,
            }
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.label,
            "model": self._device.device_type_name,
            "manufacturer": "Unavailable",
        }

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self._device.label

    @property
    def should_poll(self) -> bool:
        """No polling needed for this device."""
        return False

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._device.device_id
