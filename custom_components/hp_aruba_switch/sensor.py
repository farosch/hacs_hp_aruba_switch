"""Sensor entities for HP/Aruba Switch integration."""
import logging
import asyncio
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfInformation
from homeassistant.helpers.entity import Entity
from .const import DOMAIN, CONF_REFRESH_INTERVAL
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
    refresh_interval = config_entry.data.get("refresh_interval", 30)
    
    # Note: Activity sensors are created for ALL ports regardless of exclusion lists
    # This allows monitoring traffic even on ports that don't have control switches
    _LOGGER.debug(f"Creating activity sensors for all {port_count} ports (ignoring exclusion lists)")

    # Generate port list based on configured count
    ports = [str(i) for i in range(1, port_count + 1)]
    entities = []

    # Test SSH connectivity during setup
    ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
    test_result = await ssh_manager.execute_command("show version", timeout=10)
    _LOGGER.info(f"SSH connectivity test for sensors {host}: {'SUCCESS' if test_result else 'FAILED'}")

    for port in ports:
        # Add port activity sensor for ALL ports (exclusion lists don't apply to sensors)
        entities.append(ArubaPortActivitySensor(host, username, password, ssh_port, port, config_entry.entry_id, refresh_interval))
        
        # Add individual statistic sensors for each port
        entities.append(ArubaPortBytesSensor(host, username, password, ssh_port, port, config_entry.entry_id, "in", refresh_interval))
        entities.append(ArubaPortBytesSensor(host, username, password, ssh_port, port, config_entry.entry_id, "out", refresh_interval))
        entities.append(ArubaPortPacketsSensor(host, username, password, ssh_port, port, config_entry.entry_id, "in", refresh_interval))
        entities.append(ArubaPortPacketsSensor(host, username, password, ssh_port, port, config_entry.entry_id, "out", refresh_interval))
        entities.append(ArubaPortLinkStatusSensor(host, username, password, ssh_port, port, config_entry.entry_id, refresh_interval))
        entities.append(ArubaPortSpeedSensor(host, username, password, ssh_port, port, config_entry.entry_id, refresh_interval))

    # Add switch version and firmware sensors (one per switch)
    entities.append(ArubaSwitchFirmwareSensor(host, username, password, ssh_port, config_entry.entry_id, refresh_interval))
    entities.append(ArubaSwitchModelSensor(host, username, password, ssh_port, config_entry.entry_id, refresh_interval))
    entities.append(ArubaSwitchSerialSensor(host, username, password, ssh_port, config_entry.entry_id, refresh_interval))

    _LOGGER.debug(f"Created {len(entities)} sensors for all {len(ports)} ports plus 3 switch info sensors: "
                 f"activity, bytes, packets, link status, speed, firmware version, model, and serial number")
    # Add entities without immediate update to avoid overwhelming the switch during setup
    async_add_entities(entities, update_before_add=False)


