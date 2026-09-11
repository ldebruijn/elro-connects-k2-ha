"""Diagnostics support for the ELRO Connects K2 integration."""

from __future__ import annotations

from typing import Any

from elro_connects_k2_protocol.transport import shared_socket_is_open
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ElroK2Coordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    coordinator: ElroK2Coordinator = hass.data[DOMAIN][entry.entry_id]
    gateway = coordinator.gateway

    devices_info: dict[str, Any] = {}
    for sub_id, device in (coordinator.data or {}).items():
        devices_info[str(sub_id)] = {
            "sub_id": device.sub_id,
            "raw_type": device.raw_type,
            "device_type": device.device_type,
            "profile_name": device.profile.name,
            "signal_bars": device.signal_bars,
            "battery_pct": device.battery_pct,
            "alarm_state": device.alarm_state.name,
            "raw_status": device.raw_status,
            "co2_ppm": device.co2_ppm,
            "temperature_c": device.temperature_c,
            "humidity_pct": device.humidity_pct,
        }

    # What the hub says about itself, from the CMD_CODE 12 exchange the
    # coordinator runs before each sync. The SSID is the point: a hub on a
    # different Wi-Fi network or VLAN from Home Assistant is a leading cause of
    # "it never answers", and this is the only place that fact comes from the
    # hub rather than from the owner's description of their network.
    # None means the hub answered no command on the last refresh, which is
    # itself the most important line in the report.
    info = coordinator.gateway_info

    return {
        "gateway": {
            "ip": gateway.ip,
            "device_name": gateway.device_name,
            "answered_gateway_info": info is not None,
            "ssid": info.ssid if info else None,
            "room_id": info.room_id if info else None,
            "sub_device_push": info.sub_device_push if info else None,
            "raw_data_str1": info.raw_data_str1 if info else None,
            "raw_data_str2": info.raw_data_str2 if info else None,
        },
        # Multi-hub setups share one UDP socket on port 1025, keyed by devID.
        # A report where one hub sees nothing is nearly always a transport
        # problem, so say up front how many hubs are loaded and whether the
        # socket they share is actually bound.
        "transport": {
            "gateways_loaded": len(hass.data.get(DOMAIN, {})),
            "shared_socket_open": shared_socket_is_open(),
        },
        "devices": devices_info,
    }
