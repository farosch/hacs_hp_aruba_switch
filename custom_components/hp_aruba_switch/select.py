"""Select entities for HP/Aruba Switch port control (v2 architecture)."""

import asyncio
import logging
from typing import Any, Dict, Optional

import paramiko  # type: ignore
from homeassistant.components.select import SelectEntity  # type: ignore
from homeassistant.helpers.restore_state import RestoreEntity  # type: ignore

from .const import DOMAIN
from .entity import ArubaSwitchEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch select entities from a config entry."""
    _LOGGER.debug("HP/Aruba Switch select platform starting setup (v2 architecture)")

    # Get the coordinator from hass.data
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Wait for port detection if not ready
    if not coordinator.detected_ports:
        _LOGGER.debug("Waiting for port detection...")
        await coordinator.async_request_refresh()
        await asyncio.sleep(2)

    entities = []

    # Create port control select entities for detected ports
    for port in sorted(
        coordinator.detected_ports, key=lambda x: int(x) if x.isdigit() else 999
    ):
        port_config = coordinator.port_configs.get(port, {})
        has_poe = port_config.get("poe_capable", False)

        entities.append(
            ArubaPortControl(coordinator, port, config_entry.entry_id, has_poe)
        )

    _LOGGER.info(
        f"Created {len(entities)} port control entities for {len(coordinator.detected_ports)} ports"
    )

    async_add_entities(entities, update_before_add=False)


class ArubaPortControl(ArubaSwitchEntity, SelectEntity, RestoreEntity):
    """Consolidated port control with multiple operational modes."""

    # Port operational modes
    OPTIONS = [
        "enabled",  # Port enabled, PoE auto
        "disabled",  # Port administratively disabled
        "enabled_poe_off",  # Port enabled, PoE explicitly off
        "enabled_poe_on",  # Port enabled, PoE explicitly on
    ]

    def __init__(self, coordinator, port: str, entry_id: str, has_poe: bool = False):
        """Initialize the port control select entity."""
        super().__init__(coordinator, entry_id)
        self._port = port
        self._has_poe = has_poe
        self._attr_translation_key = "port_control"
        self._attr_name = f"Port {port} Control"
        self._attr_unique_id = (
            f"aruba_switch_{coordinator.host.replace('.', '_')}_port_{port}_control"
        )
        self._attr_icon = "mdi:ethernet-cable"

        # Set available options based on PoE capability
        if has_poe:
            self._attr_options = self.OPTIONS
        else:
            self._attr_options = ["enabled", "disabled"]

    async def async_added_to_hass(self):
        """Restore last state when added to hass."""
        await super().async_added_to_hass()
        if last_state := await self.async_get_last_state():
            if last_state.state in self._attr_options:
                self._attr_current_option = last_state.state
                _LOGGER.debug(
                    f"Restored port {self._port} control state: {last_state.state}"
                )

    @property
    def current_option(self) -> Optional[str]:
        """Return the current operational mode."""
        data = self._get_coordinator_data()
        if not data:
            return None

        interfaces = data.get("interfaces", {})
        poe_ports = data.get("poe_ports", {})

        port_data = interfaces.get(self._port, {})
        poe_data = poe_ports.get(self._port, {})

        port_enabled = port_data.get("port_enabled", False)

        if not port_enabled:
            return "disabled"

        if self._has_poe:
            poe_enabled = poe_data.get("power_enable", False)
            poe_status = poe_data.get("poe_status", "").lower()

            if poe_enabled and poe_status in ["delivering", "searching", "enabled"]:
                return "enabled_poe_on"
            elif not poe_enabled:
                return "enabled_poe_off"
            else:
                return "enabled"  # Auto mode

        return "enabled"

    async def async_select_option(self, option: str) -> None:
        """Change the port operational mode."""
        if option not in self._attr_options:
            _LOGGER.error(f"Invalid option '{option}' for port {self._port}")
            return

        _LOGGER.info(f"Setting port {self._port} to mode: {option}")

        try:
            if option == "disabled":
                await self._disable_port()
            elif option == "enabled":
                await self._enable_port()
                if self._has_poe:
                    # Auto mode - let switch decide
                    await self._set_poe_auto()
            elif option == "enabled_poe_off":
                await self._enable_port()
                await self._disable_poe()
            elif option == "enabled_poe_on":
                await self._enable_port()
                await self._enable_poe()

            # Request coordinator refresh after change
            await asyncio.sleep(2)  # Wait for switch to process
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error(f"Failed to change port {self._port} mode to {option}: {e}")

    async def _enable_port(self) -> None:
        """Enable the port administratively."""
        ssh_manager = self.coordinator.ssh_manager
        commands = f"configure\\ninterface {self._port}\\nenable\\nexit\\nexit\\n"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._sync_execute_commands, ssh_manager, commands
        )

    async def _disable_port(self) -> None:
        """Disable the port administratively."""
        ssh_manager = self.coordinator.ssh_manager
        commands = f"configure\\ninterface {self._port}\\ndisable\\nexit\\nexit\\n"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._sync_execute_commands, ssh_manager, commands
        )

    async def _enable_poe(self) -> None:
        """Enable PoE on the port."""
        if not self._has_poe:
            return

        ssh_manager = self.coordinator.ssh_manager
        commands = (
            f"configure\\ninterface {self._port}\\npower-over-ethernet\\nexit\\nexit\\n"
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._sync_execute_commands, ssh_manager, commands
        )

    async def _disable_poe(self) -> None:
        """Disable PoE on the port."""
        if not self._has_poe:
            return

        ssh_manager = self.coordinator.ssh_manager
        commands = f"configure\\ninterface {self._port}\\nno power-over-ethernet\\nexit\\nexit\\n"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._sync_execute_commands, ssh_manager, commands
        )

    async def _set_poe_auto(self) -> None:
        """Set PoE to auto mode (let switch decide)."""
        if not self._has_poe:
            return

        # For most HP/Aruba switches, removing explicit config enables auto
        ssh_manager = self.coordinator.ssh_manager
        commands = f"configure\\ninterface {self._port}\\nno power-over-ethernet\\npower-over-ethernet\\nexit\\nexit\\n"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._sync_execute_commands, ssh_manager, commands
        )

    def _sync_execute_commands(self, ssh_manager, commands: str) -> None:
        """Execute commands synchronously (runs in executor)."""
        import time

        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=ssh_manager.host,
                port=ssh_manager.ssh_port,
                username=ssh_manager.username,
                password=ssh_manager.password,
                timeout=15,
                look_for_keys=False,
                allow_agent=False,
            )

            shell = ssh.invoke_shell()
            shell.send("\\n")
            time.sleep(0.5)

            shell.send("no page\\n")
            time.sleep(0.5)

            if shell.recv_ready():
                shell.recv(4096)

            # Send commands
            for cmd in commands.split("\\n"):
                if cmd.strip():
                    shell.send(cmd.strip() + "\\n")
                    time.sleep(0.8)

            time.sleep(1)

            # Collect output
            output = ""
            if shell.recv_ready():
                output = shell.recv(4096).decode("utf-8", errors="ignore")

            shell.close()
            _LOGGER.debug(f"Port control commands executed: {output[:200]}")

        except Exception as e:
            _LOGGER.error(f"Failed to execute port control commands: {e}")
            raise
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass

    @property
    def icon(self) -> str:
        """Return dynamic icon based on current mode."""
        option = self.current_option

        if option == "disabled":
            return "mdi:ethernet-off"
        elif option == "enabled_poe_on":
            return "mdi:flash"
        elif option == "enabled_poe_off":
            return "mdi:flash-off"
        else:
            return "mdi:ethernet"
