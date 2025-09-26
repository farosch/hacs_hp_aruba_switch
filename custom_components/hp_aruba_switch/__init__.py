from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from datetime import timedelta
from .const import DOMAIN
from .ssh_manager import get_ssh_manager
import logging

_LOGGER = logging.getLogger(__name__)

# This integration only supports config entries, no YAML configuration
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

class ArubaSwitchCoordinator(DataUpdateCoordinator):
    """Coordinator to manage single SSH session and update all entities."""
    
    def __init__(self, hass, entry):
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.host = entry.data["host"]
        refresh_interval = entry.data.get("refresh_interval", 30)
        
        # Initialize SSH manager
        self.ssh_manager = get_ssh_manager(
            entry.data["host"],
            entry.data["username"], 
            entry.data["password"],
            entry.data.get("ssh_port", 22),
            refresh_interval
        )
        
        super().__init__(
            hass,
            _LOGGER,
            name=f"Aruba Switch {self.host}",
            update_interval=timedelta(seconds=refresh_interval),
        )
    
    async def _async_update_data(self):
        """Fetch data from switch using single SSH session."""
        try:
            # Force a cache refresh to get latest data
            success = await self.ssh_manager.force_cache_refresh()
            if not success:
                raise UpdateFailed(f"Failed to fetch data from switch {self.host}")
            
            # Return success indicator - entities will read from cache
            return {"last_update": self.hass.loop.time()}
            
        except Exception as err:
            raise UpdateFailed(f"Error communicating with switch {self.host}: {err}")

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Aruba Switch component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Aruba Switch from a config entry."""
    # Create and store the coordinator
    coordinator = ArubaSwitchCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Set up switch platform
    await hass.config_entries.async_forward_entry_setups(entry, ["switch"])
    
    # Add a small delay before setting up sensors to allow switch initialization
    import asyncio
    await asyncio.sleep(2)
    
    # Then set up sensor and binary_sensor platforms
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "binary_sensor"])
    
    # Add update listener for options flow
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload config entry when options are updated."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # Unload switch, sensor, and binary_sensor platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch", "sensor", "binary_sensor"])
    
    if unload_ok:
        # Remove the config entry from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
