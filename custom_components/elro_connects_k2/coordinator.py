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
from elro_connects_k2_protocol.models import GatewayInfo, SubDevice, UpdateSource
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .issues import async_clear_hub_issue, async_report_hub_issue

_LOGGER = logging.getLogger(__name__)


class ElroK2Coordinator(DataUpdateCoordinator[dict[int, SubDevice]]):
    """Coordinator that owns the K2Gateway instance and fans out updates to entities."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, gateway: K2Gateway
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="ELRO Connects K2",
            config_entry=entry,
            update_interval=None,  # push-driven; no automatic polling
        )
        # Kept under our own name rather than reading self.config_entry back:
        # the base class types that as optional, and every use here needs a
        # ConfigEntry to key the repair issue by.
        self.entry = entry
        self.gateway = gateway
        # Last CMD_CODE 12 -> 13 answer, refreshed on every update. Carries the
        # hub's Wi-Fi SSID, which diagnostics reports because a hub on the wrong
        # network is a leading cause of "it never answers".
        self.gateway_info: GatewayInfo | None = None

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

        # Ask the hub about itself before asking what it owns. Two reasons.
        #
        # It is the vendor's own order: the app has no path that reaches a
        # status sync without a gateway-info reply having arrived first
        # (BlurWorker -> CMD_CODE 12, then MainFragment fires CMD_CODE 54 off
        # the CMD_CODE 13 event).
        #
        # More importantly it is the only question that does not depend on the
        # device table, which makes it the one signal that separates "this hub
        # is ignoring me" from "this hub genuinely has nothing paired". Those
        # two produce identical silence on a status sync: a K2 has no "nothing
        # to report" response — asked about a sub-device that does not exist, a
        # healthy hub answers with nothing at all — so an empty sync on its own
        # cannot tell them apart.
        info = await self.gateway.get_gateway_info()
        self.gateway_info = info
        if info is not None:
            # The SSID is the payoff for a support report. A hub on a different
            # Wi-Fi network or VLAN from Home Assistant is a common cause of
            # "it never answers", and until now the only source for that was
            # asking the owner — who reports what they configured, not what the
            # hub actually joined.
            _LOGGER.debug(
                "Gateway %s reports ssid=%r room=%s sub_device_push=%s",
                self.gateway.device_name, info.ssid, info.room_id, info.sub_device_push,
            )

        devices = await self.gateway.sync_devices()

        # "The hub was added and no entities appeared" is a report this
        # integration received, and the reason used to be visible only in a
        # debug log. Surface it in Settings > Repairs instead, split three ways
        # now that gateway-info makes the middle case distinguishable:
        #
        #   never acked a ping        -> unreachable, or the wrong device name
        #   acked, answers no command -> reachable but not processing commands
        #   answers, lists nothing    -> genuinely nothing paired
        #
        # Raised on the first empty result rather than after a run of them,
        # because this coordinator only refreshes on startup and on the Sync now
        # button — debouncing would mean the issue never appeared unless the
        # user pressed Sync twice.
        if not devices:
            async_report_hub_issue(
                self.hass, self.entry, activated=activated, answering=info is not None
            )
        else:
            async_clear_hub_issue(self.hass, self.entry)

        # An empty result is only believable from a hub that answered
        # gateway-info: it is then demonstrably processing commands and is
        # reporting an empty installation, which is the normal state of a new
        # hub. A hub that answered nothing may simply not be listening, and
        # publishing {} would mark every existing entity unavailable and look
        # like the detectors vanished. Failing the update says what actually
        # happened and keeps the last known state.
        if info is None and not devices:
            reason = (
                "never acknowledged activation and answered no commands; it is "
                "unreachable or the configured device name is wrong"
                if not activated
                else "acknowledged activation pings but answered no commands, so it "
                "is reachable but not processing them"
            )
            raise UpdateFailed(f"Gateway {self.gateway.ip} {reason}")

        return devices
