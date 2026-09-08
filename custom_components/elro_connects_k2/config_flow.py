"""Config flow for the ELRO Connects K2 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from elro_connects_k2_protocol.gateway import K2Gateway, discover_gateways
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST

from .const import CONF_DEBUG_LOGGING, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_MANUAL_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_DEVICE_NAME): str,
})

# Sentinel option in the picker, so a hub that answered the broadcast from an
# address Home Assistant cannot reach is not a dead end.
PICK_MANUAL = "__manual__"


class ElroK2OptionsFlow(OptionsFlow):
    """Options flow: toggles debug logging for the protocol library."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(CONF_DEBUG_LOGGING, False)
        schema = vol.Schema({
            vol.Required(CONF_DEBUG_LOGGING, default=current): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema)


class ElroK2ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> ElroK2OptionsFlow:
        return ElroK2OptionsFlow()

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}
        # devID -> IP for every hub that answered and is not already set up
        self._candidates: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point: broadcast for hubs, then offer whichever are not set up yet.

        Discovery runs over the protocol library's shared socket, so it no
        longer conflicts with gateways this Home Assistant already has
        connected. On hosts where binding UDP 1025 fails outright (macOS
        Docker, or something else holding the port) the exception is caught and
        the flow falls through to manual entry rather than crashing.

        A home can have several K2 hubs — they are independent installations,
        not a mesh — so all of them are offered, minus the ones already added.
        """
        _LOGGER.debug("Config flow: attempting broadcast discovery")
        gateways: list[K2Gateway] = []
        try:
            gateways = await discover_gateways(timeout=5.0)
        except OSError as exc:
            _LOGGER.debug("Broadcast discovery failed (%s), falling back to manual entry", exc)

        # Public API rather than the _async_current_ids() helper most core
        # flows reach for: the unique id of an entry is the hub's devID, which
        # is exactly the key discovery reports back.
        configured = {
            entry.unique_id for entry in self.hass.config_entries.async_entries(DOMAIN)
        }
        self._candidates = {
            gw.device_name: gw.ip
            for gw in gateways
            if gw.device_name not in configured
        }
        _LOGGER.debug(
            "Config flow: %d hub(s) answered, %d not yet configured",
            len(gateways), len(self._candidates),
        )

        if not self._candidates:
            return await self.async_step_manual()

        if len(self._candidates) == 1:
            device_name, host = next(iter(self._candidates.items()))
            self._discovered = {CONF_HOST: host, CONF_DEVICE_NAME: device_name}
            return await self.async_step_confirm()

        return await self.async_step_pick()

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose between several discovered hubs.

        One entry is created per hub. Re-running the flow offers whatever is
        left, which is how the second hub in a house gets added.
        """
        if user_input is not None:
            choice = user_input[CONF_DEVICE_NAME]
            if choice == PICK_MANUAL:
                return await self.async_step_manual()
            self._discovered = {
                CONF_HOST: self._candidates[choice],
                CONF_DEVICE_NAME: choice,
            }
            return await self.async_step_confirm()

        options = {
            device_name: f"{device_name} ({host})"
            for device_name, host in sorted(self._candidates.items())
        }
        options[PICK_MANUAL] = "Enter a gateway manually"
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_NAME): vol.In(options)}),
            description_placeholders={"count": str(len(self._candidates))},
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer one discovered gateway, or a way past it to manual entry.

        A menu rather than a plain confirmation because discovery answers only
        for hubs the broadcast reaches. Someone with a hub on another VLAN would
        otherwise have to add the discovered one first just to be offered the
        manual form on a second run, and could never add the far hub at all if
        the near one was already set up.
        """
        del user_input  # the menu carries the choice; there is no form to read
        return self.async_show_menu(
            step_id="confirm",
            menu_options=["confirm_add", "manual"],
            description_placeholders={
                "host": self._discovered[CONF_HOST],
                "device_name": self._discovered[CONF_DEVICE_NAME],
            },
        )

    async def async_step_confirm_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry for the gateway offered by ``async_step_confirm``."""
        del user_input
        await self.async_set_unique_id(self._discovered[CONF_DEVICE_NAME])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"ELRO Connects K2 ({self._discovered[CONF_HOST]})",
            data=self._discovered,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual IP + device name entry fallback.

        Unlike the discovered path, nothing here has been confirmed by a hub, so
        the details are checked before an entry is created. A typo used to
        produce an entry that loaded, created no entities, and raised a repair
        issue after the fact. With several hubs configured that is worse: frames
        naming a devID no gateway is registered for are dropped, so the mistyped
        hub goes completely silent while its neighbour keeps working -- which
        looks exactly like "the integration only picks up one of my hubs".
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_NAME])
            self._abort_if_unique_id_configured()

            if await self._hub_answers(
                user_input[CONF_HOST], user_input[CONF_DEVICE_NAME]
            ):
                return self.async_create_entry(
                    title=f"ELRO Connects K2 ({user_input[CONF_HOST]})",
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            # Hand back what was typed, so correcting one character in a devID
            # does not mean retyping the IP address as well.
            data_schema=self.add_suggested_values_to_schema(
                STEP_MANUAL_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def _hub_answers(self, host: str, device_name: str) -> bool:
        """Whether a hub at ``host`` acknowledges being called ``device_name``.

        The hub names *itself* in the NODE_ACK it answers a targeted IOT_KEY?
        with, and the protocol library drops frames naming a devID it has no
        gateway registered for -- so this comes back false for a wrong address
        and for a wrong device name alike.

        Safe to run while other hubs are loaded: since library 0.2.0 every
        gateway shares one socket on port 1025 instead of binding its own, so
        this no longer takes inbound traffic away from a live entry for as long
        as it runs.
        """
        gateway = K2Gateway(ip=host, device_name=device_name)
        try:
            await gateway.connect()
        except OSError as exc:
            _LOGGER.debug("Manual entry: could not open UDP port 1025 (%s)", exc)
            return False
        try:
            return gateway.activated
        finally:
            await gateway.disconnect()
