"""Define tests for the LG Netcast config flow."""
import asyncio
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest

from homeassistant import data_entry_flow
from homeassistant.components.lg_netcast.const import DEFAULT_NAME, DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE,
    CONF_HOST,
    CONF_ID,
    CONF_NAME,
)
from homeassistant.core import HomeAssistant

from . import (
    ADAPTERS_WITH_FAILING_CONFIG,
    DEVICE_DESCRIPTION,
    FAIL_TO_BIND_IP,
    FAKE_PIN,
    IP_ADDRESS,
    MODEL_NAME,
    NETRCU_LOCATION,
    UNIQUE_ID,
    _patch_discovery,
    _patch_discovery_interval,
    _patch_lg_netcast,
)

from tests.common import MockConfigEntry


async def test_show_form(hass: HomeAssistant) -> None:
    """Test that the form is served with no input."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_invalid_host(hass: HomeAssistant) -> None:
    """Test that errors are shown when the host is invalid."""
    with _patch_lg_netcast():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: "invalid/host"}
        )

        assert result["errors"] == {CONF_HOST: "invalid_host"}


async def test_discover_no_device(hass: HomeAssistant) -> None:
    """Test discover devices."""
    with _patch_discovery(no_device=True), _patch_discovery_interval():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: ""}
        )

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"


async def test_discover_devices(hass: HomeAssistant) -> None:
    """Test discovery with no available devices."""
    with _patch_discovery(), _patch_discovery_interval():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: ""}
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "pick_device"
        assert not result["errors"]

    with _patch_lg_netcast():
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE: UNIQUE_ID}
        )
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "authorize"
        assert not result2["errors"]

        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ACCESS_TOKEN: FAKE_PIN}
        )

        assert result3["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result3["title"] == MODEL_NAME
        assert result3["data"] == {
            CONF_ID: UNIQUE_ID,
            CONF_HOST: IP_ADDRESS,
            CONF_NAME: MODEL_NAME,
            CONF_ACCESS_TOKEN: FAKE_PIN,
        }


async def test_manual_host(hass: HomeAssistant) -> None:
    """Test manual host configuration."""
    with _patch_lg_netcast():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: IP_ADDRESS}
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "authorize"
        assert not result["errors"]

        result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "authorize"
        assert result2["errors"] is not None
        assert result2["errors"][CONF_ACCESS_TOKEN] == "invalid_access_token"

        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ACCESS_TOKEN: FAKE_PIN}
        )

        assert result3["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result3["title"] == DEFAULT_NAME
        assert result3["data"] == {
            CONF_HOST: IP_ADDRESS,
            CONF_ACCESS_TOKEN: FAKE_PIN,
            CONF_NAME: DEFAULT_NAME,
        }


async def test_invalid_session_id(hass: HomeAssistant) -> None:
    """Test Invalid Session ID."""
    with _patch_lg_netcast(session_error=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: IP_ADDRESS}
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "authorize"
        assert not result["errors"]

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ACCESS_TOKEN: FAKE_PIN}
        )

        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "authorize"
        assert result2["errors"] is not None
        assert result2["errors"]["base"] == "cannot_connect"


async def test_invalid_ssdp_st(hass: HomeAssistant) -> None:
    """Test invalid SSDP returned."""
    capabilities = {
        "ST": "invalid_ssdp_st",
        "USN": f"uuid:{UNIQUE_ID}:urn:schememas-udap:service:netrcu:1",
        "location": f"http://{IP_ADDRESS}:8080/udap/api/data?target=netrcu.xml",
    }
    with _patch_discovery(capabilities=capabilities), _patch_discovery_interval():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: ""}
        )

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"


async def test_discover_existing_devices(hass: HomeAssistant) -> None:
    """Test Already configured devices are ignored."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ID: UNIQUE_ID,
            CONF_HOST: IP_ADDRESS,
            CONF_NAME: MODEL_NAME,
            CONF_ACCESS_TOKEN: FAKE_PIN,
        },
        unique_id=UNIQUE_ID,
    )

    config_entry.add_to_hass(hass)

    with _patch_discovery(), _patch_discovery_interval():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: ""}
        )

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"


async def test_setup_with_invalid_adapters(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
):
    """Test setting up TV with an adapter that fails to bind."""
    with _patch_discovery(), _patch_discovery_interval(), patch(
        "homeassistant.components.network.async_get_adapters",
        return_value=ADAPTERS_WITH_FAILING_CONFIG,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: ""}
        )

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"
        assert f"Failed to setup listener for ('{FAIL_TO_BIND_IP}', 0)" in caplog.text


@pytest.mark.parametrize(
    ("response", "log_message"),
    [
        ((404, {}, ""), None),
        ((200, {}, ""), None),
        ((200, {}, "invalid"), None),
        ((200, {}, DEVICE_DESCRIPTION.replace("envelope", "root")), None),
        (aiohttp.ClientError(), f"Error fetching {NETRCU_LOCATION}:"),
        (asyncio.TimeoutError(), f"Error fetching {NETRCU_LOCATION}:"),
    ],
)
async def test_invalid_description_responses(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    response: tuple[int, dict[str, Any], None | str] | Exception,
    log_message: str | None,
):
    """Test setup when description response status is not 200."""
    with _patch_discovery(response=response), _patch_discovery_interval():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: ""}
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "pick_device"
        assert not result["errors"]

    with _patch_lg_netcast():
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE: UNIQUE_ID}
        )
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "authorize"
        assert not result2["errors"]

        result3 = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result3["type"] == data_entry_flow.FlowResultType.FORM
        assert result3["step_id"] == "authorize"
        assert result3["errors"] is not None
        assert result3["errors"][CONF_ACCESS_TOKEN] == "invalid_access_token"

        result4 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ACCESS_TOKEN: FAKE_PIN}
        )

        assert result4["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result4["title"] == DEFAULT_NAME
        assert result4["data"] == {
            CONF_ID: UNIQUE_ID,
            CONF_HOST: IP_ADDRESS,
            CONF_NAME: DEFAULT_NAME,
            CONF_ACCESS_TOKEN: FAKE_PIN,
        }

        if log_message:
            assert log_message in caplog.text
