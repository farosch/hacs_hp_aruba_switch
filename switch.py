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
    exclude_ports = [p.strip() for p in exclude_ports_str.split(",") if p.strip()]

    # Get port configuration from switch or use default 24 ports
    ports = [str(i) for i in range(1, 25)]  # Generate simple port numbers: 1, 2, 3, etc.
    entities = []

    for port in ports:
        if port not in exclude_ports:
            # Port-Switch
            entities.append(ArubaSwitch(host, username, password, ssh_port, port, False, config_entry.entry_id))
            # PoE-Switch
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
        self._update_interval = 90  # Increase to 90 seconds
        
        # Stagger updates to prevent simultaneous SSH connections
        # Use port number and type to create different offsets
        import hashlib
        offset_hash = hashlib.md5(f"{port}_{is_poe}".encode()).hexdigest()
        self._update_offset = int(offset_hash[:2], 16) % 30  # 0-29 second offset

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
            command = f"configure\ninterface {self._port}\nno shutdown\nexit\nwrite mem\nexit"
        
        result = await self._ssh_manager.execute_command(command)
        if result is not None:
            self._is_on = True
            self._available = True
            self.async_write_ha_state()
        else:
            self._available = False
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self._is_poe:
            command = f"configure\ninterface {self._port}\nno power-over-ethernet\nexit\nwrite mem\nexit"
        else:
            command = f"configure\ninterface {self._port}\nshutdown\nexit\nwrite mem\nexit"
        
        result = await self._ssh_manager.execute_command(command)
        if result is not None:
            self._is_on = False
            self._available = True
            self.async_write_ha_state()
        else:
            self._available = False
            self.async_write_ha_state()

    async def async_update(self):
        """Update the switch state."""
        import time
        current_time = time.time()
        
        # Calculate time since last update with staggered offset
        time_since_update = current_time - (self._last_update + self._update_offset)
        
        # Only update if enough time has passed
        if time_since_update < self._update_interval:
            return
        
        self._last_update = current_time
        
        if self._is_poe:
            # Check PoE status
            command = f"show power-over-ethernet {self._port}"
        else:
            # Check interface status
            command = f"show interface {self._port}"
        
        # Use shorter timeout for updates
        result = await self._ssh_manager.execute_command(command, timeout=8)
        if result is not None:
            self._available = True
            if self._is_poe:
                # Parse PoE status from output
                output_lower = result.lower()
                self._is_on = any(keyword in output_lower for keyword in [
                    'enabled', 'on', 'delivering', 'active'
                ])
            else:
                # Parse interface status from output
                output_lower = result.lower()
                # Interface is up if it contains "up" but not "down"
                has_up = 'up' in output_lower
                has_down = 'down' in output_lower and 'up' not in output_lower.split('down')[0]
                self._is_on = has_up and not has_down
        else:
            self._available = False
