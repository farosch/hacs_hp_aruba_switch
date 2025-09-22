from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Aruba Switch component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Aruba Switch from a config entry."""
    # Store the config entry data
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Forward the setup to both switch and fan platforms
    await hass.config_entries.async_forward_entry_setups(entry, ["switch", "fan"])
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # Unload both switch and fan platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch", "fan"])
    
    if unload_ok:
        # Remove the config entry from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
