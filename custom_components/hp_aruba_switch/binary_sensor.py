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

    # Add switch connectivity sensor
    entities.append(ArubaSwitchConnectivitySensor(coordinator, config_entry.entry_id))

    _LOGGER.debug(f"Created {len(entities)} binary sensors using coordinator pattern")
    async_add_entities(entities, update_before_add=False)


class ArubaSwitchConnectivitySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for switch connectivity status."""
    
    def __init__(self, coordinator, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = f"Switch {coordinator.host} Connectivity"
        self._attr_unique_id = f"{coordinator.host}_connectivity"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:lan-connect"
        
    @property
    def is_on(self):
        """Return true if the switch is connected."""
        return self.coordinator.last_update_success
        
    @property
    def available(self):
        """Return if entity is available."""
        # This sensor is always available - it shows connectivity status
        return True
        
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "host": self.coordinator.host,
            "last_update": self.coordinator.last_update_success if hasattr(self.coordinator, 'last_update_success') else "unknown",
        }
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "Aruba", 
            "model": "Switch",
        }