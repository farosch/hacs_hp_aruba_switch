import logging
import asyncio
import paramiko
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import Entity
from .const import DOMAIN, CONF_REFRESH_INTERVAL
from .ssh_manager import get_ssh_manager

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch from a config entry."""
    _LOGGER.debug("HP/Aruba Switch integration starting setup")
    host = config_entry.data["host"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]
    ssh_port = config_entry.data.get("ssh_port", 22)
    exclude_ports_str = config_entry.data.get("exclude_ports", "")
    exclude_poe_str = config_entry.data.get("exclude_poe", "")
    
    # Get configured port count (default to 24 if not set)
    port_count = config_entry.data.get("port_count", 24)
    refresh_interval = config_entry.data.get("refresh_interval", 30)
    _LOGGER.debug(f"Using configured port count: {port_count}")
    _LOGGER.debug(f"Config entry data: {config_entry.data}")
    
    # Parse exclusion lists
    exclude_ports = [p.strip() for p in exclude_ports_str.split(",") if p.strip()]
    exclude_poe = [p.strip() for p in exclude_poe_str.split(",") if p.strip()]

    # Generate port list based on configured count
    ports = [str(i) for i in range(1, port_count + 1)]
    _LOGGER.debug(f"Generated {len(ports)} ports for switch setup")
    entities = []

    # Test SSH connectivity during setup
    ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
    test_result = await ssh_manager.execute_command("show version", timeout=10)
    _LOGGER.info(f"SSH connectivity test for {host}: {'SUCCESS' if test_result else 'FAILED'}")
    if test_result:
        _LOGGER.debug(f"Switch version info: {repr(test_result[:200])}")  # Log first 200 chars

    for port in ports:
        # Add port switch entity (if not excluded)
        if port not in exclude_ports:
            entities.append(ArubaSwitch(host, username, password, ssh_port, port, False, config_entry.entry_id, refresh_interval))
        
        # Add PoE switch entity (if not excluded)
        if port not in exclude_poe:
            entities.append(ArubaSwitch(host, username, password, ssh_port, port, True, config_entry.entry_id, refresh_interval))

    async_add_entities(entities, update_before_add=False)


class ArubaSwitch(SwitchEntity):
    """Representation of an Aruba switch port."""
    
    # Reduce update frequency to avoid overwhelming the switch
    entity_registry_enabled_default = True
    
    def __init__(self, host, username, password, ssh_port, port, is_poe, entry_id, refresh_interval=30):
        """Initialize the switch."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._port = port
        self._is_poe = is_poe
        self._entry_id = entry_id
        self._is_on = False
        self._available = True
        self._attr_name = f"Port {port} {'PoE' if is_poe else ''}".strip()
        self._attr_unique_id = f"{host}_{port}_{'poe' if is_poe else 'port'}"
        
        # Set appropriate icons for different entity types
        if is_poe:
            self._attr_icon = "mdi:flash"
        else:
            self._attr_icon = "mdi:ethernet"
            
        # Initialize extra state attributes to expose all port data
        self._attr_extra_state_attributes = {
            "port_number": port,
            "link_status": "unknown",
            "link_speed": "unknown",
            "duplex": "unknown",
            "auto_negotiation": "unknown",
            "cable_type": "unknown",
            "bytes_in": 0,
            "bytes_out": 0,
            "packets_in": 0,
            "packets_out": 0,
            "last_update": "never"
        }
            
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port, refresh_interval)
        self._last_update = 0
        self._update_interval = refresh_interval + 5  # Add small buffer for switches
        
        # Stagger updates to prevent simultaneous cache refreshes
        # Use port number and type to create different offsets
        import hashlib
        offset_hash = hashlib.md5(f"{port}_{is_poe}".encode()).hexdigest()
        self._update_offset = int(offset_hash[:2], 16) % 15  # 0-14 second offset (reduced)

    @property
    def name(self):
        """Return the name of the switch."""
        return self._attr_name

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return self._attr_unique_id

    @property
    def is_on(self):
        """Return true if switch is on."""
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

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        if self._is_poe:
            command = f"configure\ninterface {self._port}\npower-over-ethernet\nexit\nwrite mem\nexit"
        else:
            command = f"configure\ninterface {self._port}\nenable\nexit\nwrite mem\nexit"
        
        _LOGGER.debug(f"Executing turn_on command for {self._attr_name}: {command}")
        result = await self._ssh_manager.execute_command(command)
        _LOGGER.debug(f"Turn_on result for {self._attr_name}: {repr(result)}")
        
        if result is not None:
            self._is_on = True
            self._available = True
            # Force a state refresh from the switch
            await asyncio.sleep(1)  # Wait for switch to process
            await self.async_update()
            self.async_write_ha_state()
        else:
            # Command failed - switch may be offline
            self._available = False
            _LOGGER.warning(f"Failed to turn on {self._attr_name} - switch may be offline")
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self._is_poe:
            command = f"configure\ninterface {self._port}\nno power-over-ethernet\nexit\nwrite mem\nexit"
        else:
            command = f"configure\ninterface {self._port}\ndisable\nexit\nwrite mem\nexit"
        
        _LOGGER.debug(f"Executing turn_off command for {self._attr_name}: {command}")
        result = await self._ssh_manager.execute_command(command)
        _LOGGER.debug(f"Turn_off result for {self._attr_name}: {repr(result)}")
        
        if result is not None:
            self._is_on = False
            self._available = True
            # Force a state refresh from the switch
            await asyncio.sleep(1)  # Wait for switch to process
            await self.async_update()
            self.async_write_ha_state()
        else:
            # Command failed - switch may be offline
            self._available = False
            _LOGGER.warning(f"Failed to turn off {self._attr_name} - switch may be offline")
            self.async_write_ha_state()

    async def async_update(self):
        """Update the switch state using bulk queries for better performance."""
        import time
        current_time = time.time()
        
        # Calculate time since last update with staggered offset
        time_since_update = current_time - (self._last_update + self._update_offset)
        
        # Only update if enough time has passed
        if time_since_update < self._update_interval:
            return
        
        self._last_update = current_time
        
        try:
            # Get all available data for this port
            status = await self._ssh_manager.get_port_status(self._port, self._is_poe)
            statistics = await self._ssh_manager.get_port_statistics(self._port)
            link_details = await self._ssh_manager.get_port_link_status(self._port)
            
            _LOGGER.debug(f"Port {self._port} {'PoE' if self._is_poe else ''} - status: {status}, stats: {statistics}, link: {link_details}")
            
            # Check if switch is available (all data methods return None when offline)
            if status is None or statistics is None or link_details is None:
                self._available = False
                _LOGGER.debug(f"Switch appears offline for port {self._port} {'PoE' if self._is_poe else ''} - marking entity as unavailable")
                return
            
            if status:
                self._available = True
                
                # Update main entity state
                if self._is_poe:
                    # Parse PoE status from bulk query
                    power_enable = status.get("power_enable", False)
                    poe_status = status.get("poe_status", "off")
                    
                    # PoE is considered "on" if power is enabled and status indicates active power delivery
                    poe_active = False
                    if power_enable and isinstance(poe_status, str):
                        poe_active = poe_status.lower() in ["delivering", "searching", "on", "enabled"]
                    elif power_enable and isinstance(poe_status, bool):
                        poe_active = poe_status  # Legacy boolean support
                    
                    self._is_on = poe_active
                    _LOGGER.debug(f"PoE port {self._port}: power_enable={power_enable}, poe_status={poe_status}, final_state={self._is_on}")
                else:
                    # Parse interface status from bulk query
                    # For switch ports, "on" means administratively enabled, regardless of link status
                    port_enabled = status.get("port_enabled", False)
                    link_up = status.get("link_status", "down").lower() == "up"
                    self._is_on = port_enabled  # Only check if port is administratively enabled
                    _LOGGER.debug(f"Interface port {self._port}: port_enabled={port_enabled}, link_up={link_up}, final_state={self._is_on}")
                
                # Update all attributes with comprehensive port information
                import datetime
                self._attr_extra_state_attributes.update({
                    "port_number": self._port,
                    "link_status": "up" if link_details.get("link_up", False) else "down",
                    "link_speed": link_details.get("link_speed", "unknown"),
                    "duplex": link_details.get("duplex", "unknown"),
                    "auto_negotiation": link_details.get("auto_negotiation", "unknown"),
                    "cable_type": link_details.get("cable_type", "unknown"),
                    "bytes_in": statistics.get("bytes_in", 0),
                    "bytes_out": statistics.get("bytes_out", 0),
                    "packets_in": statistics.get("packets_in", 0),
                    "packets_out": statistics.get("packets_out", 0),
                    "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
                # Add PoE-specific attributes if this is a PoE entity
                if self._is_poe:
                    self._attr_extra_state_attributes.update({
                        "power_enable": status.get("power_enable", False),
                        "poe_status": status.get("poe_status", False)
                    })
                else:
                    # Add port-specific attributes for non-PoE entities
                    self._attr_extra_state_attributes.update({
                        "port_enabled": status.get("port_enabled", False),
                        "admin_status": "enabled" if status.get("port_enabled", False) else "disabled"
                    })
                
            else:
                self._available = False
                _LOGGER.debug(f"No status data received for port {self._port} {'PoE' if self._is_poe else ''}")
                
        except Exception as e:
            _LOGGER.warning(f"Failed to update {self._attr_name}: {e}")
            self._available = False
