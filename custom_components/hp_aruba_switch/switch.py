import logging
import asyncio
import paramiko
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, CONF_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch from a config entry."""
    _LOGGER.debug("HP/Aruba Switch integration starting setup")
    
    # Get the coordinator from the integration setup
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    exclude_ports_str = config_entry.data.get("exclude_ports", "")
    exclude_poe_str = config_entry.data.get("exclude_poe", "")
    port_count = config_entry.data.get("port_count", 24)
    
    _LOGGER.debug(f"Using configured port count: {port_count}")
    _LOGGER.debug(f"Config entry data: {config_entry.data}")
    
    # Parse exclusion lists
    exclude_ports = [p.strip() for p in exclude_ports_str.split(",") if p.strip()]
    exclude_poe = [p.strip() for p in exclude_poe_str.split(",") if p.strip()]

    # Generate port list based on configured count
    ports = [str(i) for i in range(1, port_count + 1)]
    _LOGGER.debug(f"Generated {len(ports)} ports for switch setup")
    entities = []

    for port in ports:
        # Add port switch entity (if not excluded)
        if port not in exclude_ports:
            entities.append(ArubaSwitch(coordinator, port, False, config_entry.entry_id))
        
        # Add PoE switch entity (if not excluded)
        if port not in exclude_poe:
            entities.append(ArubaSwitch(coordinator, port, True, config_entry.entry_id))

    async_add_entities(entities, update_before_add=False)


class ArubaSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of an Aruba switch port."""
    
    def __init__(self, coordinator, port, is_poe, entry_id):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._port = port
        self._is_poe = is_poe
        self._entry_id = entry_id
        self._is_on = False
        self._attr_name = f"Port {port} {'PoE' if is_poe else ''}".strip()
        self._attr_unique_id = f"{coordinator.host}_{port}_{'poe' if is_poe else 'port'}"
        
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
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attr_extra_state_attributes

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._coordinator.host)},
            "name": f"Switch {self._coordinator.host}",
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
        result = await self._coordinator.ssh_manager.execute_command(command)
        _LOGGER.debug(f"Turn_on result for {self._attr_name}: {repr(result)}")
        
        if result is not None:
            self._is_on = True
            # Force a coordinator refresh to get updated data
            await asyncio.sleep(1)  # Wait for switch to process
            await self._coordinator.async_request_refresh()
        else:
            _LOGGER.warning(f"Failed to turn on {self._attr_name} - switch may be offline")

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self._is_poe:
            command = f"configure\ninterface {self._port}\nno power-over-ethernet\nexit\nwrite mem\nexit"
        else:
            command = f"configure\ninterface {self._port}\ndisable\nexit\nwrite mem\nexit"
        
        _LOGGER.debug(f"Executing turn_off command for {self._attr_name}: {command}")
        result = await self._coordinator.ssh_manager.execute_command(command)
        _LOGGER.debug(f"Turn_off result for {self._attr_name}: {repr(result)}")
        
        if result is not None:
            self._is_on = False
            # Force a coordinator refresh to get updated data
            await asyncio.sleep(1)  # Wait for switch to process
            await self._coordinator.async_request_refresh()
        else:
            _LOGGER.warning(f"Failed to turn off {self._attr_name} - switch may be offline")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.last_update_success:
            return
            
        try:
            # Get data from coordinator's SSH manager cache - NO SSH CALLS HERE
            ssh_manager = self._coordinator.ssh_manager
            
            # Read from the cached data that coordinator already fetched
            status = ssh_manager._interface_cache.get(self._port, {}) if self._is_poe else ssh_manager._interface_cache.get(self._port, {})
            statistics = ssh_manager._statistics_cache.get(self._port, {})  
            link_details = ssh_manager._link_cache.get(self._port, {})
            
            if self._is_poe:
                # Get PoE status from cache
                poe_status = ssh_manager._poe_cache.get(self._port, {})
                status.update(poe_status)  # Merge PoE data with interface data
            
            _LOGGER.debug(f"Port {self._port} {'PoE' if self._is_poe else ''} - cached status: {status}, stats: {statistics}, link: {link_details}")
            
            # Update entity state based on cached data
            if self._is_poe:
                # Parse PoE status from cached data
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
                # Parse interface status from cached data
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
            
            # Add type-specific attributes
            if self._is_poe:
                self._attr_extra_state_attributes.update({
                    "power_enable": status.get("power_enable", False),
                    "poe_status": status.get("poe_status", False)
                })
            else:
                self._attr_extra_state_attributes.update({
                    "port_enabled": status.get("port_enabled", False),
                    "admin_status": "enabled" if status.get("port_enabled", False) else "disabled"
                })
                
        except Exception as e:
            _LOGGER.warning(f"Failed to update {self._attr_name} from coordinator: {e}")
