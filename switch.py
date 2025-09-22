import logging
import asyncio
import paramiko
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import Entity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Aruba switch from a config entry."""
    host = config_entry.data["host"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]
    exclude_ports_str = config_entry.data.get("exclude_ports", "")
    exclude_ports = [p.strip() for p in exclude_ports_str.split(",") if p.strip()]

    # Get port configuration from switch or use default 24 ports
    ports = [str(i) for i in range(1, 25)]  # Generate simple port numbers: 1, 2, 3, etc.
    entities = []

    for port in ports:
        if port not in exclude_ports:
            # Port-Switch
            entities.append(ArubaSwitch(host, username, password, port, False, config_entry.entry_id))
            # PoE-Switch
            entities.append(ArubaSwitch(host, username, password, port, True, config_entry.entry_id))

    async_add_entities(entities, update_before_add=True)


class ArubaSwitch(SwitchEntity):
    """Representation of an Aruba switch port."""
    
    def __init__(self, host, username, password, port, is_poe, entry_id):
        """Initialize the switch."""
        self._host = host
        self._username = username
        self._password = password
        self._port = port
        self._is_poe = is_poe
        self._entry_id = entry_id
        self._is_on = False
        self._available = True
        self._attr_name = f"Port {port} {'PoE' if is_poe else ''}".strip()
        self._attr_unique_id = f"{host}_{port}_{'poe' if is_poe else 'port'}"

    @property
    def name(self):
        """Return the name of the switch."""
        return self._attr_name

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return self._attr_unique_id

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._is_on

    @property
    def available(self):
        """Return if entity is available."""
        return self._available

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": f"Aruba Switch {self._host}",
            "manufacturer": "Aruba",
            "model": "Switch",
        }

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        if self._is_poe:
            command = f"interface 1/{self._port}\npower-over-ethernet\nexit"
        else:
            command = f"interface 1/{self._port}\nno shutdown\nexit"
        
        success = await self._async_send_command(command)
        if success:
            self._is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self._is_poe:
            command = f"interface 1/{self._port}\nno power-over-ethernet\nexit"
        else:
            command = f"interface 1/{self._port}\nshutdown\nexit"
        
        success = await self._async_send_command(command)
        if success:
            self._is_on = False
            self.async_write_ha_state()

    async def async_update(self):
        """Update the switch state."""
        if self._is_poe:
            # Check PoE status
            command = f"show power-over-ethernet 1/{self._port}"
        else:
            # Check interface status
            command = f"show interface 1/{self._port}"
        
        success = await self._async_send_command(command, check_status=True)
        self._available = success

    async def _async_send_command(self, command, check_status=False):
        """Send command to switch via SSH."""
        def _sync_ssh_command():
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(
                    hostname=self._host,
                    username=self._username,
                    password=self._password,
                    timeout=10
                )
                
                if check_status:
                    # For status checks, parse the output to determine actual state
                    stdin, stdout, stderr = ssh.exec_command(command)
                    output = stdout.read().decode()
                    
                    if self._is_poe:
                        # Parse PoE status from output
                        self._is_on = "Enabled" in output or "On" in output
                    else:
                        # Parse interface status from output
                        self._is_on = "up" in output.lower() and "down" not in output.lower()
                else:
                    # For control commands, just execute
                    stdin, stdout, stderr = ssh.exec_command(command)
                    exit_status = stdout.channel.recv_exit_status()
                    if exit_status != 0:
                        error_output = stderr.read().decode()
                        _LOGGER.error(f"Command failed on {self._host}: {error_output}")
                        return False
                
                ssh.close()
                return True
                
            except paramiko.AuthenticationException:
                _LOGGER.error(f"Authentication failed for {self._host}")
                return False
            except paramiko.SSHException as e:
                _LOGGER.error(f"SSH error connecting to {self._host}: {e}")
                return False
            except Exception as e:
                _LOGGER.error(f"Error sending command to {self._host}: {e}")
                return False
        
        # Run SSH command in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_ssh_command)
