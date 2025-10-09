"""Tests for sensor entities."""

import pytest
from unittest.mock import MagicMock

from custom_components.hp_aruba_switch.sensor import (
    ArubaPortSensor,
    ArubaSwitchStatusSensor,
    ArubaPortTrafficSensor,
)


class TestArubaPortSensor:
    """Test ArubaPortSensor."""

    def test_initialization(self, mock_coordinator):
        """Test sensor initialization."""
        sensor = ArubaPortSensor(mock_coordinator, "1", "test_entry")

        assert sensor._port == "1"
        assert sensor._attr_translation_key == "port_statistics"
        assert "port_1" in sensor._attr_unique_id
        assert sensor._attr_icon == "mdi:ethernet"

    def test_native_value_up(self, mock_coordinator):
        """Test native value when port is up."""
        sensor = ArubaPortSensor(mock_coordinator, "1", "test_entry")
        sensor.coordinator = mock_coordinator

        assert sensor.native_value == "up"

    def test_native_value_down(self, mock_coordinator):
        """Test native value when port is down."""
        sensor = ArubaPortSensor(mock_coordinator, "2", "test_entry")
        sensor.coordinator = mock_coordinator

        assert sensor.native_value == "down"

    def test_native_value_disabled(self, mock_coordinator):
        """Test native value when port is disabled."""
        sensor = ArubaPortSensor(mock_coordinator, "3", "test_entry")
        sensor.coordinator = mock_coordinator

        assert sensor.native_value == "disabled"

    def test_extra_state_attributes(self, mock_coordinator):
        """Test extra state attributes."""
        sensor = ArubaPortSensor(mock_coordinator, "1", "test_entry")
        sensor.coordinator = mock_coordinator

        attributes = sensor.extra_state_attributes

        assert attributes["port_enabled"] is True
        assert attributes["link_up"] is True
        assert attributes["link_speed"] == "1000 Mbps"
        assert attributes["duplex"] == "full"
        assert attributes["bytes_in"] == 1234567
        assert attributes["bytes_out"] == 987654
        assert attributes["packets_in"] == 1000
        assert attributes["packets_out"] == 500
        assert attributes["activity"] in ["idle", "low", "medium", "high"]

    def test_calculate_activity_idle(self, mock_coordinator):
        """Test activity calculation for idle port."""
        sensor = ArubaPortSensor(mock_coordinator, "2", "test_entry")

        activity = sensor._calculate_activity({"bytes_rx": 0, "bytes_tx": 0})
        assert activity == "idle"

    def test_calculate_activity_high(self, mock_coordinator):
        """Test activity calculation for high traffic port."""
        sensor = ArubaPortSensor(mock_coordinator, "1", "test_entry")

        activity = sensor._calculate_activity(
            {"bytes_rx": 150_000_000, "bytes_tx": 50_000_000}
        )
        assert activity == "high"

    def test_icon_disabled(self, mock_coordinator):
        """Test icon when port is disabled."""
        sensor = ArubaPortSensor(mock_coordinator, "3", "test_entry")
        sensor.coordinator = mock_coordinator

        assert sensor.icon == "mdi:ethernet-off"

    def test_icon_down(self, mock_coordinator):
        """Test icon when port is down."""
        sensor = ArubaPortSensor(mock_coordinator, "2", "test_entry")
        sensor.coordinator = mock_coordinator

        assert sensor.icon == "mdi:ethernet-cable-off"


class TestArubaSwitchStatusSensor:
    """Test ArubaSwitchStatusSensor."""

    def test_initialization(self, mock_coordinator):
        """Test sensor initialization."""
        sensor = ArubaSwitchStatusSensor(mock_coordinator, "test_entry")

        assert sensor._attr_translation_key == "switch_status"
        assert sensor._attr_icon == "mdi:lan-connect"

    def test_native_value_online(self, mock_coordinator):
        """Test native value when switch is online."""
        sensor = ArubaSwitchStatusSensor(mock_coordinator, "test_entry")
        sensor.coordinator = mock_coordinator

        assert sensor.native_value == "online"

    def test_native_value_offline(self, mock_coordinator):
        """Test native value when switch is offline."""
        mock_coordinator.last_update_success = False
        sensor = ArubaSwitchStatusSensor(mock_coordinator, "test_entry")
        sensor.coordinator = mock_coordinator

        assert sensor.native_value == "offline"

    def test_available_always_true(self, mock_coordinator):
        """Test that status sensor is always available."""
        sensor = ArubaSwitchStatusSensor(mock_coordinator, "test_entry")
        sensor.coordinator = mock_coordinator

        assert sensor.available is True

        # Even when coordinator fails
        mock_coordinator.last_update_success = False
        assert sensor.available is True

    def test_extra_state_attributes(self, mock_coordinator):
        """Test extra state attributes include firmware info."""
        sensor = ArubaSwitchStatusSensor(mock_coordinator, "test_entry")
        sensor.coordinator = mock_coordinator

        attributes = sensor.extra_state_attributes

        assert attributes["host"] == "192.168.1.100"
        assert attributes["model"] == "HP 2530-24G"
        assert attributes["firmware_version"] == "YA.16.11.0001"
        assert attributes["rom_version"] == "YA.16.01"
        assert attributes["serial_number"] == "ABC123456"


class TestArubaPortTrafficSensor:
    """Test ArubaPortTrafficSensor."""

    def test_initialization_in(self, mock_coordinator):
        """Test traffic in sensor initialization."""
        sensor = ArubaPortTrafficSensor(mock_coordinator, "1", "test_entry", "in")

        assert sensor._port == "1"
        assert sensor._direction == "in"
        assert "bytes_in" in sensor._attr_translation_key
        assert sensor._attr_icon == "mdi:download"

    def test_initialization_out(self, mock_coordinator):
        """Test traffic out sensor initialization."""
        sensor = ArubaPortTrafficSensor(mock_coordinator, "1", "test_entry", "out")

        assert sensor._direction == "out"
        assert "bytes_out" in sensor._attr_translation_key
        assert sensor._attr_icon == "mdi:upload"

    def test_native_value_in(self, mock_coordinator):
        """Test native value for bytes in."""
        sensor = ArubaPortTrafficSensor(mock_coordinator, "1", "test_entry", "in")
        sensor.coordinator = mock_coordinator

        assert sensor.native_value == 1234567

    def test_native_value_out(self, mock_coordinator):
        """Test native value for bytes out."""
        sensor = ArubaPortTrafficSensor(mock_coordinator, "1", "test_entry", "out")
        sensor.coordinator = mock_coordinator

        assert sensor.native_value == 987654
