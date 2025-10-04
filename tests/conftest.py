"""Pytest configuration and fixtures for HP/Aruba Switch tests."""
import pytest
from unittest.mock import MagicMock, patch
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from custom_components.hp_aruba_switch.const import DOMAIN


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Test Switch",
        data={
            "host": "192.168.1.100",
            "username": "admin",
            "password": "password",
            "ssh_port": 22,
            "port_count": 24,
            "exclude_ports": "",
            "exclude_poe": "",
            "refresh_interval": 30,
        },
        source="user",
        entry_id="test_entry_id",
    )


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.host = "192.168.1.100"
    coordinator.model = "HP 2530-24G"
    coordinator.firmware = "YA.16.11.0001"
    coordinator.serial_number = "ABC123456"
    coordinator.detected_ports = {"1", "2", "3", "4", "5"}
    coordinator.poe_capable_ports = {"1", "2"}
    coordinator.sfp_ports = set()
    coordinator.port_configs = {
        "1": {"poe_capable": True, "is_sfp": False, "detected": True},
        "2": {"poe_capable": True, "is_sfp": False, "detected": True},
        "3": {"poe_capable": False, "is_sfp": False, "detected": True},
        "4": {"poe_capable": False, "is_sfp": False, "detected": True},
        "5": {"poe_capable": False, "is_sfp": False, "detected": True},
    }
    coordinator.last_update_success = True
    coordinator.data = {
        "available": True,
        "interfaces": {
            "1": {"port_enabled": True, "link_status": "up"},
            "2": {"port_enabled": True, "link_status": "down"},
            "3": {"port_enabled": False, "link_status": "down"},
        },
        "statistics": {
            "1": {"bytes_rx": 1234567, "bytes_tx": 987654, "unicast_rx": 1000, "unicast_tx": 500},
            "2": {"bytes_rx": 0, "bytes_tx": 0, "unicast_rx": 0, "unicast_tx": 0},
            "3": {"bytes_rx": 0, "bytes_tx": 0, "unicast_rx": 0, "unicast_tx": 0},
        },
        "link_details": {
            "1": {
                "port_enabled": True,
                "link_up": True,
                "link_speed": "1000 Mbps",
                "duplex": "full",
                "auto_negotiation": "enabled",
                "cable_type": "Cat5e",
            },
            "2": {
                "port_enabled": True,
                "link_up": False,
                "link_speed": "unknown",
                "duplex": "unknown",
                "auto_negotiation": "enabled",
                "cable_type": "unknown",
            },
            "3": {
                "port_enabled": False,
                "link_up": False,
                "link_speed": "unknown",
                "duplex": "unknown",
                "auto_negotiation": "unknown",
                "cable_type": "unknown",
            },
        },
        "poe_ports": {
            "1": {"power_enable": True, "poe_status": "delivering"},
            "2": {"power_enable": False, "poe_status": "off"},
        },
        "version_info": {
            "model": "HP 2530-24G",
            "firmware_version": "YA.16.11.0001",
            "rom_version": "YA.16.01",
            "serial_number": "ABC123456",
        },
        "last_successful_connection": 1696435200.0,
    }
    return coordinator


@pytest.fixture
def load_test_output():
    """Load test output files."""
    import os
    from pathlib import Path
    
    test_data_dir = Path(__file__).parent / "test_data"
    
    def _load(filename):
        """Load a test output file."""
        filepath = test_data_dir / filename
        if filepath.exists():
            return filepath.read_text()
        return ""
    
    return _load
