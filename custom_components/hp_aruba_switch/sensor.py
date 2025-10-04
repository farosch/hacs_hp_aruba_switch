"""Sensor platform setup for HP/Aruba Switch integration (v2 architecture)."""
import asyncio
import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass  # type: ignore
from homeassistant.const import UnitOfInformation  # type: ignore
from homeassistant.helpers.restore_state import RestoreEntity  # type: ignore

from .const import DOMAIN
from .entity import ArubaSwitchEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch sensors from a config entry with dynamic entity creation."""
    _LOGGER.debug("HP/Aruba Switch sensor platform starting setup (v2 architecture)")
    
    # Get the coordinator from hass.data
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    # Wait for first coordinator refresh to detect ports
    if not coordinator.detected_ports:
        _LOGGER.debug("Waiting for port detection...")
        await coordinator.async_request_refresh()
        await asyncio.sleep(2)  # Give time for detection
    
    entities = []
    
    # Create switch status sensor (always present)
    entities.append(ArubaSwitchStatusSensor(coordinator, config_entry.entry_id))
    _LOGGER.debug("Created switch status sensor")
    
    # Create port sensors only for detected ports
    for port in sorted(coordinator.detected_ports, key=lambda x: int(x) if x.isdigit() else 999):
        # Create consolidated port sensor
        entities.append(ArubaPortSensor(coordinator, port, config_entry.entry_id))
        
        # Create dedicated traffic sensors for better statistics tracking
        entities.append(ArubaPortTrafficSensor(coordinator, port, config_entry.entry_id, "in"))
        entities.append(ArubaPortTrafficSensor(coordinator, port, config_entry.entry_id, "out"))
    
    _LOGGER.info(
        f"Created {len(entities)} sensor entities for {len(coordinator.detected_ports)} ports "
        f"({len(coordinator.poe_capable_ports)} PoE capable)"
    )
    
    # Add entities without waiting for update (coordinator already has data)
    async_add_entities(entities, update_before_add=False)
    
    # Register lazy loading for additional sensors after startup
    async def _lazy_load_additional_sensors():
        """Load additional optional sensors after initial setup."""
        await asyncio.sleep(10)  # Wait 10 seconds after startup
        # Could add more detailed sensors here if needed
        _LOGGER.debug("Lazy sensor loading completed")
    
    hass.async_create_task(_lazy_load_additional_sensors())


class ArubaPortSensor(ArubaSwitchEntity, SensorEntity, RestoreEntity):
    """Consolidated sensor for all port statistics and status."""
    
    def __init__(self, coordinator, port: str, entry_id: str):
        """Initialize the consolidated port sensor."""
        super().__init__(coordinator, entry_id)
        self._port = port
        self._attr_translation_key = "port_statistics"
        self._attr_name = f"Port {port}"
        self._attr_unique_id = f"aruba_switch_{coordinator.host.replace('.', '_')}_port_{port}_stats"
        self._attr_icon = "mdi:ethernet"
        
    async def async_added_to_hass(self):
        """Restore last state when added to hass."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()):
            _LOGGER.debug(f"Restored last state for port {self._port}: {last_state.state}")
    
    @property
    def native_value(self) -> str:
        """Return the main state: port operational status."""
        data = self._get_coordinator_data()
        if not data:
            return "unknown"
        
        link_details = data.get("link_details", {})
        port_data = link_details.get(self._port, {})
        
        # Determine status hierarchy: disabled > down > up
        if not port_data.get("port_enabled", False):
            return "disabled"
        elif not port_data.get("link_up", False):
            return "down"
        else:
            return "up"
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return comprehensive port statistics and details."""
        data = self._get_coordinator_data()
        if not data:
            return {}
        
        statistics = data.get("statistics", {})
        link_details = data.get("link_details", {})
        interfaces = data.get("interfaces", {})
        
        port_stats = statistics.get(self._port, {})
        port_link = link_details.get(self._port, {})
        port_interface = interfaces.get(self._port, {})
        
        attributes = {
            # Link status
            "port_enabled": port_link.get("port_enabled", False),
            "link_up": port_link.get("link_up", False),
            "link_speed": port_link.get("link_speed", "unknown"),
            "duplex": port_link.get("duplex", "unknown"),
            "auto_negotiation": port_link.get("auto_negotiation", "unknown"),
            "cable_type": port_link.get("cable_type", "unknown"),
            
            # Traffic statistics
            "bytes_in": port_stats.get("bytes_rx", 0),
            "bytes_out": port_stats.get("bytes_tx", 0),
            "packets_in": port_stats.get("unicast_rx", 0),
            "packets_out": port_stats.get("unicast_tx", 0),
            
            # Activity calculation
            "activity": self._calculate_activity(port_stats),
            
            # Link status from interface
            "link_status": port_interface.get("link_status", "unknown"),
        }
        
        return attributes
    
    def _calculate_activity(self, stats: Dict[str, Any]) -> str:
        """Calculate port activity based on traffic."""
        bytes_rx = stats.get("bytes_rx", 0)
        bytes_tx = stats.get("bytes_tx", 0)
        total_bytes = bytes_rx + bytes_tx
        
        if total_bytes == 0:
            return "idle"
        elif total_bytes < 1_000:  # < 1KB
            return "idle"
        elif total_bytes < 1_000_000:  # < 1MB
            return "low"
        elif total_bytes < 100_000_000:  # < 100MB
            return "medium"
        else:
            return "high"
    
    @property
    def icon(self) -> str:
        """Return dynamic icon based on port status."""
        data = self._get_coordinator_data()
        if not data:
            return "mdi:ethernet-off"
        
        link_details = data.get("link_details", {})
        port_data = link_details.get(self._port, {})
        
        if not port_data.get("port_enabled", False):
            return "mdi:ethernet-off"
        elif not port_data.get("link_up", False):
            return "mdi:ethernet-cable-off"
        else:
            # Show activity-based icon
            activity = self._calculate_activity(data.get("statistics", {}).get(self._port, {}))
            if activity in ["medium", "high"]:
                return "mdi:ethernet"
            else:
                return "mdi:ethernet-cable"


class ArubaSwitchStatusSensor(ArubaSwitchEntity, SensorEntity):
    """Sensor for overall switch status with firmware details."""
    
    def __init__(self, coordinator, entry_id: str):
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id)
        self._attr_translation_key = "switch_status"
        self._attr_name = f"Switch Status"
        self._attr_unique_id = f"aruba_switch_{coordinator.host.replace('.', '_')}_status"
        self._attr_icon = "mdi:lan-connect"
        
    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success:
            return "offline"

        data = self.coordinator.data or {}
        if "available" in data:
            return "online" if data.get("available") else "offline"

        return "online"
        
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Status sensor is always available to show online/offline
        return True
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return comprehensive switch information."""
        data = self.coordinator.data or {}
        version_info = data.get("version_info", {})
        
        attributes = {
            "host": self.coordinator.host,
            "last_successful_update": data.get("last_successful_connection"),
            "last_coordinator_refresh_success": self.coordinator.last_update_success,
        }
        
        # Add firmware/model info if available
        if version_info:
            attributes.update({
                "model": version_info.get("model", "Unknown"),
                "firmware_version": version_info.get("firmware_version", "Unknown"),
                "rom_version": version_info.get("rom_version", "Unknown"),
                "serial_number": version_info.get("serial_number", "Unknown"),
            })
        
        return attributes


