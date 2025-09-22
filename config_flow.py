import voluptuous as vol
import paramiko
import logging
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN, CONF_EXCLUDE_PORTS, CONF_EXCLUDE_POE, CONF_SSH_PORT, CONF_PORT_COUNT

_LOGGER = logging.getLogger(__name__)

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate the user input allows us to connect."""
    
    host = data[CONF_HOST]
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    ssh_port = data.get(CONF_SSH_PORT, 22)
    
    # Test SSH connection in executor to avoid blocking
    def _test_connection():
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=host,
                port=ssh_port,
                username=username,
                password=password,
                timeout=15,
                banner_timeout=10,
                auth_timeout=10,
                look_for_keys=False,
                allow_agent=False
            )
            # Test basic command execution
            stdin, stdout, stderr = ssh.exec_command("show version", timeout=10)
            stdout.read()  # Read output to ensure command works
            return True
        except paramiko.AuthenticationException:
            raise InvalidAuth
        except (paramiko.SSHException, EOFError, OSError):
            raise CannotConnect
        finally:
            if ssh:
                try:
                    ssh.close()
                except:
                    pass
    
    # Run connection test in executor
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _test_connection)
    
    # Return info that you want to store in the config entry
    return {"title": f"Aruba Switch ({host}:{ssh_port})"}

class ArubaSwitchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Aruba Switch Integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # UI form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SSH_PORT, default=22): int,
                vol.Optional(CONF_PORT_COUNT, default=24): vol.All(int, vol.Range(min=1, max=48)),
                vol.Optional(CONF_EXCLUDE_PORTS, default=""): str,
                vol.Optional(CONF_EXCLUDE_POE, default=""): str,
            }),
            errors=errors,
        )
