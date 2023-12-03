"""Constants for the lg_netcast component."""
from datetime import timedelta
from typing import Final

ATTR_MANUFACTURER: Final = "LG"

DEFAULT_NAME: Final = "LG Netcast TV"

DOMAIN = "lg_netcast"


DISCOVERY_INTERVAL = timedelta(seconds=60)
SSDP_TARGET = ("239.255.255.250", 1900)
SSDP_ST = "urn:schemas-udap:service:netrcu:1"
DISCOVERY_ATTEMPTS = 3
DISCOVERY_SEARCH_INTERVAL = timedelta(seconds=2)
