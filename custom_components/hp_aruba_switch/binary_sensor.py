"""Binary sensor entities for HP/Aruba Switch integration using coordinator pattern."""
import logging
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch binary sensors from a config entry."""
    _LOGGER.debug("HP/Aruba Switch binary sensor integration starting setup")
    
    # Get the coordinator from hass.data
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    entities = []

    # Status sensor moved to regular sensor platform
    # No binary sensors currently needed

    _LOGGER.debug(f"Created {len(entities)} binary sensors using coordinator pattern")
    async_add_entities(entities, update_before_add=False)


# Connectivity sensor moved to regular sensor platform as status sensor
# No binary sensors currently needed for this integration