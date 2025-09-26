from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from datetime import timedelta
from .const import DOMAIN
from .ssh_manager import get_ssh_manager
import logging
import asyncio

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
            entry.data.get("ssh_port", 22)
        )
        
        super().__init__(
            hass,
            _LOGGER,
            name=f"Aruba Switch {self.host}",
            update_interval=timedelta(seconds=refresh_interval),
        )
    
    async def _async_update_data(self):
        """Fetch live data from switch - no caching."""
        try:
            _LOGGER.debug("⏳ Starting coordinator data update for %s", self.host)
            # Get live data directly  
            data = await self.ssh_manager.get_current_data()
            
            if not data.get("available", False):
                _LOGGER.error("❌ Switch %s is offline or returned no data", self.host)
                raise UpdateFailed(f"Switch {self.host} is offline")
            
            _LOGGER.debug("✅ Coordinator data update completed for %s", self.host)
            # Return the actual switch data for entities to use
            return data
            
        except Exception as err:
            _LOGGER.error("❌ Coordinator update error for %s: %s", self.host, err)
            raise UpdateFailed(f"Error communicating with switch {self.host}: {err}")

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Aruba Switch component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Aruba Switch from a config entry."""
    _LOGGER.info("🚀 Starting Aruba Switch setup for %s", entry.data["host"])
    
    # Create and store the coordinator
    _LOGGER.info("📡 Creating coordinator for %s", entry.data["host"])
    coordinator = ArubaSwitchCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Fetch initial data with timeout
    _LOGGER.info("📊 Fetching initial data for %s", entry.data["host"])
    try:
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info("✅ Initial data fetch completed for %s", entry.data["host"])
    except asyncio.TimeoutError:
        _LOGGER.error("❌ Initial data fetch timed out after 60 seconds for %s", entry.data["host"])
        raise ConfigEntryNotReady(f"Switch {entry.data['host']} did not respond within timeout")

    # Set up switch platform
    _LOGGER.info("🔌 Setting up switch platform for %s", entry.data["host"]) 
    await hass.config_entries.async_forward_entry_setups(entry, ["switch", "sensor", "binary_sensor"])
    _LOGGER.info("✅ Switch platform setup completed for %s", entry.data["host"])
    
    # TEMPORARY: Debug setup hanging - disable sensors
    _LOGGER.warning("⚠️  TEMP DEBUG: Sensors disabled to test setup completion")
    
    # Add update listener for options flow
    _LOGGER.info("👂 Adding update listener for %s", entry.data["host"])
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    _LOGGER.info("✅ Update listener added for %s", entry.data["host"])
    
    _LOGGER.info("🎉 Aruba Switch setup COMPLETED successfully for %s", entry.data["host"])
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload config entry when options are updated."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # Only unload switch platform for now (sensors temporarily disabled)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch"])
    
    if unload_ok:
        # Remove the config entry from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
