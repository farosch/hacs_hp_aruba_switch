"""Binary sensor entities for HP/Aruba Switch integration."""
import logging
import asyncio
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.entity import Entity
from .const import DOMAIN, CONF_REFRESH_INTERVAL
from .ssh_manager import get_ssh_manager

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch binary sensors from a config entry."""
    _LOGGER.debug("HP/Aruba Switch binary sensor integration starting setup")
    host = config_entry.data["host"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]
    ssh_port = config_entry.data.get("ssh_port", 22)
    
    # Get configured port count (default to 24 if not set)
    port_count = config_entry.data.get("port_count", 24)
    refresh_interval = config_entry.data.get("refresh_interval", 30)
    
    # Note: Binary sensors are created for ALL ports regardless of exclusion lists
    # This allows monitoring link status even on ports that don't have control switches
    _LOGGER.debug(f"Creating binary sensors for all {port_count} ports (ignoring exclusion lists)")

    # Generate port list based on configured count
    ports = [str(i) for i in range(1, port_count + 1)]
    entities = []

    # Test SSH connectivity during setup
    ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
    test_result = await ssh_manager.execute_command("show version", timeout=10)
    _LOGGER.info(f"SSH connectivity test for binary sensors {host}: {'SUCCESS' if test_result else 'FAILED'}")

    for port in ports:
        # Add link status binary sensor for each port
        entities.append(ArubaPortLinkSensor(host, username, password, ssh_port, port, config_entry.entry_id, refresh_interval))

    # Add switch connectivity status sensor
    entities.append(ArubaSwitchConnectivitySensor(host, username, password, ssh_port, config_entry.entry_id, refresh_interval))

    _LOGGER.debug(f"Created {len(entities)} link status binary sensors for all {len(ports)} ports + 1 connectivity sensor")
    # Add entities without immediate update to avoid overwhelming the switch during setup
    async_add_entities(entities, update_before_add=False)


class ArubaPortLinkSensor(BinarySensorEntity):
    """Representation of an Aruba switch port link status binary sensor."""
    
    def __init__(self, host, username, password, ssh_port, port, entry_id, refresh_interval=30):
        """Initialize the binary sensor."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._port = port
        self._entry_id = entry_id
        self._is_on = False
        self._available = True
        self._attr_name = f"Port {port} Link"
        self._attr_unique_id = f"{host}_{port}_link"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:ethernet-cable"
        
        # Link status attributes
        self._attr_extra_state_attributes = {
            "port_enabled": False,
            "link_speed": "unknown",
            "duplex": "unknown",
            "auto_negotiation": "unknown",
            "cable_type": "unknown"
        }
        
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        self._last_update = 0
        self._update_interval = refresh_interval
        
        # Stagger updates to prevent simultaneous queries, with longer initial delay
        import hashlib
        import time
        offset_hash = hashlib.md5(f"link_{port}".encode()).hexdigest()
        self._update_offset = 45 + (int(offset_hash[:2], 16) % 20)  # 45-65 second initial delay

    @property
    def name(self):
        """Return the name of the binary sensor."""
        return self._attr_name

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return self._attr_unique_id

    @property
    def is_on(self):
        """Return true if link is up."""
        return self._is_on

    @property
    def available(self):
        """Return if entity is available."""
        return self._available

    @property
    def device_class(self):
        """Return the device class."""
        return self._attr_device_class

    @property
    def icon(self):
        """Return the icon."""
        # Change icon based on link status
        if self._is_on:
            return "mdi:ethernet-cable"
        else:
            return "mdi:ethernet-cable-off"

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
        """Update the binary sensor state."""
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
            # Get port link status with timeout protection
            status = await asyncio.wait_for(
                self._ssh_manager.get_port_link_status(self._port),
                timeout=15
            )
            _LOGGER.debug(f"Port {self._port} link status: {status}")
            
            if status:
                self._available = True
                
                # Extract link status information
                link_up = status.get("link_up", False)
                port_enabled = status.get("port_enabled", False)
                link_speed = status.get("link_speed", "unknown")
                duplex = status.get("duplex", "unknown")
                auto_neg = status.get("auto_negotiation", "unknown")
                cable_type = status.get("cable_type", "unknown")
                
                # Binary sensor is ON when link is up AND port is enabled
                self._is_on = link_up and port_enabled
                
                # Update attributes
                self._attr_extra_state_attributes.update({
                    "port_enabled": port_enabled,
                    "link_speed": link_speed,
                    "duplex": duplex,
                    "auto_negotiation": auto_neg,
                    "cable_type": cable_type
                })
                
                _LOGGER.debug(f"Port {self._port} link sensor: link_up={link_up}, "
                            f"port_enabled={port_enabled}, final_state={self._is_on}, "
                            f"speed={link_speed}, duplex={duplex}")
            else:
                self._available = False
                _LOGGER.debug(f"No link status data received for port {self._port}")
                
        except asyncio.TimeoutError:
            _LOGGER.debug(f"Timeout updating link status for {self._attr_name}")
            self._available = False
        except asyncio.CancelledError:
            _LOGGER.debug(f"Update cancelled for {self._attr_name}")
            # Don't mark as unavailable on cancellation, just skip this update
            raise
        except Exception as e:
            _LOGGER.warning(f"Failed to update {self._attr_name}: {e}")
            self._available = False


class ArubaSwitchConnectivitySensor(BinarySensorEntity):
    """Representation of an Aruba switch connectivity status binary sensor."""
    
    def __init__(self, host, username, password, ssh_port, entry_id, refresh_interval=30):
        """Initialize the connectivity binary sensor."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._refresh_interval = refresh_interval
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        
        # Entity properties
        self._attr_name = f"Switch {host} Connectivity"
        self._attr_unique_id = f"{entry_id}_switch_connectivity"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:network-outline"
        
        # State properties
        self._is_on = True  # Assume online initially
        self._available = True
        self._attr_extra_state_attributes = {}
        
        # Update management
        self._last_update = 0
        import random
        self._update_offset = random.uniform(0, 5)  # Stagger updates
        self._update_interval = refresh_interval

    @property
    def is_on(self):
        """Return true if the switch is connected/online."""
        return self._is_on

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
        """Update the switch connectivity status."""
        import time
        current_time = time.time()
        
        # Calculate time since last update with staggered offset
        time_since_update = current_time - (self._last_update + self._update_offset)
        
        # Only update if enough time has passed
        if time_since_update < self._update_interval:
            return
            
        self._last_update = current_time
        
        try:
            # Check if switch is available
            is_available = await self._ssh_manager.is_switch_available()
            
            # Update state and attributes
            self._is_on = is_available
            self._available = True  # This sensor itself is always available
            
            # Get additional connectivity information
            import datetime
            last_successful = getattr(self._ssh_manager, '_last_successful_connection', 0)
            
            self._attr_extra_state_attributes = {
                "host": self._host,
                "ssh_port": self._ssh_port,
                "status": "online" if is_available else "offline",
                "last_successful_connection": (
                    datetime.datetime.fromtimestamp(last_successful).strftime("%Y-%m-%d %H:%M:%S")
                    if last_successful > 0 else "never"
                ),
                "refresh_interval": self._refresh_interval,
                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            _LOGGER.debug(f"Switch connectivity sensor: {self._host} is {'online' if is_available else 'offline'}")
            
        except Exception as e:
            _LOGGER.warning(f"Failed to update connectivity sensor for {self._host}: {e}")
            # Keep the sensor available even if we can't determine switch status
            # The switch being offline shouldn't make the connectivity sensor unavailable