class ArubaPortTrafficSensor(ArubaSwitchEntity, SensorEntity):
    """Dedicated sensor for port traffic with proper data size handling."""
    
    def __init__(self, coordinator, port: str, entry_id: str, direction: str):
        """Initialize the traffic sensor.
        
        Args:
            direction: Either 'in' or 'out' for bytes received/transmitted
        """
        super().__init__(coordinator, entry_id)
        self._port = port
        self._direction = direction
        self._attr_translation_key = f"port_bytes_{direction}"
        self._attr_name = f"Port {port} Traffic {'In' if direction == 'in' else 'Out'}"
        self._attr_unique_id = f"aruba_switch_{coordinator.host.replace('.', '_')}_port_{port}_bytes_{direction}"
        self._attr_icon = "mdi:download" if direction == "in" else "mdi:upload"
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfInformation.BYTES
        self._attr_suggested_display_precision = 0
        self._attr_suggested_unit_of_measurement = UnitOfInformation.MEGABYTES
        
    @property
    def native_value(self) -> Optional[int]:
        """Return bytes received or transmitted."""
        data = self._get_coordinator_data()
        if not data:
            return None
            
        statistics = data.get("statistics", {})
        port_stats = statistics.get(self._port, {})
        
        if self._direction == "in":
            return port_stats.get("bytes_rx", 0)
        else:
            return port_stats.get("bytes_tx", 0)
