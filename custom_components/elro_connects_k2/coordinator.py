"""DataUpdateCoordinator for the ELRO Connects K2 integration.

This coordinator is push-driven: update_interval is None so HA never polls
on a timer. Instead, the K2 gateway calls _handle_device_update every time
a CMD_CODE 19 push arrives, which calls async_set_updated_data immediately
to notify all subscribed entities without any delay.

The only periodic activity is the session-keepalive IOT_KEY? ping, which is
scheduled separately in __init__.py and does NOT update coordinator data.

A manual refresh (e.g. "Sync now" button) triggers _async_update_data, which
sends CMD_CODE 54 and collects the 55/56 response.
"""

from __future__ import annotations

import logging

from elro_connects_k2_protocol.gateway import K2Gateway
from elro_connects_k2_protocol.models import SubDevice, UpdateSource
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)


class ElroK2Coordinator(DataUpdateCoordinator[dict[int, SubDevice]]):
    """Coordinator that owns the K2Gateway instance and fans out updates to entities."""

    def __init__(self, hass: HomeAssistant, gateway: K2Gateway) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="ELRO Connects K2",
            update_interval=None,  # push-driven; no automatic polling
        )
        self.gateway = gateway

    async def _async_setup(self) -> None:
        """Register the push callback and open the UDP socket.

        Called once by the coordinator framework before the first data fetch.
        Data fetching happens in _async_update_data so there is only one sync
        on startup (the framework calls _async_update_data immediately after).
        """
        self.gateway.add_update_callback(self._handle_device_update)
        await self.gateway.connect()

    @callback
    def _handle_device_update(
        self, sub_id: int, device: SubDevice, source: UpdateSource
    ) -> None:
        """Called from the UDP receive loop on every CMD_CODE 19 push.

        The gateway library already logged the update with source=PUSH/POLL.
        Merge the new state and notify all subscribed entities immediately.
        """
        current = self.data or {}
        self.async_set_updated_data({**current, sub_id: device})

    async def _async_update_data(self) -> dict[int, SubDevice]:
        """Fetch all device state from the gateway.

        Called once on startup (by async_config_entry_first_refresh) and again
        on manual refresh (Sync now button). Re-activates the session first in
        case the K2 stopped responding after a keepalive gap.
        """
        activated = await self.gateway.activate()
        devices = await self.gateway.sync_devices()

        # An empty result is only believable when the hub acked activation: it
        # is then armed and genuinely reports no paired sub-devices, which is
        # the normal state of a new hub. Without that ack the hub may never
        # have armed, and an unarmed hub drops CMD_CODE 54 silently — so "no
        # devices" is indistinguishable from "not listening". Publishing that
        # as data would mark every existing entity unavailable and look like
        # the detectors vanished; failing the update says what actually
        # happened and keeps the last known state.
        if not activated and not devices:
            raise UpdateFailed(
                f"Gateway {self.gateway.ip} never acknowledged activation and returned "
                "no devices; it is unreachable or the configured device name is wrong"
            )

        return devices
