"""Tests for SSH manager parsing logic."""
import pytest
from unittest.mock import MagicMock, patch

from custom_components.hp_aruba_switch.ssh_manager import ArubaSSHManager


class TestArubaSSHManager:
    """Test ArubaSSHManager parsing methods."""
    
    @pytest.fixture
    def ssh_manager(self):
        """Create SSH manager instance."""
        return ArubaSSHManager("192.168.1.100", "admin", "password", 22)
    
    def test_parse_show_interface_all(self, ssh_manager, load_test_output):
        """Test parsing show interface all output."""
        output = load_test_output("show_interface_all.txt")
        
        if not output:
            pytest.skip("Test data file not available")
        
        interfaces, statistics, link_details = ssh_manager.parse_show_interface_all(output)
        
        assert len(interfaces) > 0, "Should parse at least one interface"
        assert len(statistics) > 0, "Should parse at least one statistics entry"
        assert len(link_details) > 0, "Should parse at least one link detail entry"
        
        # Check structure of first port
        first_port = list(interfaces.keys())[0]
        assert "port_enabled" in interfaces[first_port]
        assert "link_status" in interfaces[first_port]
        
        assert "bytes_rx" in statistics[first_port]
        assert "bytes_tx" in statistics[first_port]
        assert "unicast_rx" in statistics[first_port]
        assert "unicast_tx" in statistics[first_port]
        
        assert "link_up" in link_details[first_port]
        assert "port_enabled" in link_details[first_port]
        
        # Verify specific values from test data
        assert "1" in interfaces, "Port 1 should be present"
        assert interfaces["1"]["link_status"] == "up", "Port 1 should be up"
        assert statistics["1"]["bytes_rx"] > 0, "Port 1 should have RX bytes"
    
    def test_parse_show_interface_brief(self, ssh_manager, load_test_output):
        """Test parsing show interface brief output."""
        output = load_test_output("show_interface_brief.txt")
        
        if not output:
            pytest.skip("Test data file not available")
        
        brief_info = ssh_manager.parse_show_interface_brief(output)
        
        assert len(brief_info) > 0, "Should parse at least one port"
        
        # Check structure
        first_port = list(brief_info.keys())[0]
        assert "link_speed_mbps" in brief_info[first_port]
        assert "duplex" in brief_info[first_port]
        
        # Verify specific values from test data
        assert "1" in brief_info, "Port 1 should be present"
        assert brief_info["1"]["link_speed_mbps"] == 1000, "Port 1 should be 1000 Mbps"
        assert brief_info["1"]["duplex"] == "full", "Port 1 should be full duplex"
    
    def test_parse_show_power_over_ethernet_all(self, ssh_manager, load_test_output):
        """Test parsing show power-over-ethernet all output."""
        output = load_test_output("show_power_over_ethernet_all.txt")
        
        if not output:
            pytest.skip("Test data file not available")
        
        poe_ports = ssh_manager.parse_show_power_over_ethernet_all(output)
        
        assert isinstance(poe_ports, dict), "Should return a dictionary"
        assert len(poe_ports) > 0, "Should parse at least one PoE port"
        
        # Check structure
        first_port = list(poe_ports.keys())[0]
        assert "power_enable" in poe_ports[first_port]
        assert "poe_status" in poe_ports[first_port]
        
        # Verify specific values from test data
        assert "1" in poe_ports, "Port 1 should be present"
        assert poe_ports["1"]["power_enable"] == True, "Port 1 should have PoE enabled"
        assert poe_ports["1"]["poe_status"] in ["searching", "delivering", "off"], "Port 1 should have valid PoE status"
    
    def test_parse_show_version(self, ssh_manager, load_test_output):
        """Test parsing show version output."""
        output = load_test_output("show_version.txt")
        
        if not output:
            pytest.skip("Test data file not available")
        
        version_info = ssh_manager.parse_show_version(output)
        
        assert isinstance(version_info, dict), "Should return a dictionary"
        assert len(version_info) > 0, "Should parse at least some version info"
        
        # Should have at least some version info
        assert "model" in version_info, "Should have model information"
        assert "firmware_version" in version_info, "Should have firmware version"
        
        # Verify specific values from test data (HP-2530-24G-PoEP, YA.16.08.0002)
        assert "HP-2530-24G-PoEP" in version_info["model"] or "2530" in version_info["model"], "Should detect correct model"
        assert "YA.16.08" in version_info["firmware_version"], "Should detect correct firmware version"
