"""Config flow for the ELRO Connects K2 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from elro_connects_k2_protocol.gateway import discover_gateway
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point: try broadcast discovery first.

        Discovery binds UDP port 1025 for a short broadcast.  On macOS Docker
        or other environments where binding fails (port in use, no broadcast
        support), the exception is caught and the flow falls through to manual
        entry rather than crashing HA.
        """
        _LOGGER.debug("Config flow: attempting broadcast discovery")
        gateway = None
        try:
            gateway = await discover_gateway(timeout=5.0)
        except OSError as exc:
            _LOGGER.debug("Broadcast discovery failed (%s), falling back to manual entry", exc)

        if gateway is not None:
            await self.async_set_unique_id(gateway.device_name)
            self._abort_if_unique_id_configured()
            self._discovered = {
                CONF_HOST: gateway.ip,
                CONF_DEVICE_NAME: gateway.device_name,
            }
            return await self.async_step_confirm()

        return await self.async_step_manual()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User confirms an auto-discovered gateway."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"ELRO Connects K2 ({self._discovered[CONF_HOST]})",
                data=self._discovered,
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "host": self._discovered[CONF_HOST],
                "device_name": self._discovered[CONF_DEVICE_NAME],
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual IP + device name entry fallback."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_NAME])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"ELRO Connects K2 ({user_input[CONF_HOST]})",
                data=user_input,
            )

        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_MANUAL_SCHEMA,
            errors=errors,
        )
