"""Sensor entities for HP/Aruba Switch integration using coordinator pattern."""
import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfInformation
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch sensors from a config entry."""
    _LOGGER.debug("HP/Aruba Switch sensor integration starting setup")
    
    # Get the coordinator from hass.data
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    # Get configured port count (default to 24 if not set)  
    port_count = config_entry.data.get("port_count", 24)
    
    _LOGGER.debug(f"Creating sensors for all {port_count} ports using coordinator")

    # Generate port list based on configured count
    ports = [str(i) for i in range(1, port_count + 1)]
    entities = []

    for port in ports:
        # Add essential sensors for each port
        entities.append(ArubaPortLinkStatusSensor(coordinator, port, config_entry.entry_id))
        entities.append(ArubaPortActivitySensor(coordinator, port, config_entry.entry_id))

    # Add switch info sensors
    entities.append(ArubaSwitchFirmwareSensor(coordinator, config_entry.entry_id))
    entities.append(ArubaSwitchModelSensor(coordinator, config_entry.entry_id))

    _LOGGER.debug(f"Created {len(entities)} sensors using coordinator pattern")
    async_add_entities(entities, update_before_add=False)


class ArubaPortLinkStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for port link status."""
    
    def __init__(self, coordinator, port, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._port = port
        self._entry_id = entry_id
        self._attr_name = f"Port {port} Link Status"
        self._attr_unique_id = f"{coordinator.host}_{port}_link_status"
        self._attr_icon = "mdi:ethernet"
        
    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return "unknown"
            
        # Get port data from coordinator live data
        interfaces = self.coordinator.data.get("interfaces", {})
        port_data = interfaces.get(str(self._port), {})
        if port_data:
            return "up" if port_data.get("link_up", False) else "down"
        return "unknown"
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success


class ArubaPortActivitySensor(CoordinatorEntity, SensorEntity):
    """Sensor for port activity status."""
    
    def __init__(self, coordinator, port, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._port = port
        self._entry_id = entry_id
        self._attr_name = f"Port {port} Activity"
        self._attr_unique_id = f"{coordinator.host}_{port}_activity"
        self._attr_icon = "mdi:network"
        
    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return "unknown"
            
        # Get port statistics from coordinator live data
        statistics = self.coordinator.data.get("statistics", {})
        port_stats = statistics.get(str(self._port), {})
        if port_stats:
            bytes_in = port_stats.get("bytes_in", 0)
            bytes_out = port_stats.get("bytes_out", 0)
            total_bytes = bytes_in + bytes_out
            
            if total_bytes > 1000:  # More than 1KB indicates activity
                return "active"
            else:
                return "idle"
        return "unknown"
        
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}
            
        port_data = self.coordinator.ssh_manager.get_port_status(self._port)
        if port_data:
            return {
                "bytes_rx": port_data.get("bytes_rx", 0),
                "bytes_tx": port_data.get("bytes_tx", 0),
                "packets_rx": port_data.get("unicast_rx", 0),
                "packets_tx": port_data.get("unicast_tx", 0),
            }
        return {}
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success


class ArubaSwitchFirmwareSensor(CoordinatorEntity, SensorEntity):
    """Sensor for switch firmware version."""
    
    def __init__(self, coordinator, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = f"Switch {coordinator.host} Firmware"
        self._attr_unique_id = f"{coordinator.host}_firmware"
        self._attr_icon = "mdi:chip"
        
    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return "unknown"
            
        # Get version data from coordinator live data
        version_data = self.coordinator.data.get("version_info", {})
        if version_data:
            return version_data.get("firmware_version", "unknown")
        return "unknown"
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success


class ArubaSwitchModelSensor(CoordinatorEntity, SensorEntity):
    """Sensor for switch model."""
    
    def __init__(self, coordinator, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = f"Switch {coordinator.host} Model"
        self._attr_unique_id = f"{coordinator.host}_model"
        self._attr_icon = "mdi:router-network"
        
    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return "unknown"
            
        # Get version data from coordinator live data
        version_data = self.coordinator.data.get("version_info", {})
        if version_data:
            return version_data.get("model", "unknown")
        return "unknown"
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success