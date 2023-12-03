"""Tests for LG Netcast TV."""
from datetime import timedelta
from unittest.mock import patch

from async_upnp_client.aiohttp import AiohttpSessionRequester
from async_upnp_client.const import AddressTupleVXType
from async_upnp_client.search import SsdpSearchListener
from async_upnp_client.utils import CaseInsensitiveDict
from pylgnetcast import AccessTokenError, LgNetCastClient, SessionIdError

from homeassistant.components.lg_netcast import scanner
from homeassistant.components.lg_netcast.scanner import LGNetCastScanner
from homeassistant.core import callback

FAIL_TO_BIND_IP = "1.2.3.4"

IP_ADDRESS = "192.168.1.239"
DEVICE_TYPE = "TV"
MODEL_NAME = "MockLGModelName"
UNIQUE_ID = "1234"
NETRCU_LOCATION = f"http://{IP_ADDRESS}:8080/udap/api/data?target=netrcu.xml"

CAPABILITIES = {
    "ST": "urn:schemas-udap:service:netrcu:1",
    "USN": f"uuid:{UNIQUE_ID}:urn:schememas-udap:service:netrcu:1",
    "location": NETRCU_LOCATION,
}

DEVICE_DESCRIPTION = f"""\
<?xml version="1.0" encoding="utf-8"?>
<envelope>
  <device>
    <deviceType>{DEVICE_TYPE}</deviceType>
    <modelName>{MODEL_NAME}</modelName>
    <friendlyName>LG Netcast Tester</friendlyName>
    <manufacturer>LG Electronics</manufacturer>
    <uuid>{UNIQUE_ID}</uuid>
  </device>
</envelope>
"""

FAKE_SESSION_ID = "987654321"
FAKE_PIN = "123456"

ADAPTERS_WITH_FAILING_CONFIG = [
    {
        "auto": True,
        "index": 1,
        "default": False,
        "enabled": True,
        "ipv4": [{"address": FAIL_TO_BIND_IP, "network_prefix": 23}],
        "ipv6": [],
        "name": "eth0",
    }
]


def _patched_ssdp_listener(info: CaseInsensitiveDict, *args, **kwargs):
    listener = SsdpSearchListener(*args, **kwargs)

    async def _async_callback():
        if kwargs["source"][0] == FAIL_TO_BIND_IP:
            raise OSError
        if listener.connect_callback is not None:
            listener.connect_callback()

    @callback
    def _async_search(override_target: AddressTupleVXType | None = None):
        if info:
            assert listener.async_callback is not None
            coro = listener.async_callback(info)
            listener.loop.create_task(coro)

    listener.async_start = _async_callback
    listener.async_search = _async_search
    return listener


def _patched_aiohttp_session_requester(
    resp: tuple[int, dict[str, str], str], *args, **kwargs
):
    requester = AiohttpSessionRequester(*args, **kwargs)

    async def _async_http_request(_method, _url, _headers=None, _body=None):
        if isinstance(resp, Exception):
            raise resp
        return resp

    requester.async_http_request = _async_http_request

    return requester


def _patched_lgnetcast_client(*args, session_error=False, **kwargs):
    client = LgNetCastClient(*args, **kwargs)

    def _get_fake_session_id():
        if not client.access_token:
            raise AccessTokenError("Fake Access Token Requested")
        if session_error:
            raise SessionIdError("Can not get session id from TV.")
        return FAKE_SESSION_ID

    client._get_session_id = _get_fake_session_id

    return client


def _patch_discovery(no_device=False, capabilities=None, response=None):
    LGNetCastScanner._scanner = None  # Clear class scanner to reset hass

    def _generate_fake_ssdp_listener(*args, **kwargs):
        info = None
        if not no_device:
            info = capabilities or CAPABILITIES
        return _patched_ssdp_listener(CaseInsensitiveDict(info), *args, **kwargs)

    def _generate_fake_requester(*args, **kwargs):
        resp: tuple[int, dict[str, str], str] = response or (
            200,
            {},
            DEVICE_DESCRIPTION,
        )
        return _patched_aiohttp_session_requester(resp, *args, **kwargs)

    return patch.multiple(
        "homeassistant.components.lg_netcast.scanner",
        SsdpSearchListener=_generate_fake_ssdp_listener,
        AiohttpSessionRequester=_generate_fake_requester,
    )


def _patch_discovery_interval():
    return patch.object(scanner, "DISCOVERY_SEARCH_INTERVAL", timedelta(seconds=0))


def _patch_lg_netcast(session_error: bool = False):
    def _generate_fake_lgnetcast_client(*args, **kwargs):
        return _patched_lgnetcast_client(*args, session_error=session_error, **kwargs)

    return patch(
        "homeassistant.components.lg_netcast.config_flow.LgNetCastClient",
        new=_generate_fake_lgnetcast_client,
    )
