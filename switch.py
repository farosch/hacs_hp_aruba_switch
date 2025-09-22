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
    ssh_port = config_entry.data.get("ssh_port", 22)
    exclude_ports_str = config_entry.data.get("exclude_ports", "")
    exclude_ports = [p.strip() for p in exclude_ports_str.split(",") if p.strip()]

    # Get port configuration from switch or use default 24 ports
    ports = [str(i) for i in range(1, 25)]  # Generate simple port numbers: 1, 2, 3, etc.
    entities = []

    for port in ports:
        if port not in exclude_ports:
            # Port-Switch
            entities.append(ArubaSwitch(host, username, password, ssh_port, port, False, config_entry.entry_id))
            # PoE-Switch
            entities.append(ArubaSwitch(host, username, password, ssh_port, port, True, config_entry.entry_id))

    async_add_entities(entities, update_before_add=True)


class ArubaSwitch(SwitchEntity):
    """Representation of an Aruba switch port."""
    
    def __init__(self, host, username, password, ssh_port, port, is_poe, entry_id):
        """Initialize the switch."""
        self._host = host
        self._username = username
        self._password = password
        self._ssh_port = ssh_port
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
            ssh = None
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Enhanced connection parameters for Aruba switches
                connect_params = {
                    'hostname': self._host,
                    'username': self._username,
                    'password': self._password,
                    'port': self._ssh_port,
                    'timeout': 15,  # Increased timeout
                    'auth_timeout': 10,  # Authentication timeout
                    'banner_timeout': 10,  # Banner read timeout
                    'look_for_keys': False,  # Don't look for SSH keys
                    'allow_agent': False,  # Don't use SSH agent
                }
                
                # Try different SSH configurations for compatibility
                ssh_configs = [
                    # Modern SSH (try first)
                    {},
                    # Legacy SSH for older switches
                    {
                        'disabled_algorithms': {
                            'kex': [],
                            'server_host_key_algs': [],
                            'ciphers': [],
                            'macs': []
                        }
                    },
                    # Very old SSH compatibility
                    {
                        'disabled_algorithms': {
                            'kex': ['diffie-hellman-group14-sha256', 'diffie-hellman-group16-sha512'],
                            'server_host_key_algs': [],
                            'ciphers': [],
                            'macs': []
                        }
                    }
                ]
                
                connection_successful = False
                last_error = None
                
                # Try each SSH configuration
                for i, config in enumerate(ssh_configs):
                    try:
                        if ssh:
                            ssh.close()
                        ssh = paramiko.SSHClient()
                        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        
                        # Merge config with base parameters
                        final_params = {**connect_params, **config}
                        ssh.connect(**final_params)
                        
                        connection_successful = True
                        _LOGGER.debug(f"SSH connection successful to {self._host} using config {i}")
                        break
                        
                    except (paramiko.SSHException, EOFError, OSError) as e:
                        last_error = e
                        _LOGGER.debug(f"SSH config {i} failed for {self._host}: {e}")
                        continue
                
                if not connection_successful:
                    _LOGGER.error(f"All SSH connection attempts failed for {self._host}. Last error: {last_error}")
                    return False
                
                if check_status:
                    # For status checks, parse the output to determine actual state
                    stdin, stdout, stderr = ssh.exec_command(command, timeout=10)
                    output = stdout.read().decode('utf-8', errors='ignore')
                    
                    if self._is_poe:
                        # Parse PoE status from output
                        output_lower = output.lower()
                        self._is_on = any(keyword in output_lower for keyword in [
                            'enabled', 'on', 'delivering', 'active'
                        ])
                    else:
                        # Parse interface status from output
                        output_lower = output.lower()
                        # Interface is up if it contains "up" but not "down"
                        has_up = 'up' in output_lower
                        has_down = 'down' in output_lower and 'up' not in output_lower.split('down')[0]
                        self._is_on = has_up and not has_down
                else:
                    # For control commands, execute with timeout
                    stdin, stdout, stderr = ssh.exec_command(command, timeout=15)
                    exit_status = stdout.channel.recv_exit_status()
                    if exit_status != 0:
                        error_output = stderr.read().decode('utf-8', errors='ignore')
                        _LOGGER.error(f"Command failed on {self._host}: {error_output}")
                        return False
                
                return True
                
            except paramiko.AuthenticationException as e:
                _LOGGER.error(f"Authentication failed for {self._host}: {e}")
                return False
            except paramiko.SSHException as e:
                _LOGGER.error(f"SSH protocol error connecting to {self._host}: {e}")
                # Check if this might be a port/service issue
                if "banner" in str(e).lower():
                    _LOGGER.error(f"SSH banner error - check if SSH is enabled on {self._host} and accessible on port 22")
                return False
            except (EOFError, OSError) as e:
                _LOGGER.error(f"Network error connecting to {self._host}: {e}")
                _LOGGER.error(f"Check network connectivity and SSH service status on {self._host}")
                return False
            except Exception as e:
                _LOGGER.error(f"Unexpected error connecting to {self._host}: {e}")
                return False
            finally:
                if ssh:
                    try:
                        ssh.close()
                    except:
                        pass
        
        # Run SSH command in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_ssh_command)
