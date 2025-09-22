import logging
import asyncio
import paramiko
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import Entity
from .const import DOMAIN
from .ssh_manager import get_ssh_manager

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch from a config entry."""
    host = config_entry.data["host"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]
    ssh_port = config_entry.data.get("ssh_port", 22)
    exclude_ports_str = config_entry.data.get("exclude_ports", "")
    exclude_poe_str = config_entry.data.get("exclude_poe", "")
    
    # Parse exclusion lists
    exclude_ports = [p.strip() for p in exclude_ports_str.split(",") if p.strip()]
    exclude_poe = [p.strip() for p in exclude_poe_str.split(",") if p.strip()]

    # Get port configuration from switch or use default 24 ports
    ports = [str(i) for i in range(1, 25)]  # Generate simple port numbers: 1, 2, 3, etc.
    entities = []

    # Test SSH connectivity during setup
    ssh_manager = get_ssh_manager(host, username, password, ssh_port)
    test_result = await ssh_manager.execute_command("show version", timeout=10)
    _LOGGER.info(f"SSH connectivity test for {host}: {'SUCCESS' if test_result else 'FAILED'}")
    if test_result:
        _LOGGER.debug(f"Switch version info: {repr(test_result[:200])}")  # Log first 200 chars

    for port in ports:
        # Add port switch entity (if not excluded)
        if port not in exclude_ports:
            entities.append(ArubaSwitch(host, username, password, ssh_port, port, False, config_entry.entry_id))
        
        # Add PoE switch entity (if not excluded)
        if port not in exclude_poe:
            entities.append(ArubaSwitch(host, username, password, ssh_port, port, True, config_entry.entry_id))

    async_add_entities(entities, update_before_add=True)


class ArubaSwitch(SwitchEntity):
    """Representation of an Aruba switch port."""
    
    # Reduce update frequency to avoid overwhelming the switch
    entity_registry_enabled_default = True
    
    def __init__(self, host, username, password, ssh_port, port, is_poe, entry_id):
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
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port)
        self._last_update = 0
        self._update_interval = 35  # Reduced since bulk queries are more efficient
        
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
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Aruba Switch {self._host}",
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
            self._available = False
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
            self._available = False
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
            # Use bulk query method instead of individual queries
            status = await self._ssh_manager.get_port_status(self._port, self._is_poe)
            
            if status:
                self._available = True
                if self._is_poe:
                    # Parse PoE status from bulk query
                    self._is_on = status.get("power_enable", False) and status.get("poe_status", False)
                else:
                    # Parse interface status from bulk query
                    port_enabled = status.get("port_enabled", False)
                    link_up = status.get("link_status", "down").lower() == "up"
                    self._is_on = port_enabled and link_up
            else:
                self._available = False
                
        except Exception as e:
            _LOGGER.warning(f"Failed to update {self._attr_name}: {e}")
            self._available = False
