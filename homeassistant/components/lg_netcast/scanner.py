"""Support for LG Netcast TVs."""
from __future__ import annotations

import asyncio
from collections.abc import ValuesView
from datetime import datetime
from ipaddress import IPv4Address
import logging
from typing import Any, Self
from urllib.parse import urlparse

import aiohttp
from aiohttp.hdrs import USER_AGENT
from async_upnp_client.aiohttp import AiohttpSessionRequester
from async_upnp_client.search import SsdpSearchListener
from async_upnp_client.utils import CaseInsensitiveDict, etree_to_dict
import defusedxml.ElementTree as DET

from homeassistant.components import network
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DISCOVERY_ATTEMPTS, DISCOVERY_SEARCH_INTERVAL, SSDP_ST, SSDP_TARGET

_LOGGER = logging.getLogger(__name__)


class LGNetCastScanner:
    """Scan for LG NetCast devices."""

    _scanner: Self | None = None

    @classmethod
    @callback
    def async_get(cls, hass: HomeAssistant) -> LGNetCastScanner:
        """Get scanner instance."""
        if cls._scanner is None:
            cls._scanner = cls(hass)

        return cls._scanner

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize class."""
        self._hass = hass
        self._unique_id_capabilties: dict[str, dict[str, Any]] = {}
        self._host_capabilities: dict[str, CaseInsensitiveDict] = {}
        self._listeners: list[SsdpSearchListener] = []
        self._connected_events: list[asyncio.Event] = []
        self._requester: AiohttpSessionRequester | None = None

    async def async_discover(self) -> ValuesView[dict[str, Any]]:
        """Discover TVs."""
        _LOGGER.debug("LG Netcast discover with interval %s", DISCOVERY_SEARCH_INTERVAL)
        await self.async_setup()
        for _ in range(DISCOVERY_ATTEMPTS):
            self.async_scan()
            await asyncio.sleep(DISCOVERY_SEARCH_INTERVAL.total_seconds())
        return self._unique_id_capabilties.values()

    async def async_setup(self) -> None:
        """Set up the scanner."""
        if self._connected_events:
            await self._async_wait_connected()
            return

        session = async_get_clientsession(self._hass, verify_ssl=False)
        self._requester = AiohttpSessionRequester(
            session,
            with_sleep=True,
            timeout=10,
            http_headers={USER_AGENT: "UDAP/2.0"},
        )

        def _wrap_idx_async_connected(idx):
            @callback
            def _async_connected() -> None:
                self._connected_events[idx].set()

            return _async_connected

        for idx, source_ip in enumerate(await self._async_build_source_set()):
            self._connected_events.append(asyncio.Event())

            source = (str(source_ip), 0)
            self._listeners.append(
                SsdpSearchListener(
                    async_callback=self._async_process_entry,
                    search_target=SSDP_ST,
                    target=SSDP_TARGET,
                    source=source,
                    connect_callback=_wrap_idx_async_connected(idx),
                )
            )

        results = await asyncio.gather(
            *(listener.async_start() for listener in self._listeners),
            return_exceptions=True,
        )
        failed_listeners: list[SsdpSearchListener] = []
        for idx, result in enumerate(results):
            if not isinstance(result, Exception):
                continue
            _LOGGER.warning(
                "Failed to setup listener for %s: %s",
                self._listeners[idx].source,
                result,
            )
            failed_listeners.append(self._listeners[idx])
            self._connected_events[idx].set()

        for listener in failed_listeners:
            self._listeners.remove(listener)

        await self._async_wait_connected()
        self.async_scan()

    @callback
    def async_scan(self, _: datetime | None = None) -> None:
        """Send discovery packets."""
        _LOGGER.debug("LG Netcast scanning")
        for listener in self._listeners:
            listener.async_search()

    async def _async_wait_connected(self):
        """Wait for the listeners to be up and connected."""
        await asyncio.gather(*(event.wait() for event in self._connected_events))

    async def _async_build_source_set(self) -> set[IPv4Address]:
        """Build the list of ssdp sources."""
        adapters = await network.async_get_adapters(self._hass)
        if network.async_only_default_interface_enabled(adapters):
            return {IPv4Address("0.0.0.0")}

        return {
            source_ip
            for source_ip in await network.async_get_enabled_source_ips(self._hass)
            if isinstance(source_ip, IPv4Address) and not source_ip.is_loopback
        }

    @callback
    async def _async_process_entry(self, headers: CaseInsensitiveDict) -> None:
        """Process a discovery."""
        _LOGGER.debug("Discovered via SSDP: %s", headers)
        unique_id = headers["USN"].split(":")[1]
        location: str = headers["location"]
        host = urlparse(location).hostname
        assert host
        current_entry = self._unique_id_capabilties.get(unique_id)
        if current_entry:
            location = current_entry["location"]
        info_desc = await self._async_get_description_dict(location) or {}
        # Make sure we handle ip changes
        if not current_entry or host != urlparse(location).hostname:
            _LOGGER.debug("LG Netcast TV discovered with %s", headers)
        self._host_capabilities[host] = headers
        self._unique_id_capabilties[unique_id] = {
            **headers.as_dict(),
            "upnp": info_desc,
        }

    async def _async_get_description_dict(self, location: str) -> dict[str, Any] | None:
        """Get description dict."""
        assert self._requester is not None

        try:
            status, _headers, body = await self._requester.async_http_request(
                "GET", location
            )
            if status != 200:
                return None
            description_xml = body
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug("Error fetching %s: %s", location, err)
            return None
        if not description_xml:
            return None
        try:
            tree = DET.fromstring(description_xml)
        except DET.ParseError as err:
            _LOGGER.debug("Error parsing %s: %s", description_xml, err)
            return None

        envelope = etree_to_dict(tree).get("envelope")
        if envelope is None:
            return None

        return envelope.get("device")
