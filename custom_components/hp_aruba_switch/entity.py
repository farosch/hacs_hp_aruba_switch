"""Base entity for HP/Aruba Switch integration."""
from typing import Any, Dict, Optional

from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": f"Switch {self.coordinator.host}",
            "manufacturer": "Aruba",
            "model": "Switch",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    def _get_coordinator_data(self) -> Optional[Dict[str, Any]]:
        """Get coordinator data if available."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return None
        return self.coordinator.data
