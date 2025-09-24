from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN

# This integration only supports config entries, no YAML configuration
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Aruba Switch component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Aruba Switch from a config entry."""
    # Store the config entry data
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Set up switch platform first
    await hass.config_entries.async_forward_entry_setups(entry, ["switch"])
    
    # Add a small delay before setting up sensors to allow switch initialization
    import asyncio
    await asyncio.sleep(2)
    
    # Then set up sensor and binary_sensor platforms
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "binary_sensor"])
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # Unload switch, sensor, and binary_sensor platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch", "sensor", "binary_sensor"])
    
    if unload_ok:
        # Remove the config entry from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
