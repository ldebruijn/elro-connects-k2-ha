"""ELRO Connects K2 Home Assistant integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from elro_connects_k2_protocol.gateway import K2Gateway
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_DEBUG_LOGGING,
    CONF_DEVICE_NAME,
    DOMAIN,
    KEEPALIVE_INTERVAL_SECONDS,
    PLATFORMS,
)
from .coordinator import ElroK2Coordinator
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

_PLATFORM_LIST = [Platform(p) for p in PLATFORMS]


def _apply_debug_logging(entry: ConfigEntry) -> None:
    """Set the protocol library logger level based on the integration option."""
    level = logging.DEBUG if entry.options.get(CONF_DEBUG_LOGGING, False) else logging.NOTSET
    logging.getLogger("elro_connects_k2_protocol").setLevel(level)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _apply_debug_logging(entry)

    gateway = K2Gateway(
        ip=entry.data[CONF_HOST],
        device_name=entry.data[CONF_DEVICE_NAME],
    )
    coordinator = ElroK2Coordinator(hass, gateway)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        _LOGGER.exception("Failed to connect to K2 gateway at %s", entry.data[CONF_HOST])
        return False

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Register the hub device so child devices can resolve their via_device reference.
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_DEVICE_NAME])},
        name=entry.data[CONF_DEVICE_NAME],
        manufacturer="ELRO Connects",
        model="K2 (SF50GA)",
    )

    # Session keepalive — send targeted IOT_KEY? every 60 s so the K2 keeps
    # accepting APP_SEND commands. This does NOT fetch state or update entities.
    async def _keepalive(_now: object) -> None:
        await gateway.activate()

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            _keepalive,
            timedelta(seconds=KEEPALIVE_INTERVAL_SECONDS),
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORM_LIST)

    async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change so the new logger level takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Disconnect the gateway (closes the UDP socket) before unloading platforms.
    # Doing it first maximises the time between socket close and the next
    # connect() call during a reload, reducing the EADDRINUSE window.
    coordinator: ElroK2Coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.gateway.disconnect()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORM_LIST)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
