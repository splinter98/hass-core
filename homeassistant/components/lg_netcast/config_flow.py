"""Config flow to configure the LG Netcast TV integration."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pylgnetcast import AccessTokenError, LgNetCastClient, SessionIdError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE,
    CONF_HOST,
    CONF_ID,
    CONF_NAME,
)
from homeassistant.data_entry_flow import FlowResult
from homeassistant.util.network import is_host_valid

from .const import DEFAULT_NAME, DOMAIN, SSDP_ST
from .scanner import LGNetCastScanner


class LGNetCast(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LG Netcast TV integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self.client: LgNetCastClient | None = None
        self.device_config: dict[str, Any] = {}
        self._discovered_devices: dict[str, Any] = {}

    def create_client(self) -> None:
        """Create LG Netcast client from config."""
        host = self.device_config[CONF_HOST]
        access_token = self.device_config.get(CONF_ACCESS_TOKEN)
        self.client = LgNetCastClient(host, access_token)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not (host := user_input.get(CONF_HOST)):
                return await self.async_step_pick_device()
            if is_host_valid(host):
                self.device_config[CONF_HOST] = host
                return await self.async_step_authorize()

            errors[CONF_HOST] = "invalid_host"

        user_input = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Optional(CONF_HOST, default=user_input.get(CONF_HOST, "")): str}
            ),
            errors=errors,
        )

    async def async_step_pick_device(self, user_input=None):
        """Handle the step to pick discovered device."""
        if user_input is not None:
            unique_id = user_input[CONF_DEVICE]
            capabilities = self._discovered_devices[unique_id]
            await self.async_set_unique_id(unique_id, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            location: str = capabilities["location"]
            host = urlparse(location).hostname
            self.device_config[CONF_HOST] = host
            self.device_config[CONF_ID] = unique_id
            self.device_config[CONF_NAME] = capabilities["upnp"].get(
                "modelName", DEFAULT_NAME
            )
            return await self.async_step_authorize()

        configured_devices = {
            entry.data[CONF_ID]
            for entry in self._async_current_entries()
            if entry.data[CONF_ID]
        }
        devices_name = {}
        scanner = LGNetCastScanner.async_get(self.hass)
        devices = await scanner.async_discover()
        # Run 3 times as packages can get lost
        for capabilities in devices:
            if capabilities["ST"] != SSDP_ST:
                continue
            unique_id = capabilities["USN"].split(":")[1]
            if unique_id in configured_devices:
                continue
            location: str = capabilities["location"]
            host = urlparse(location).hostname
            model_name = capabilities["upnp"].get("modelName", DEFAULT_NAME)
            self._discovered_devices[unique_id] = capabilities
            devices_name[unique_id] = model_name

        if not devices_name:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): vol.In(devices_name)}),
        )

    async def async_step_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Authorize step."""
        errors: dict[str, str] = {}

        if user_input is not None and user_input.get(CONF_ACCESS_TOKEN) is not None:
            self.device_config[CONF_ACCESS_TOKEN] = user_input[CONF_ACCESS_TOKEN]

        self.create_client()
        assert self.client is not None

        try:
            await self.hass.async_add_executor_job(
                self.client._get_session_id  # pylint: disable=protected-access
            )
            return await self.async_create_device()
        except AccessTokenError:
            if user_input is not None:
                errors[CONF_ACCESS_TOKEN] = "invalid_access_token"
        except SessionIdError:
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="authorize",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ACCESS_TOKEN): vol.All(str, vol.Length(max=6)),
                }
            ),
            errors=errors,
        )

    async def async_create_device(self) -> FlowResult:
        """Create LG Netcast TV Device from config."""
        assert self.client

        if CONF_ID not in self.device_config:
            await self._async_handle_discovery_without_unique_id()
            assert CONF_NAME not in self.device_config
            self.device_config[CONF_NAME] = DEFAULT_NAME

        return self.async_create_entry(
            title=self.device_config[CONF_NAME], data=self.device_config
        )
