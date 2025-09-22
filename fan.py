import logging
import asyncio
import paramiko
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)
from .const import DOMAIN
from .ssh_manager import get_ssh_manager

_LOGGER = logging.getLogger(__name__)

# Fan speed presets for Aruba switches
SPEED_LIST = ["auto", "low", "medium", "high"]

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch fan from a config entry."""
    host = config_entry.data["host"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]
    ssh_port = config_entry.data.get("ssh_port", 22)

    # Create fan entity for the switch
    fan_entity = ArubaFan(host, username, password, ssh_port, config_entry.entry_id)
    async_add_entities([fan_entity], update_before_add=True)


class ArubaFan(FanEntity):
    """Representation of an Aruba switch fan."""
    
    def __init__(self, host, username, password, ssh_port, entry_id):
        """Initialize the fan."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
        self._entry_id = entry_id
        self._is_on = True  # Fans are typically always on
        self._available = True
        self._speed = "auto"  # Default to auto mode
        self._attr_name = f"Switch Fan"
        self._attr_unique_id = f"{host}_fan"
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED | 
            FanEntityFeature.PRESET_MODE
        )
        self._attr_preset_modes = SPEED_LIST
        self._attr_speed_count = len(SPEED_LIST)
        self._ssh_manager = get_ssh_manager(host, username, password, ssh_port)
        self._last_update = 0
        self._update_interval = 120  # Update fan status every 2 minutes

    @property
    def name(self):
        """Return the name of the fan."""
        return self._attr_name

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return self._attr_unique_id

    @property
    def is_on(self):
        """Return true if fan is on."""
        return self._is_on

    @property
    def available(self):
        """Return if entity is available."""
        return self._available

    @property
    def percentage(self):
        """Return the current speed percentage."""
        if not self._is_on or self._speed is None:
            return 0
        return ordered_list_item_to_percentage(SPEED_LIST, self._speed)

    @property
    def preset_mode(self):
        """Return the current preset mode."""
        return self._speed

    @property
    def preset_modes(self):
        """Return a list of available preset modes."""
        return SPEED_LIST

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Aruba Switch {self._host}",
            "manufacturer": "Aruba",
            "model": "Switch",
        }

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        """Turn on the fan."""
        if preset_mode:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            # Default to auto mode when turning on
            await self.async_set_preset_mode("auto")

    async def async_turn_off(self, **kwargs):
        """Turn off the fan. Note: Most switches don't allow turning off fans."""
        _LOGGER.warning("Cannot turn off switch fan - fans are required for switch operation")
        # Don't actually turn off the fan as it's critical for switch operation

    async def async_set_percentage(self, percentage):
        """Set the speed percentage of the fan."""
        if percentage == 0:
            await self.async_turn_off()
            return
        
        speed = percentage_to_ordered_list_item(SPEED_LIST, percentage)
        await self.async_set_preset_mode(speed)

    async def async_set_preset_mode(self, preset_mode):
        """Set the preset mode of the fan."""
        if preset_mode not in SPEED_LIST:
            _LOGGER.error(f"Invalid fan speed: {preset_mode}")
            return

        # Map preset modes to Aruba CLI commands
        speed_commands = {
            "auto": "configure\nfan auto\nexit",
            "low": "configure\nfan speed low\nexit", 
            "medium": "configure\nfan speed medium\nexit",
            "high": "configure\nfan speed high\nexit"
        }
        
        command = speed_commands.get(preset_mode)
        if not command:
            _LOGGER.error(f"No command mapping for speed: {preset_mode}")
            return

        result = await self._ssh_manager.execute_command(command)
        if result is not None:
            self._speed = preset_mode
            self._is_on = True
            self._available = True
            self.async_write_ha_state()
        else:
            self._available = False
            self.async_write_ha_state()

    async def async_update(self):
        """Update the fan state."""
        import time
        current_time = time.time()
        
        # Throttle fan updates - fans don't change often
        if current_time - self._last_update < self._update_interval:
            return
        
        self._last_update = current_time
        
        command = "show system fan"
        result = await self._ssh_manager.execute_command(command, timeout=8)
        if result is not None:
            self._available = True
            output_lower = result.lower()
            
            # Parse fan status and speed from output
            if "auto" in output_lower:
                self._speed = "auto"
            elif "high" in output_lower:
                self._speed = "high"
            elif "medium" in output_lower:
                self._speed = "medium"
            elif "low" in output_lower:
                self._speed = "low"
            
            # Fan is considered on if it's running
            self._is_on = any(keyword in output_lower for keyword in [
                'running', 'ok', 'active', 'operational'
            ]) or any(speed in output_lower for speed in SPEED_LIST)
        else:
            self._available = False