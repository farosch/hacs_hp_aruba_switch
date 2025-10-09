"""Integration tests for SSH manager against a real switch.

These tests connect to a real HP/Aruba switch to validate parsing logic.
They can be skipped if the switch is not available.
"""

import pytest
import asyncio
from custom_components.hp_aruba_switch.ssh_manager import ArubaSSHManager


# Real switch credentials - can be overridden with environment variables
REAL_SWITCH_IP = "10.4.20.65"
REAL_SWITCH_USERNAME = "manager"
REAL_SWITCH_PASSWORD = "SY=ojE3%'_s"


class TestRealSwitchIntegration:
    """Integration tests against a real HP/Aruba switch."""

    @pytest.fixture
    def ssh_manager(self):
        """Create SSH manager for real switch."""
        return ArubaSSHManager(
            REAL_SWITCH_IP, REAL_SWITCH_USERNAME, REAL_SWITCH_PASSWORD, 22
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_connectivity(self, ssh_manager):
        """Test basic connectivity to real switch."""
        is_available = await ssh_manager.test_connectivity()
        assert is_available, f"Could not connect to switch at {REAL_SWITCH_IP}"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_execute_show_version(self, ssh_manager):
        """Test executing show version command."""
        output = await ssh_manager.execute_command("show version", timeout=10)
        assert output is not None, "show version returned no output"
        assert len(output.strip()) > 0, "show version output is empty"
        print(f"\n=== Show Version Output ===\n{output}\n")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_execute_show_interface_brief(self, ssh_manager):
        """Test executing show interface brief command."""
        output = await ssh_manager.execute_command("show interface brief", timeout=10)
        assert output is not None, "show interface brief returned no output"
        assert len(output.strip()) > 0, "show interface brief output is empty"
        print(
            f"\n=== Show Interface Brief Output (first 500 chars) ===\n{output[:500]}\n"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_parse_real_show_interface_all(self, ssh_manager):
        """Test parsing real show interface all output."""
        output = await ssh_manager.execute_command("show interface all", timeout=20)
        assert output is not None, "Command returned no output"

        interfaces, statistics, link_details = ssh_manager.parse_show_interface_all(
            output
        )

        assert len(interfaces) > 0, "Should parse at least one interface"
        assert len(statistics) > 0, "Should parse at least one statistics entry"
        assert len(link_details) > 0, "Should parse at least one link detail entry"

        print(f"\n✅ Parsed {len(interfaces)} interfaces from real switch")

        # Verify structure
        first_port = list(interfaces.keys())[0]
        assert "port_enabled" in interfaces[first_port]
        assert "link_status" in interfaces[first_port]
        assert "bytes_rx" in statistics[first_port]
        assert "link_up" in link_details[first_port]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_parse_real_show_interface_brief(self, ssh_manager):
        """Test parsing real show interface brief output."""
        output = await ssh_manager.execute_command("show interface brief", timeout=10)
        assert output is not None, "Command returned no output"

        brief_info = ssh_manager.parse_show_interface_brief(output)

        assert len(brief_info) > 0, "Should parse at least one port"
        print(f"\n✅ Parsed {len(brief_info)} ports from real switch")

        # Verify structure
        first_port = list(brief_info.keys())[0]
        assert "link_speed_mbps" in brief_info[first_port]
        assert "duplex" in brief_info[first_port]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_parse_real_show_power_over_ethernet(self, ssh_manager):
        """Test parsing real show power-over-ethernet all output."""
        output = await ssh_manager.execute_command(
            "show power-over-ethernet all", timeout=10
        )
        assert output is not None, "Command returned no output"

        poe_ports = ssh_manager.parse_show_power_over_ethernet_all(output)

        assert isinstance(poe_ports, dict), "Should return a dictionary"
        print(f"\n✅ Parsed {len(poe_ports)} PoE ports from real switch")

        if len(poe_ports) > 0:
            first_port = list(poe_ports.keys())[0]
            assert "power_enable" in poe_ports[first_port]
            assert "poe_status" in poe_ports[first_port]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_parse_real_show_version(self, ssh_manager):
        """Test parsing real show version output."""
        output = await ssh_manager.execute_command("show version", timeout=10)
        assert output is not None, "Command returned no output"

        version_info = ssh_manager.parse_show_version(output)

        assert isinstance(version_info, dict), "Should return a dictionary"
        assert len(version_info) > 0, "Should parse at least some version info"

        print(f"\n✅ Parsed version info from real switch:")
        print(f"   Model: {version_info.get('model', 'Unknown')}")
        print(f"   Firmware: {version_info.get('firmware_version', 'Unknown')}")

        assert "model" in version_info, "Should have model information"
        assert "firmware_version" in version_info, "Should have firmware version"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_get_all_switch_data_real(self, ssh_manager):
        """Test the complete data collection workflow against real switch."""
        interfaces, statistics, link_details, poe_ports, version_info = (
            await ssh_manager.get_all_switch_data()
        )

        # Should have data from at least some commands
        total_data = (
            len(interfaces)
            + len(statistics)
            + len(link_details)
            + len(poe_ports)
            + len(version_info)
        )
        assert total_data > 0, "Should collect some data from real switch"

        print(f"\n✅ Complete data collection from real switch:")
        print(f"   Interfaces: {len(interfaces)}")
        print(f"   Statistics: {len(statistics)}")
        print(f"   Link Details: {len(link_details)}")
        print(f"   PoE Ports: {len(poe_ports)}")
        print(f"   Version Info: {bool(version_info)}")

        # Verify data consistency
        if interfaces and statistics:
            # Interfaces and statistics should have the same ports
            interface_ports = set(interfaces.keys())
            stats_ports = set(statistics.keys())
            assert (
                interface_ports == stats_ports
            ), "Interface and statistics ports should match"
