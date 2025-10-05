"""Base entity for HP/Aruba Switch integration."""
from typing import Any, Dict, Optional

from homeassistant.helpers.update_coordinator import CoordinatorEntity  # type: ignore

from .const import DOMAIN


class ArubaSwitchEntity(CoordinatorEntity):
    """Base entity for Aruba Switch integration."""

    def __init__(self, coordinator, entry_id: str):
        """Initialize the base entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information with enhanced details."""
        device = {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "HP/Aruba",
            "model": self.coordinator.model,
        }
        
        # Add firmware version if available
        if self.coordinator.firmware and self.coordinator.firmware != "Unknown":
            device["sw_version"] = self.coordinator.firmware
        
        # Add serial number if available
        if self.coordinator.serial_number and self.coordinator.serial_number != "Unknown":
            device["serial_number"] = self.coordinator.serial_number
            
        # Add hostname if available
        if self.coordinator.hostname:
            device["hostname"] = self.coordinator.hostname
            
        # Add MAC address if available  
        if self.coordinator.mac_address:
            device["mac_address"] = self.coordinator.mac_address
            
        # Add hardware revision if available
        if self.coordinator.hardware_revision:
            device["hw_version"] = self.coordinator.hardware_revision
            
        # Add uptime if available (as configuration URL since HA doesn't have uptime field)
        if self.coordinator.uptime:
            device["configuration_url"] = f"Uptime: {self.coordinator.uptime}"
        
        # Add configuration URL
        device["configuration_url"] = f"https://{self.coordinator.host}"
        
        return device

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    def _get_coordinator_data(self) -> Optional[Dict[str, Any]]:
        """Get coordinator data if available."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return None
        return self.coordinator.data
