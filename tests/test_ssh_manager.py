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
    
    def test_parse_interface_all_output(self, ssh_manager, load_test_output):
        """Test parsing show interface all output."""
        output = load_test_output("show_interface_all.txt")
        
        if not output:
            pytest.skip("Test data file not available")
        
        interfaces, statistics, link_details = ssh_manager._parse_interface_all_output(output)
        
        assert len(interfaces) > 0
        assert len(statistics) > 0
        assert len(link_details) > 0
        
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
    
    def test_parse_interface_brief_output(self, ssh_manager, load_test_output):
        """Test parsing show interface brief output."""
        output = load_test_output("show_interface_brief.txt")
        
        if not output:
            pytest.skip("Test data file not available")
        
        brief_info = ssh_manager._parse_interface_brief_output(output)
        
        assert len(brief_info) > 0
        
        # Check structure
        first_port = list(brief_info.keys())[0]
        assert "link_speed_mbps" in brief_info[first_port]
        assert "duplex" in brief_info[first_port]
    
    def test_parse_poe_output(self, ssh_manager, load_test_output):
        """Test parsing show power-over-ethernet all output."""
        output = load_test_output("show_power_over_ethernet_all.txt")
        
        if not output:
            pytest.skip("Test data file not available")
        
        poe_ports = ssh_manager._parse_poe_output(output)
        
        assert isinstance(poe_ports, dict)
        
        if len(poe_ports) > 0:
            first_port = list(poe_ports.keys())[0]
            assert "power_enable" in poe_ports[first_port]
            assert "poe_status" in poe_ports[first_port]
    
    def test_parse_version_output(self, ssh_manager, load_test_output):
        """Test parsing show version output."""
        output = load_test_output("show_version.txt")
        
        if not output:
            pytest.skip("Test data file not available")
        
        version_info = ssh_manager._parse_version_output(output)
        
        assert isinstance(version_info, dict)
        
        # Should have at least some version info
        if version_info:
            # Check for common fields
            assert "model" in version_info or "firmware_version" in version_info
    
    def test_split_output_by_commands(self, ssh_manager):
        """Test splitting combined command output."""
        combined_output = """
show interface all
Port 1 statistics
show interface brief
Port | Status
show version
Model: HP 2530
"""
        commands = ["show interface all", "show interface brief", "show version"]
        
        sections = ssh_manager._split_output_by_commands(combined_output, commands)
        
        assert len(sections) > 0
        assert isinstance(sections, dict)