class ArubaPortActivitySensor(SensorEntity):
    """Representation of an Aruba switch port activity sensor."""
    
    def __init__(self, host, username, password, ssh_port, port, entry_id, refresh_interval=30):
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
        
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        self._last_update = 0
        self._update_interval = refresh_interval
        
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
            
            if stats and any(stats.get(key, 0) > 0 for key in ["bytes_in", "bytes_out", "packets_in", "packets_out"]):
                _LOGGER.debug(f"Port {self._port} has non-zero statistics: bytes_in={stats.get('bytes_in')}, bytes_out={stats.get('bytes_out')}")
            elif stats:
                _LOGGER.debug(f"Port {self._port} has all-zero statistics")
            else:
                _LOGGER.warning(f"Port {self._port} failed to get statistics")
                
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
                    
                    # Debug logging for activity calculation
                    _LOGGER.debug(f"Port {self._port} activity calc: prev_in={self._prev_bytes_in}, current_in={current_bytes_in}, "
                                f"prev_out={self._prev_bytes_out}, current_out={current_bytes_out}, time_diff={time_diff:.2f}s")
                    _LOGGER.debug(f"Port {self._port} rates: in_rate={bytes_in_rate:.2f} B/s, out_rate={bytes_out_rate:.2f} B/s, "
                                f"total_rate={total_rate:.2f} B/s, threshold={self._activity_threshold} B/s")
                    
                    if total_rate > self._activity_threshold:
                        self._state = "active"
                        self._attr_extra_state_attributes["last_activity"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        _LOGGER.debug(f"Port {self._port} marked as ACTIVE (rate {total_rate:.2f} > {self._activity_threshold})")
                    else:
                        self._state = "idle"
                        _LOGGER.debug(f"Port {self._port} marked as IDLE (rate {total_rate:.2f} <= {self._activity_threshold})")
                    
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

class ArubaPortBytesSensor(SensorEntity):
    """Sensor for port bytes in/out."""
    
    def __init__(self, host, username, password, ssh_port, port, entry_id, direction, refresh_interval=30):
        self._host = host
        self._port = port
        self._direction = direction  # "in" or "out"
        self._entry_id = entry_id
        
        self._attr_name = f"Port {port} Bytes {direction.title()}"
        self._attr_unique_id = f"{host}_{port}_bytes_{direction}"
        self._attr_icon = "mdi:counter"
        self._attr_unit_of_measurement = "B"
        self._attr_state_class = "total_increasing"
        self._attr_device_class = "data_size"
        
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        self._state = 0
        self._available = True

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "HP/Aruba",
            "model": "Network Switch"
        }

    @property
    def state(self):
        return self._state

    @property
    def available(self):
        return self._available

    async def async_update(self):
        try:
            stats = await asyncio.wait_for(
                self._ssh_manager.get_port_statistics(self._port),
                timeout=10
            )
            
            if stats:
                key = f"bytes_{self._direction}"
                value = stats.get(key, 0)
                self._state = value
                self._available = True
                _LOGGER.debug(f"Port {self._port} bytes {self._direction}: {value} (from stats: {stats})")
            else:
                self._available = False
                _LOGGER.debug(f"No statistics returned for port {self._port} bytes sensor")
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update bytes sensor for port {self._port}: {e}")
            self._available = False


class ArubaPortPacketsSensor(SensorEntity):
    """Sensor for port packets in/out."""
    
    def __init__(self, host, username, password, ssh_port, port, entry_id, direction, refresh_interval=30):
        self._host = host
        self._port = port
        self._direction = direction  # "in" or "out"
        self._entry_id = entry_id
        
        self._attr_name = f"Port {port} Packets {direction.title()}"
        self._attr_unique_id = f"{host}_{port}_packets_{direction}"
        self._attr_icon = "mdi:package-variant"
        self._attr_unit_of_measurement = "packets"
        self._attr_state_class = "total_increasing"
        
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        self._state = 0
        self._available = True

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "HP/Aruba",
            "model": "Network Switch"
        }

    @property
    def state(self):
        return self._state

    @property
    def available(self):
        return self._available

    async def async_update(self):
        try:
            stats = await asyncio.wait_for(
                self._ssh_manager.get_port_statistics(self._port),
                timeout=10
            )
            
            if stats:
                key = f"packets_{self._direction}"
                value = stats.get(key, 0)
                self._state = value
                self._available = True
                _LOGGER.debug(f"Port {self._port} packets {self._direction}: {value} (from stats: {stats})")
            else:
                self._available = False
                _LOGGER.debug(f"No statistics returned for port {self._port} packets sensor")
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update packets sensor for port {self._port}: {e}")
            self._available = False


class ArubaPortLinkStatusSensor(SensorEntity):
    """Sensor for port link status."""
    
    def __init__(self, host, username, password, ssh_port, port, entry_id, refresh_interval=30):
        self._host = host
        self._port = port
        self._entry_id = entry_id
        
        self._attr_name = f"Port {port} Link Status"
        self._attr_unique_id = f"{host}_{port}_link_status"
        self._attr_icon = "mdi:ethernet"
        
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        self._state = "unknown"
        self._available = True
        self._attr_extra_state_attributes = {}

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "HP/Aruba",
            "model": "Network Switch"
        }

    @property
    def state(self):
        return self._state

    @property
    def available(self):
        return self._available

    async def async_update(self):
        try:
            link_info = await asyncio.wait_for(
                self._ssh_manager.get_port_link_status(self._port),
                timeout=10
            )
            
            if link_info:
                self._state = "up" if link_info.get("link_up", False) else "down"
                self._attr_extra_state_attributes = {
                    "port_enabled": link_info.get("port_enabled", False),
                    "link_speed": link_info.get("link_speed", "unknown"),
                    "duplex": link_info.get("duplex", "unknown"),
                    "auto_negotiation": link_info.get("auto_negotiation", "unknown")
                }
                self._available = True
            else:
                self._available = False
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update link status sensor for port {self._port}: {e}")
            self._available = False


