"""Services for the ELRO Connects K2 integration.

``start_pairing`` reproduces the vendor app's add-device screen.  The hub is put
into a join window (CMD_CODE 2) and then the call simply waits: a detector only
joins when someone physically triggers its pairing action, so this is a
long-running interactive service, not a fire-and-forget one.  It returns a
response describing what joined and also fires ``elro_connects_k2_device_paired``
on the event bus so automations can react without owning the call.

Note that the app's device-type picker is purely cosmetic — the type is never
sent to the hub — so there is nothing to select here.  Whatever detector
completes pairing during the window is what gets added.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from elro_connects_k2_protocol.gateway import PAIRING_TIMEOUT_SECONDS
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util.json import JsonObjectType

from .const import DOMAIN
from .coordinator import ElroK2Coordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_START_PAIRING = "start_pairing"
SERVICE_CANCEL_PAIRING = "cancel_pairing"

EVENT_DEVICE_PAIRED = f"{DOMAIN}_device_paired"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_TIMEOUT = "timeout"

_BASE_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})

_START_PAIRING_SCHEMA = _BASE_SCHEMA.extend(
    {
        vol.Optional(ATTR_TIMEOUT, default=PAIRING_TIMEOUT_SECONDS): vol.All(
            vol.Coerce(float), vol.Range(min=10, max=300)
        )
    }
)


def _resolve_coordinator(hass: HomeAssistant, call: ServiceCall) -> ElroK2Coordinator:
    """Pick the gateway this call targets.

    ``config_entry_id`` may be omitted when there is exactly one gateway set up,
    which is the normal case — a K2 covers a whole house.
    """
    coordinators: dict[str, ElroK2Coordinator] = hass.data.get(DOMAIN, {})
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)

    if entry_id is not None:
        coordinator = coordinators.get(entry_id)
        if coordinator is None:
            raise ServiceValidationError(
                f"No loaded ELRO Connects K2 gateway with config entry id {entry_id}"
            )
        return coordinator

    if not coordinators:
        raise ServiceValidationError("No ELRO Connects K2 gateway is loaded")
    if len(coordinators) > 1:
        raise ServiceValidationError(
            "Multiple ELRO Connects K2 gateways are set up; "
            "pass config_entry_id to choose one"
        )
    return next(iter(coordinators.values()))


async def _async_start_pairing(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    coordinator = _resolve_coordinator(hass, call)
    gateway = coordinator.gateway
    timeout: float = call.data[ATTR_TIMEOUT]

    # The hub ignores APP_SEND until the session has been re-activated, and a
    # window that never opened looks exactly like one nothing joined during —
    # so re-activate first rather than debug a silent no-op later.
    await gateway.activate()

    _LOGGER.info("Opening pairing window on %s for %.0f s", gateway.device_name, timeout)
    result = await gateway.pair_new_device(timeout=timeout)

    if result is None:
        _LOGGER.info("Pairing window on %s closed with no new device", gateway.device_name)
        return {"paired": False}

    # The join frame carries a placeholder status (4 bars, 100 %), so pull real
    # signal/battery and the hub-stored nickname before reporting back.
    await coordinator.async_refresh()
    device = (coordinator.data or {}).get(result.device.sub_id, result.device)

    # JsonObjectType, not ServiceResponse: the latter is `JsonObjectType | None`,
    # which cannot be **-unpacked into the event payload below.
    response: JsonObjectType = {
        "paired": True,
        "sub_id": device.sub_id,
        "device_type": device.device_type,
        "name": device.nickname or device.profile.name,
        "model": ", ".join(device.profile.model_hints) or device.device_type,
        "already_known": result.already_known,
    }
    hass.bus.async_fire(
        EVENT_DEVICE_PAIRED, {"gateway": gateway.device_name, **response}
    )
    return response


async def _async_cancel_pairing(call: ServiceCall) -> None:
    _resolve_coordinator(call.hass, call).gateway.cancel_pairing()


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's services once, on first entry setup.

    Services are global rather than per-entry, so they are never unregistered —
    reloading one gateway must not tear them out from under another.
    """
    if hass.services.has_service(DOMAIN, SERVICE_START_PAIRING):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_PAIRING,
        _async_start_pairing,
        schema=_START_PAIRING_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_PAIRING,
        _async_cancel_pairing,
        schema=_BASE_SCHEMA,
    )
