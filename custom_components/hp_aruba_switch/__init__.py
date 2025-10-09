"""HP/Aruba Switch Integration."""

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, Set

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant  # type: ignore
from homeassistant.exceptions import ConfigEntryNotReady  # type: ignore
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed  # type: ignore
from homeassistant.helpers import config_validation as cv, device_registry as dr  # type: ignore

from .const import DOMAIN
from .ssh_manager import get_ssh_manager

_LOGGER = logging.getLogger(__name__)

# This integration only supports config entries, no YAML configuration
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


class ArubaSwitchCoordinator(DataUpdateCoordinator):
    """Coordinator to manage single SSH session and update all entities."""

    def __init__(self, hass, entry):
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.host = entry.data["host"]
        refresh_interval = entry.data.get("refresh_interval", 30)

        # Port capability tracking
        self.detected_ports: Set[str] = set()
        self.poe_capable_ports: Set[str] = set()
        self.sfp_ports: Set[str] = set()
        self.port_configs: Dict[str, Dict[str, Any]] = {}

        # Device information
        self.model: str = "Unknown"
        self.firmware: str = "Unknown"
        self.serial_number: str = "Unknown"

        # Initialize SSH manager
        self.ssh_manager = get_ssh_manager(
            entry.data["host"],
            entry.data["username"],
            entry.data["password"],
            entry.data.get("ssh_port", 22),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"Aruba Switch {self.host}",
            update_interval=timedelta(seconds=refresh_interval),
            always_update=False,  # Only update if data changed
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch live data from switch and detect port capabilities."""
        try:
            _LOGGER.debug("Starting coordinator data update for %s", self.host)
            # Get live data directly
            data = await self.ssh_manager.get_current_data()

            if not data.get("available", False):
                _LOGGER.error("Switch %s is offline or returned no data", self.host)
                raise UpdateFailed(f"Switch {self.host} is offline")

            # Detect port capabilities on first successful update
            if not self.detected_ports:
                await self._detect_port_capabilities(data)

            # Update device information
            self._update_device_info(data)

            # Pre-calculate entity states for performance
            self._precalculate_states(data)

            _LOGGER.debug("Coordinator data update completed for %s", self.host)
            return data

        except Exception as err:
            _LOGGER.error("Coordinator update error for %s: %s", self.host, err)
            raise UpdateFailed(f"Error communicating with switch {self.host}: {err}")

    async def _detect_port_capabilities(self, data: Dict[str, Any]) -> None:
        """Detect which ports exist and their capabilities."""
        interfaces = data.get("interfaces", {})
        poe_ports = data.get("poe_ports", {})
        link_details = data.get("link_details", {})

        for port in interfaces.keys():
            self.detected_ports.add(port)

            # Detect PoE capability
            if port in poe_ports:
                self.poe_capable_ports.add(port)

            # Detect SFP ports (typically 1000Mbps+ and port number >= 25)
            try:
                port_num = int(port)
                link_info = link_details.get(port, {})
                link_speed = link_info.get("link_speed", "")

                if port_num >= 25 or "1000" in link_speed or "10G" in link_speed:
                    self.sfp_ports.add(port)
            except ValueError:
                pass

            # Store port configuration
            self.port_configs[port] = {
                "poe_capable": port in self.poe_capable_ports,
                "is_sfp": port in self.sfp_ports,
                "detected": True,
            }

        _LOGGER.info(
            f"Detected {len(self.detected_ports)} ports on {self.host}: "
            f"{len(self.poe_capable_ports)} PoE, {len(self.sfp_ports)} SFP"
        )

    def _update_device_info(self, data: Dict[str, Any]) -> None:
        """Update device information from version data."""
        version_info = data.get("version_info", {})
        if version_info:
            self.model = version_info.get("model", self.model)
            self.firmware = version_info.get("firmware_version", self.firmware)
            self.serial_number = version_info.get("serial_number", self.serial_number)
            self.hostname = version_info.get(
                "hostname", getattr(self, "hostname", None)
            )
            self.mac_address = version_info.get(
                "mac_address", getattr(self, "mac_address", None)
            )
            self.hardware_revision = version_info.get(
                "hardware_revision", getattr(self, "hardware_revision", None)
            )
            self.uptime = version_info.get("uptime", getattr(self, "uptime", None))

    def _precalculate_states(self, data: Dict[str, Any]) -> None:
        """Pre-calculate entity states for performance optimization."""
        # This could be expanded to cache calculated values
        # For now, we just ensure data structure is clean
        pass


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Aruba Switch component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Aruba Switch from a config entry."""
    _LOGGER.info("Starting Aruba Switch setup for %s", entry.data["host"])

    # Create and store the coordinator
    _LOGGER.info("Creating coordinator for %s", entry.data["host"])
    coordinator = ArubaSwitchCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Fetch initial data with timeout
    _LOGGER.info("Fetching initial data for %s", entry.data["host"])
    try:
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info("Initial data fetch completed for %s", entry.data["host"])
    except asyncio.TimeoutError:
        _LOGGER.error(
            "Initial data fetch timed out after 60 seconds for %s", entry.data["host"]
        )
        raise ConfigEntryNotReady(
            f"Switch {entry.data['host']} did not respond within timeout"
        )

    # Register device in device registry
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, coordinator.host)},
        name=f"Switch {coordinator.host}",
        manufacturer="HP/Aruba",
        model=coordinator.model,
        sw_version=coordinator.firmware,
        serial_number=(
            coordinator.serial_number
            if coordinator.serial_number != "Unknown"
            else None
        ),
        configuration_url=f"https://{coordinator.host}",
    )

    # Set up platforms (using new v2 architecture)
    _LOGGER.info("Setting up platforms for %s", entry.data["host"])
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "select"])
    _LOGGER.info("All platforms setup completed for %s", entry.data["host"])

    # Add update listener for options flow
    _LOGGER.info("Adding update listener for %s", entry.data["host"])
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    _LOGGER.info("Update listener added for %s", entry.data["host"])

    _LOGGER.info("Aruba Switch setup COMPLETED successfully for %s", entry.data["host"])
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload config entry when options are updated."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload all active platforms (v2 uses sensor and select only)
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in ["sensor", "select"]
            ]
        )
    )

    if unload_ok:
        # Remove the config entry from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