class ArubaPortSpeedSensor(SensorEntity):
    """Sensor for port speed."""
    
    def __init__(self, host, username, password, ssh_port, port, entry_id, refresh_interval=30):
        self._host = host
        self._port = port
        self._entry_id = entry_id
        
        self._attr_name = f"Port {port} Speed"
        self._attr_unique_id = f"{host}_{port}_speed"
        self._attr_icon = "mdi:speedometer"
        self._attr_unit_of_measurement = "Mbps"
        
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        self._state = 0
        self._available = True

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "HP/Aruba",
            "model": "Network Switch"
        }

    @property
    def state(self):
        return self._state

    @property
    def available(self):
        return self._available

    async def async_update(self):
        try:
            link_info = await asyncio.wait_for(
                self._ssh_manager.get_port_link_status(self._port),
                timeout=10
            )
            
            if link_info:
                speed_str = link_info.get("link_speed", "unknown")
                _LOGGER.debug(f"Port {self._port} speed sensor - raw speed string: '{speed_str}' (from link_info: {link_info})")
                
                # Enhanced parsing for HP/Aruba format
                if "gbps" in speed_str.lower():
                    # Convert Gbps to Mbps: "1 Gbps" -> 1000 Mbps
                    import re
                    match = re.search(r'(\d+)', speed_str)
                    if match:
                        self._state = int(match.group(1)) * 1000
                    else:
                        self._state = 0
                elif "mbps" in speed_str.lower():
                    # Parse Mbps: "1000 Mbps" -> 1000
                    import re
                    match = re.search(r'(\d+)', speed_str)
                    if match:
                        self._state = int(match.group(1))
                    else:
                        self._state = 0
                elif speed_str.isdigit():
                    # Direct numeric value assumed to be Mbps
                    self._state = int(speed_str)
                else:
                    # Check for brief mode format in link_info
                    mode = link_info.get("mode", "")
                    if mode and mode != "." and mode != "unknown":
                        # Parse mode like "1000FDx" -> 1000 Mbps
                        import re
                        speed_match = re.match(r'(\d+)', mode)
                        if speed_match:
                            self._state = int(speed_match.group(1))
                        else:
                            self._state = 0
                    else:
                        self._state = 0
                
                _LOGGER.debug(f"Port {self._port} speed sensor final value: {self._state} Mbps")
                self._available = True
            else:
                self._available = False
                _LOGGER.debug(f"No link info returned for port {self._port} speed sensor")
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update speed sensor for port {self._port}: {e}")
            self._available = False


