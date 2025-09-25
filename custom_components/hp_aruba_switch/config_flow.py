import voluptuous as vol
import paramiko
import logging
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN, CONF_EXCLUDE_PORTS, CONF_EXCLUDE_POE, CONF_SSH_PORT, CONF_PORT_COUNT, CONF_REFRESH_INTERVAL

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

    @staticmethod
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        return ArubaSwitchOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        errors = {}
        
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                # Log initialization information for the user
                _LOGGER.info(f"HP/Aruba Switch integration configured for {user_input[CONF_HOST]}. "
                           "Switch controls will be available within 1 minute. Port activity sensors "
                           "will initialize over the next 2-3 minutes with staggered updates to "
                           "avoid overwhelming the switch.")
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
                vol.Optional(CONF_PORT_COUNT, default=24): int,
                vol.Optional(CONF_EXCLUDE_PORTS, default=""): str,
                vol.Optional(CONF_EXCLUDE_POE, default=""): str,
                vol.Optional(CONF_REFRESH_INTERVAL, default=30): vol.All(int, vol.Range(min=10, max=300)),
            }),
            errors=errors,
        )


class ArubaSwitchOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Aruba Switch Integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        
        if user_input is not None:
            # If username or password changed, validate connection
            if (user_input[CONF_USERNAME] != self.config_entry.data.get(CONF_USERNAME) or 
                user_input[CONF_PASSWORD] != self.config_entry.data.get(CONF_PASSWORD)):
                
                # Create validation data with current host and new credentials
                validation_data = {
                    CONF_HOST: self.config_entry.data[CONF_HOST],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_SSH_PORT: user_input[CONF_SSH_PORT],
                }
                
                try:
                    await validate_input(self.hass, validation_data)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception during credential validation")
                    errors["base"] = "unknown"
                
                if errors:
                    # Show form again with errors
                    return self._show_options_form(user_input, errors)
            
            # Update the config entry with new data
            new_data = self.config_entry.data.copy()
            new_data.update(user_input)
            
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            
            # Log the update
            _LOGGER.info(f"HP/Aruba Switch configuration updated for {new_data[CONF_HOST]}. "
                       "Changes will take effect on the next refresh cycle.")
            
            return self.async_create_entry(title="", data={})
        
        return self._show_options_form()

    def _show_options_form(self, user_input=None, errors=None):
        """Show the options form."""
        if errors is None:
            errors = {}
        
        # Get current values from config entry
        current_data = self.config_entry.data
        
        # Use user input if available, otherwise use current config values
        if user_input is not None:
            default_values = user_input
        else:
            default_values = current_data
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME, default=default_values.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD, default=default_values.get(CONF_PASSWORD, "")): str,
                vol.Optional(CONF_SSH_PORT, default=default_values.get(CONF_SSH_PORT, 22)): int,
                vol.Optional(CONF_PORT_COUNT, default=default_values.get(CONF_PORT_COUNT, 24)): int,
                vol.Optional(CONF_EXCLUDE_PORTS, default=default_values.get(CONF_EXCLUDE_PORTS, "")): str,
                vol.Optional(CONF_EXCLUDE_POE, default=default_values.get(CONF_EXCLUDE_POE, "")): str,
                vol.Optional(CONF_REFRESH_INTERVAL, default=default_values.get(CONF_REFRESH_INTERVAL, 30)): vol.All(int, vol.Range(min=10, max=300)),
            }),
            errors=errors,
        )
