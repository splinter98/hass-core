"""The lg_netcast component."""

from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .scanner import LGNetCastScanner

PLATFORMS: Final[list[Platform]] = [Platform.MEDIA_PLAYER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up LG Netcast TVs."""
    # Make sure the scanner is always started in case we are
    # going to retry via ConfigEntryNotReady and the TV has changed
    # ip
    scanner = LGNetCastScanner.async_get(hass)
    await scanner.async_setup()

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up a config entry."""

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True
