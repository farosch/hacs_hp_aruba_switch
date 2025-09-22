import logging
import paramiko
from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return

    host = discovery_info["host"]
    username = discovery_info["username"]
    password = discovery_info["password"]
    exclude_ports = discovery_info.get("exclude_ports", [])

    # Angenommen Switch hat 24 Ports
    ports = [f"1/{i}" for i in range(1, 25)]
    entities = []

    for port in ports:
        # Port-Switch
        entities.append(HPPortSwitch(host, username, password, port, exclude_ports, poe=False))
        # PoE-Switch
        entities.append(HPPortSwitch(host, username, password, port, exclude_ports, poe=True))

    async_add_entities(entities)


class HPPortSwitch(SwitchEntity):
    def __init__(self, host, username, password, port, exclude_ports, poe=False):
        self._host = host
        self._username = username
        self._password = password
        self._port = port
        self._exclude_ports = exclude_ports
        self._poe = poe
        self._is_on = False
        self._name = f"{'PoE ' if poe else 'Port '} {port}"

    @property
    def name(self):
        return self._name

    @property
    def is_on(self):
        return self._is_on

    def turn_on(self, **kwargs):
        if self._port in self._exclude_ports:
            _LOGGER.warning(f"{'PoE ' if self._poe else 'Port '} {self._port} ist gesperrt")
            return
        cmd = f"interface {self._port}\n"
        cmd += "power-over-ethernet" if self._poe else "no shutdown"
        self._send_command(cmd)
        self._is_on = True

    def turn_off(self, **kwargs):
        if self._port in self._exclude_ports:
            _LOGGER.warning(f"{'PoE ' if self._poe else 'Port '} {self._port} ist gesperrt")
            return
        cmd = f"interface {self._port}\n"
        cmd += "no power-over-ethernet" if self._poe else "shutdown"
        self._send_command(cmd)
        self._is_on = False

    def _send_command(self, command):
        _LOGGER.debug(f"Send command to {self._host}: {command}")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(self._host, username=self._username, password=self._password)
            stdin, stdout, stderr = ssh.exec_command(command)
            stdout.channel.recv_exit_status()
        except Exception as e:
            _LOGGER.error(f"Fehler beim Senden des Befehls an {self._host}: {e}")
        finally:
            ssh.close()
