"""Tests for select entities."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.hp_aruba_switch.select import ArubaPortControl


class TestArubaPortControl:
    """Test ArubaPortControl."""

    def test_initialization_with_poe(self, mock_coordinator):
        """Test initialization for PoE-capable port."""
        select = ArubaPortControl(mock_coordinator, "1", "test_entry", has_poe=True)

        assert select._port == "1"
        assert select._has_poe is True
        assert select._attr_translation_key == "port_control"
        assert len(select._attr_options) == 4
        assert "enabled_poe_on" in select._attr_options

    def test_initialization_without_poe(self, mock_coordinator):
        """Test initialization for non-PoE port."""
        select = ArubaPortControl(mock_coordinator, "3", "test_entry", has_poe=False)

        assert select._has_poe is False
        assert len(select._attr_options) == 2
        assert "enabled_poe_on" not in select._attr_options

    def test_current_option_disabled(self, mock_coordinator):
        """Test current option when port is disabled."""
        select = ArubaPortControl(mock_coordinator, "3", "test_entry", has_poe=False)
        select.coordinator = mock_coordinator

        assert select.current_option == "disabled"

    def test_current_option_enabled(self, mock_coordinator):
        """Test current option when port is enabled without PoE."""
        select = ArubaPortControl(mock_coordinator, "3", "test_entry", has_poe=False)
        select.coordinator = mock_coordinator

        # Modify data for enabled port
        mock_coordinator.data["interfaces"]["3"]["port_enabled"] = True

        assert select.current_option == "enabled"

    def test_current_option_enabled_poe_on(self, mock_coordinator):
        """Test current option when port is enabled with PoE on."""
        select = ArubaPortControl(mock_coordinator, "1", "test_entry", has_poe=True)
        select.coordinator = mock_coordinator

        assert select.current_option == "enabled_poe_on"

    def test_current_option_enabled_poe_off(self, mock_coordinator):
        """Test current option when port is enabled with PoE off."""
        select = ArubaPortControl(mock_coordinator, "2", "test_entry", has_poe=True)
        select.coordinator = mock_coordinator

        assert select.current_option == "enabled_poe_off"

    def test_icon_disabled(self, mock_coordinator):
        """Test icon when port is disabled."""
        select = ArubaPortControl(mock_coordinator, "3", "test_entry", has_poe=False)
        select.coordinator = mock_coordinator

        assert select.icon == "mdi:ethernet-off"

    def test_icon_poe_on(self, mock_coordinator):
        """Test icon when PoE is on."""
        select = ArubaPortControl(mock_coordinator, "1", "test_entry", has_poe=True)
        select.coordinator = mock_coordinator

        assert select.icon == "mdi:flash"

    @pytest.mark.asyncio
    async def test_async_select_option_disabled(self, mock_coordinator):
        """Test selecting disabled option."""
        select = ArubaPortControl(mock_coordinator, "1", "test_entry", has_poe=True)
        select.coordinator = mock_coordinator
        select.coordinator.async_request_refresh = AsyncMock()

        with patch.object(
            select, "_disable_port", new_callable=AsyncMock
        ) as mock_disable:
            await select.async_select_option("disabled")
            mock_disable.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_select_option_enabled(self, mock_coordinator):
        """Test selecting enabled option."""
        select = ArubaPortControl(mock_coordinator, "1", "test_entry", has_poe=True)
        select.coordinator = mock_coordinator
        select.coordinator.async_request_refresh = AsyncMock()

        with patch.object(
            select, "_enable_port", new_callable=AsyncMock
        ) as mock_enable, patch.object(
            select, "_set_poe_auto", new_callable=AsyncMock
        ) as mock_poe_auto:
            await select.async_select_option("enabled")
            mock_enable.assert_called_once()
            mock_poe_auto.assert_called_once()
