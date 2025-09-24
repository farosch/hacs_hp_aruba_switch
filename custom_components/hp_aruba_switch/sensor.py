"""Sensor entities for HP/Aruba Switch integration."""
import logging
import asyncio
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfInformation
from homeassistant.helpers.entity import Entity
from .const import DOMAIN
from .ssh_manager import get_ssh_manager

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch sensors from a config entry."""
    _LOGGER.debug("HP/Aruba Switch sensor integration starting setup")
    host = config_entry.data["host"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]
    ssh_port = config_entry.data.get("ssh_port", 22)
    # Get configured port count (default to 24 if not set)
    port_count = config_entry.data.get("port_count", 24)
    
    # Note: Activity sensors are created for ALL ports regardless of exclusion lists
    # This allows monitoring traffic even on ports that don't have control switches
    _LOGGER.debug(f"Creating activity sensors for all {port_count} ports (ignoring exclusion lists)")

    # Generate port list based on configured count
    ports = [str(i) for i in range(1, port_count + 1)]
    entities = []

    # Test SSH connectivity during setup
    ssh_manager = get_ssh_manager(host, username, password, ssh_port)
    test_result = await ssh_manager.execute_command("show version", timeout=10)
    _LOGGER.info(f"SSH connectivity test for sensors {host}: {'SUCCESS' if test_result else 'FAILED'}")

    for port in ports:
        # Add port activity sensor for ALL ports (exclusion lists don't apply to sensors)
        entities.append(ArubaPortActivitySensor(host, username, password, ssh_port, port, config_entry.entry_id))

    # Add a comprehensive switch diagnostic sensor
    entities.append(ArubaSwitchDiagnosticSensor(host, username, password, ssh_port, port_count, config_entry.entry_id))

    _LOGGER.debug(f"Created {len(entities)} activity sensors for all {len(ports)} ports (exclusion lists ignored for sensors)")
    # Add entities without immediate update to avoid overwhelming the switch during setup
    async_add_entities(entities, update_before_add=False)


class ArubaPortActivitySensor(SensorEntity):
    """Representation of an Aruba switch port activity sensor."""
    
    def __init__(self, host, username, password, ssh_port, port, entry_id):
        """Initialize the sensor."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._port = port
        self._entry_id = entry_id
        self._state = "unknown"
        self._available = True
        self._attr_name = f"Port {port} Activity"
        self._attr_unique_id = f"{host}_{port}_activity"
        self._attr_icon = "mdi:network"
        
        # Statistics attributes
        self._attr_extra_state_attributes = {
            "bytes_in": 0,
            "bytes_out": 0,
            "packets_in": 0,
            "packets_out": 0,
            "bytes_in_rate": 0,
            "bytes_out_rate": 0,
            "last_activity": "Never"
        }
        
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port)
        self._last_update = 0
        self._update_interval = 30  # Update every 30 seconds
        
        # Previous values for calculating rates
        self._prev_bytes_in = 0
        self._prev_bytes_out = 0
        self._prev_packets_in = 0
        self._prev_packets_out = 0
        self._prev_update_time = 0
        
        # Activity threshold (bytes per second to consider "active")
        self._activity_threshold = 1000  # 1KB/s
        
        # Stagger updates similar to switches, but with longer initial delay
        import hashlib
        import time
        offset_hash = hashlib.md5(f"activity_{port}".encode()).hexdigest()
        self._update_offset = 60 + (int(offset_hash[:2], 16) % 30)  # 60-90 second initial delay

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return self._attr_unique_id

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def available(self):
        """Return if entity is available."""
        return self._available

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "Aruba",
            "model": "Switch",
        }

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attr_extra_state_attributes

    async def async_update(self):
        """Update the sensor state."""
        import time
        current_time = time.time()
        
        # Skip update if entity is being removed
        if not self.enabled:
            return
        
        # Calculate time since last update with staggered offset
        time_since_update = current_time - (self._last_update + self._update_offset)
        
        # Only update if enough time has passed
        if time_since_update < self._update_interval:
            return
        
        self._last_update = current_time
        
        try:
            # Get port statistics with timeout protection
            stats = await asyncio.wait_for(
                self._ssh_manager.get_port_statistics(self._port),
                timeout=15
            )
            _LOGGER.debug(f"Port {self._port} statistics: {stats}")
            
            if stats:
                self._available = True
                
                # Extract current values
                current_bytes_in = stats.get("bytes_in", 0)
                current_bytes_out = stats.get("bytes_out", 0)
                current_packets_in = stats.get("packets_in", 0)
                current_packets_out = stats.get("packets_out", 0)
                
                # Calculate rates if we have previous data
                time_diff = current_time - self._prev_update_time if self._prev_update_time > 0 else 0
                
                if time_diff > 0 and self._prev_update_time > 0:
                    bytes_in_rate = max(0, (current_bytes_in - self._prev_bytes_in) / time_diff)
                    bytes_out_rate = max(0, (current_bytes_out - self._prev_bytes_out) / time_diff)
                    
                    # Update state based on activity
                    total_rate = bytes_in_rate + bytes_out_rate
                    if total_rate > self._activity_threshold:
                        self._state = "active"
                        self._attr_extra_state_attributes["last_activity"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        self._state = "idle"
                    
                    # Store rates
                    self._attr_extra_state_attributes["bytes_in_rate"] = round(bytes_in_rate, 2)
                    self._attr_extra_state_attributes["bytes_out_rate"] = round(bytes_out_rate, 2)
                else:
                    # First update, no rate calculation possible
                    self._attr_extra_state_attributes["bytes_in_rate"] = 0
                    self._attr_extra_state_attributes["bytes_out_rate"] = 0
                
                # Store current values
                self._attr_extra_state_attributes.update({
                    "bytes_in": current_bytes_in,
                    "bytes_out": current_bytes_out,
                    "packets_in": current_packets_in,
                    "packets_out": current_packets_out
                })
                
                # Store for next rate calculation
                self._prev_bytes_in = current_bytes_in
                self._prev_bytes_out = current_bytes_out
                self._prev_packets_in = current_packets_in
                self._prev_packets_out = current_packets_out
                self._prev_update_time = current_time
                
                _LOGGER.debug(f"Port {self._port} activity state: {self._state}, rates: in={self._attr_extra_state_attributes['bytes_in_rate']} B/s, out={self._attr_extra_state_attributes['bytes_out_rate']} B/s")
            else:
                self._available = False
                _LOGGER.debug(f"No statistics data received for port {self._port}")
                
        except asyncio.TimeoutError:
            _LOGGER.debug(f"Timeout updating statistics for {self._attr_name}")
            self._available = False
        except asyncio.CancelledError:
            _LOGGER.debug(f"Update cancelled for {self._attr_name}")
            # Don't mark as unavailable on cancellation, just skip this update
            raise
        except Exception as e:
            _LOGGER.warning(f"Failed to update {self._attr_name}: {e}")
            self._available = False


class ArubaSwitchDiagnosticSensor(SensorEntity):
    """Comprehensive diagnostic sensor showing all switch port information."""
    
    def __init__(self, host, username, password, ssh_port, port_count, entry_id):
        """Initialize the diagnostic sensor."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._port_count = port_count
        self._entry_id = entry_id
        self._state = "OK"
        self._available = True
        self._attr_name = f"Switch Diagnostics"
        self._attr_unique_id = f"{host}_diagnostics"
        self._attr_icon = "mdi:network-outline"
        
        # Comprehensive switch information
        self._attr_extra_state_attributes = {
            "total_ports": port_count,
            "ports_up": 0,
            "ports_enabled": 0,
            "total_bytes_in": 0,
            "total_bytes_out": 0,
            "total_packets_in": 0,
            "total_packets_out": 0,
            "last_update": "never",
            "port_details": {}
        }
        
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port)
        self._last_update = 0
        self._update_interval = 60  # Update every minute (less frequent for diagnostic)
        
        # Offset to prevent conflicts with other sensors
        self._update_offset = 30  # 30 second offset

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return self._attr_unique_id

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def available(self):
        """Return if entity is available."""
        return self._available

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "Aruba",
            "model": "Switch",
        }

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attr_extra_state_attributes

    async def async_update(self):
        """Update the diagnostic sensor with comprehensive switch information."""
        import time
        current_time = time.time()
        
        # Skip update if entity is being removed
        if not self.enabled:
            return
        
        # Calculate time since last update with offset
        time_since_update = current_time - (self._last_update + self._update_offset)
        
        # Only update if enough time has passed
        if time_since_update < self._update_interval:
            return
        
        self._last_update = current_time
        
        try:
            # Force a cache update to get fresh data
            await self._ssh_manager.update_bulk_cache()
            
            # Collect comprehensive port information
            ports_up = 0
            ports_enabled = 0
            total_bytes_in = 0
            total_bytes_out = 0
            total_packets_in = 0
            total_packets_out = 0
            port_details = {}
            
            for port_num in range(1, self._port_count + 1):
                port = str(port_num)
                
                # Get all data for each port
                status = await self._ssh_manager.get_port_status(port, False)
                statistics = await self._ssh_manager.get_port_statistics(port)
                link_details = await self._ssh_manager.get_port_link_status(port)
                
                # Count statistics
                if link_details.get("link_up", False):
                    ports_up += 1
                if status.get("port_enabled", False):
                    ports_enabled += 1
                
                # Sum traffic statistics
                bytes_in = statistics.get("bytes_in", 0)
                bytes_out = statistics.get("bytes_out", 0)
                packets_in = statistics.get("packets_in", 0)
                packets_out = statistics.get("packets_out", 0)
                
                total_bytes_in += bytes_in
                total_bytes_out += bytes_out
                total_packets_in += packets_in
                total_packets_out += packets_out
                
                # Store detailed port information
                port_details[f"port_{port}"] = {
                    "enabled": status.get("port_enabled", False),
                    "link_up": link_details.get("link_up", False),
                    "speed": link_details.get("link_speed", "unknown"),
                    "duplex": link_details.get("duplex", "unknown"),
                    "auto_neg": link_details.get("auto_negotiation", "unknown"),
                    "cable_type": link_details.get("cable_type", "unknown"),
                    "bytes_in": bytes_in,
                    "bytes_out": bytes_out,
                    "packets_in": packets_in,
                    "packets_out": packets_out
                }
            
            # Determine overall switch health
            if ports_up == 0:
                self._state = "NO_LINKS"
            elif ports_up < ports_enabled / 2:
                self._state = "DEGRADED"
            else:
                self._state = "OK"
            
            # Update attributes
            import datetime
            self._attr_extra_state_attributes.update({
                "total_ports": self._port_count,
                "ports_up": ports_up,
                "ports_enabled": ports_enabled,
                "total_bytes_in": total_bytes_in,
                "total_bytes_out": total_bytes_out,
                "total_packets_in": total_packets_in,
                "total_packets_out": total_packets_out,
                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "port_details": port_details
            })
            
            self._available = True
            _LOGGER.debug(f"Switch diagnostics updated: {ports_up}/{self._port_count} ports up, "
                        f"{ports_enabled} enabled, state: {self._state}")
                
        except asyncio.TimeoutError:
            _LOGGER.debug(f"Timeout updating diagnostics for {self._attr_name}")
            self._available = False
        except asyncio.CancelledError:
            _LOGGER.debug(f"Update cancelled for {self._attr_name}")
            raise
        except Exception as e:
            _LOGGER.warning(f"Failed to update {self._attr_name}: {e}")
            self._available = False