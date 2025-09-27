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
        # Add statistics sensors for bytes and packets
        entities.append(ArubaPortBytesInSensor(coordinator, port, config_entry.entry_id))
        entities.append(ArubaPortBytesOutSensor(coordinator, port, config_entry.entry_id))
        entities.append(ArubaPortPacketsInSensor(coordinator, port, config_entry.entry_id))
        entities.append(ArubaPortPacketsOutSensor(coordinator, port, config_entry.entry_id))

    # Add switch status sensor
    entities.append(ArubaSwitchStatusSensor(coordinator, config_entry.entry_id))

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
            
        # Get port link data from coordinator live data (link status is in link_details, not interfaces)
        link_details = self.coordinator.data.get("link_details", {})
        port_data = link_details.get(str(self._port), {})
        _LOGGER.debug(f"🔍 Link status sensor port {self._port}: link_details keys = {list(link_details.keys())}, port_data = {port_data}")
        if port_data:
            return "up" if port_data.get("link_up", False) else "down"
        return "unknown"
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "Aruba", 
            "model": "Switch",
        }


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
            
        # Get port statistics from coordinator live data (correct keys are bytes_rx/bytes_tx)
        statistics = self.coordinator.data.get("statistics", {})
        port_stats = statistics.get(str(self._port), {})
        _LOGGER.debug(f"🔍 Activity sensor port {self._port}: statistics keys = {list(statistics.keys())}, port_stats = {port_stats}")
        if port_stats:
            bytes_rx = port_stats.get("bytes_rx", 0)
            bytes_tx = port_stats.get("bytes_tx", 0)
            total_bytes = bytes_rx + bytes_tx
            
            if total_bytes > 1000:  # More than 1KB indicates activity
                return "active"
            else:
                return "idle"
        return "unknown"
        
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return {}
            
        statistics = self.coordinator.data.get("statistics", {})
        port_stats = statistics.get(self._port, {})
        if port_stats:
            return {
                "bytes_rx": port_stats.get("bytes_rx", 0),
                "bytes_tx": port_stats.get("bytes_tx", 0),
                "packets_rx": port_stats.get("unicast_rx", 0),
                "packets_tx": port_stats.get("unicast_tx", 0),
            }
        return {}
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "Aruba", 
            "model": "Switch",
        }


class ArubaSwitchStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for switch status (online/offline)."""
    
    def __init__(self, coordinator, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = f"Switch {coordinator.host} Status"
        self._attr_unique_id = f"{coordinator.host}_status"
        self._attr_icon = "mdi:lan-connect"
        
    @property
    def state(self):
        """Return the state of the sensor."""
        data = self.coordinator.data or {}
        if "available" in data:
            return "online" if data.get("available") else "offline"
        return "online" if self.coordinator.last_update_success else "offline"
        
    @property
    def available(self):
        """Return if entity is available."""
        # Status sensor is always available to show online/offline
        return True
        
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        data = self.coordinator.data or {}
        return {
            "host": self.coordinator.host,
            "last_successful_update": data.get("last_successful_connection"),
            "last_coordinator_refresh_success": self.coordinator.last_update_success,
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


class ArubaPortBytesInSensor(CoordinatorEntity, SensorEntity):
    """Sensor for port bytes received."""
    
    def __init__(self, coordinator, port, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._port = port
        self._entry_id = entry_id
        self._attr_name = f"Port {port} Bytes In"
        self._attr_unique_id = f"{coordinator.host}_{port}_bytes_in"
        self._attr_icon = "mdi:download"
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfInformation.BYTES
        
    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return None
            
        statistics = self.coordinator.data.get("statistics", {})
        port_stats = statistics.get(str(self._port), {})
        return port_stats.get("bytes_rx", 0)
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "Aruba", 
            "model": "Switch",
        }


class ArubaPortBytesOutSensor(CoordinatorEntity, SensorEntity):
    """Sensor for port bytes transmitted."""
    
    def __init__(self, coordinator, port, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._port = port
        self._entry_id = entry_id
        self._attr_name = f"Port {port} Bytes Out"
        self._attr_unique_id = f"{coordinator.host}_{port}_bytes_out"
        self._attr_icon = "mdi:upload"
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfInformation.BYTES
        
    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return None
            
        statistics = self.coordinator.data.get("statistics", {})
        port_stats = statistics.get(str(self._port), {})
        return port_stats.get("bytes_tx", 0)
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "Aruba", 
            "model": "Switch",
        }


class ArubaPortPacketsInSensor(CoordinatorEntity, SensorEntity):
    """Sensor for port packets received."""
    
    def __init__(self, coordinator, port, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._port = port
        self._entry_id = entry_id
        self._attr_name = f"Port {port} Packets In"
        self._attr_unique_id = f"{coordinator.host}_{port}_packets_in"
        self._attr_icon = "mdi:download"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        
    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return None
            
        statistics = self.coordinator.data.get("statistics", {})
        port_stats = statistics.get(str(self._port), {})
        return port_stats.get("unicast_rx", 0)
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "Aruba", 
            "model": "Switch",
        }


class ArubaPortPacketsOutSensor(CoordinatorEntity, SensorEntity):
    """Sensor for port packets transmitted."""
    
    def __init__(self, coordinator, port, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._port = port
        self._entry_id = entry_id
        self._attr_name = f"Port {port} Packets Out"
        self._attr_unique_id = f"{coordinator.host}_{port}_packets_out"
        self._attr_icon = "mdi:upload"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        
    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return None
            
        statistics = self.coordinator.data.get("statistics", {})
        port_stats = statistics.get(str(self._port), {})
        return port_stats.get("unicast_tx", 0)
        
    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "Aruba", 
            "model": "Switch",
        }