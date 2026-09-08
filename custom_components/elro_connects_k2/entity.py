"""Shared device-registry plumbing for the ELRO Connects K2 platforms.

Every platform builds the same two device entries — the gateway itself and one
child device per sub-device — so the definitions live here instead of being
repeated per platform.

Child devices link to the gateway with ``via_device_id``, which takes the
gateway's device-registry id rather than its identifier tuple. The tuple form
(``via_device``) is deprecated in Home Assistant and removed in 2027.8; the id
is captured in ``async_setup_entry`` when the gateway device is registered and
kept on the coordinator as ``hub_device_id``.
"""

from __future__ import annotations

from elro_connects_k2_protocol.models import SubDevice
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import ElroK2Coordinator

GATEWAY_MODEL = "K2 (SF50GA)"


def gateway_device_info(gateway_name: str) -> DeviceInfo:
    """Device entry for the K2 gateway itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, gateway_name)},
        name=f"ELRO Connects K2 Gateway ({gateway_name})",
        manufacturer="ELRO Connects",
        model=GATEWAY_MODEL,
    )


def sub_device_info(
    coordinator: ElroK2Coordinator, sub_id: int, device: SubDevice
) -> DeviceInfo:
    """Device entry for one detector, linked to the gateway that reports it."""
    gateway_name = coordinator.gateway.device_name
    return DeviceInfo(
        identifiers={(DOMAIN, f"{gateway_name}_{sub_id}")},
        name=f"{device.profile.name} {sub_id}",
        manufacturer="ELRO Connects",
        model=", ".join(device.profile.model_hints) or device.device_type,
        via_device_id=coordinator.hub_device_id,
    )