class ArubaSwitchFirmwareSensor(SensorEntity):
    """Representation of an Aruba switch firmware version sensor."""
    
    def __init__(self, host, username, password, ssh_port, entry_id, refresh_interval=30):
        """Initialize the firmware version sensor."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._refresh_interval = refresh_interval
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        
        # Entity properties
        self._attr_name = f"Switch {host} Firmware Version"
        self._attr_unique_id = f"{entry_id}_firmware_version"
        self._attr_icon = "mdi:memory"
        
        # State properties
        self._state = None
        self._available = True
        self._attr_extra_state_attributes = {}
        
        # Update management
        self._last_update = 0
        import random
        self._update_offset = random.uniform(0, 5)
        self._update_interval = refresh_interval * 2  # Update less frequently for version info

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def available(self):
        """Return if entity is available."""
        return self._available

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attr_extra_state_attributes

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "Aruba",
            "model": "Switch",
        }

    async def async_update(self):
        """Update the firmware version sensor."""
        import time
        current_time = time.time()
        
        # Calculate time since last update with staggered offset
        time_since_update = current_time - (self._last_update + self._update_offset)
        
        # Only update if enough time has passed
        if time_since_update < self._update_interval:
            return
            
        self._last_update = current_time
        
        try:
            version_info = await self._ssh_manager.get_version_info()
            
            if version_info is None:
                # Switch is offline
                self._available = False
                return
                
            if version_info:
                self._available = True
                self._state = version_info.get("firmware_version", "Unknown")
                
                # Add all version info as attributes
                import datetime
                self._attr_extra_state_attributes = {
                    "host": self._host,
                    "firmware_version": version_info.get("firmware_version", "Unknown"),
                    "boot_version": version_info.get("boot_version", "Unknown"),
                    "hardware_revision": version_info.get("hardware_revision", "Unknown"),
                    "uptime": version_info.get("uptime", "Unknown"),
                    "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                _LOGGER.debug(f"Switch firmware version: {self._state}")
            else:
                self._available = False
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update firmware sensor for {self._host}: {e}")
            self._available = False


class ArubaSwitchModelSensor(SensorEntity):
    """Representation of an Aruba switch model sensor."""
    
    def __init__(self, host, username, password, ssh_port, entry_id, refresh_interval=30):
        """Initialize the model sensor."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._refresh_interval = refresh_interval
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        
        # Entity properties
        self._attr_name = f"Switch {host} Model"
        self._attr_unique_id = f"{entry_id}_model"
        self._attr_icon = "mdi:router-network"
        
        # State properties
        self._state = None
        self._available = True
        self._attr_extra_state_attributes = {}
        
        # Update management
        self._last_update = 0
        import random
        self._update_offset = random.uniform(0, 5)
        self._update_interval = refresh_interval * 2  # Update less frequently

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def available(self):
        """Return if entity is available."""
        return self._available

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attr_extra_state_attributes

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "Aruba",
            "model": "Switch",
        }

    async def async_update(self):
        """Update the model sensor."""
        import time
        current_time = time.time()
        
        time_since_update = current_time - (self._last_update + self._update_offset)
        
        if time_since_update < self._update_interval:
            return
            
        self._last_update = current_time
        
        try:
            version_info = await self._ssh_manager.get_version_info()
            
            if version_info is None:
                self._available = False
                return
                
            if version_info:
                self._available = True
                self._state = version_info.get("model", "HP/Aruba Switch")
                
                import datetime
                self._attr_extra_state_attributes = {
                    "host": self._host,
                    "model": version_info.get("model", "HP/Aruba Switch"),
                    "mac_address": version_info.get("mac_address", "Unknown"),
                    "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            else:
                self._available = False
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update model sensor for {self._host}: {e}")
            self._available = False


class ArubaSwitchSerialSensor(SensorEntity):
    """Representation of an Aruba switch serial number sensor."""
    
    def __init__(self, host, username, password, ssh_port, entry_id, refresh_interval=30):
        """Initialize the serial number sensor."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._refresh_interval = refresh_interval
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        
        # Entity properties
        self._attr_name = f"Switch {host} Serial Number"
        self._attr_unique_id = f"{entry_id}_serial_number"
        self._attr_icon = "mdi:barcode"
        
        # State properties
        self._state = None
        self._available = True
        self._attr_extra_state_attributes = {}
        
        # Update management
        self._last_update = 0
        import random
        self._update_offset = random.uniform(0, 5)
        self._update_interval = refresh_interval * 2  # Update less frequently

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def available(self):
        """Return if entity is available."""
        return self._available

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attr_extra_state_attributes

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Switch {self._host}",
            "manufacturer": "Aruba",
            "model": "Switch",
        }

    async def async_update(self):
        """Update the serial number sensor."""
        import time
        current_time = time.time()
        
        time_since_update = current_time - (self._last_update + self._update_offset)
        
        if time_since_update < self._update_interval:
            return
            
        self._last_update = current_time
        
        try:
            version_info = await self._ssh_manager.get_version_info()
            
            if version_info is None:
                self._available = False
                return
                
            if version_info:
                self._available = True
                self._state = version_info.get("serial_number", "Unknown")
                
                import datetime
                self._attr_extra_state_attributes = {
                    "host": self._host,
                    "serial_number": version_info.get("serial_number", "Unknown"),
                    "mac_address": version_info.get("mac_address", "Unknown"),
                    "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            else:
                self._available = False
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update serial sensor for {self._host}: {e}")
            self._available = False
