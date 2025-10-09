import voluptuous as vol  # type: ignore
import paramiko  # type: ignore
import logging
from homeassistant import config_entries  # type: ignore
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD  # type: ignore
from homeassistant.core import HomeAssistant  # type: ignore
from homeassistant.exceptions import HomeAssistantError  # type: ignore
from .const import DOMAIN, CONF_SSH_PORT, CONF_PORT_COUNT, CONF_REFRESH_INTERVAL

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
                allow_agent=False,
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
                except Exception as e:
                    _LOGGER.debug(
                        f"Error closing SSH connection during validation: {e}"
                    )

    # Run connection test in executor
    import asyncio

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _test_connection)

    # Return info that you want to store in the config entry
    return {"title": f"Aruba Switch ({host}:{ssh_port})"}


class ArubaSwitchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Aruba Switch Integration."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}

    @staticmethod
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        return ArubaSwitchOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Single step: connection details, port count, and dynamic exclusion checkboxes."""
        errors = {}
        # Use previous input or defaults
        data = user_input or {}
        port_count = int(data.get(CONF_PORT_COUNT, 24))

        # Build dynamic schema
        schema_dict = {
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
            vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
            vol.Optional(CONF_SSH_PORT, default=data.get(CONF_SSH_PORT, 22)): int,
            vol.Optional(CONF_PORT_COUNT, default=port_count): int,
            vol.Optional(
                CONF_REFRESH_INTERVAL, default=data.get(CONF_REFRESH_INTERVAL, 30)
            ): vol.All(int, vol.Range(min=10, max=300)),
        }

        if user_input is not None:
            # If required fields are present, validate connection
            required_fields = [CONF_HOST, CONF_USERNAME, CONF_PASSWORD]
            if all(data.get(f) for f in required_fields):
                try:
                    info = await validate_input(self.hass, data)
                    entry_data = {
                        CONF_HOST: data[CONF_HOST],
                        CONF_USERNAME: data[CONF_USERNAME],
                        CONF_PASSWORD: data[CONF_PASSWORD],
                        CONF_SSH_PORT: int(data.get(CONF_SSH_PORT, 22)),
                        CONF_PORT_COUNT: port_count,
                        CONF_REFRESH_INTERVAL: int(data.get(CONF_REFRESH_INTERVAL, 30)),
                    }
                    return self.async_create_entry(
                        title=f"Aruba Switch ({entry_data[CONF_HOST]}:{entry_data[CONF_SSH_PORT]})",
                        data=entry_data,
                    )
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except Exception:
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )


class ArubaSwitchOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Aruba Switch Integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self._data = {}

    async def async_step_init(self, user_input=None):
        """Manage the options - connection details and port count."""
        errors = {}

        if user_input is not None:
            # If username or password changed, validate connection
            if user_input[CONF_USERNAME] != self.config_entry.data.get(
                CONF_USERNAME
            ) or user_input[CONF_PASSWORD] != self.config_entry.data.get(CONF_PASSWORD):

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
                    _LOGGER.exception(
                        "Unexpected exception during credential validation"
                    )
                    errors["base"] = "unknown"

                if errors:
                    # Show form again with errors
                    return self._show_options_form(user_input, errors)

            # Store data for next step
            self._data = user_input.copy()
            self._data[CONF_HOST] = self.config_entry.data[CONF_HOST]  # Preserve host

            # Move to port exclusion step
            return await self.async_step_port_exclusion()

        return self._show_options_form()

    async def async_step_port_exclusion(self, user_input=None):
        """Handle the port exclusion step with checkboxes."""
        if user_input is not None:
            # Convert checkbox selections to comma-separated strings
            exclude_ports = []
            exclude_poe = []

            for key, value in user_input.items():
                if key.startswith("exclude_port_") and value:
                    port_num = key.replace("exclude_port_", "")
                    exclude_ports.append(port_num)
                elif key.startswith("exclude_poe_") and value:
                    port_num = key.replace("exclude_poe_", "")
                    exclude_poe.append(port_num)

            # Add exclusions to the stored data
            self._data[CONF_EXCLUDE_PORTS] = ",".join(exclude_ports)
            self._data[CONF_EXCLUDE_POE] = ",".join(exclude_poe)

            # Update the config entry with new data
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=self._data
            )

            # Log the update
            _LOGGER.info(
                f"HP/Aruba Switch configuration updated for {self._data[CONF_HOST]}. "
                "Changes will take effect on the next refresh cycle."
            )

            return self.async_create_entry(title="", data={})

        # Generate checkbox schema based on port count
        port_count = self._data.get(CONF_PORT_COUNT, 24)

        # Exclusion logic removed

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
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=default_values.get(CONF_USERNAME, "")
                    ): str,
                    vol.Required(
                        CONF_PASSWORD, default=default_values.get(CONF_PASSWORD, "")
                    ): str,
                    vol.Optional(
                        CONF_SSH_PORT, default=default_values.get(CONF_SSH_PORT, 22)
                    ): int,
                    vol.Optional(
                        CONF_PORT_COUNT, default=default_values.get(CONF_PORT_COUNT, 24)
                    ): int,
                    vol.Optional(
                        CONF_REFRESH_INTERVAL,
                        default=default_values.get(CONF_REFRESH_INTERVAL, 30),
                    ): vol.All(int, vol.Range(min=10, max=300)),
                }
            ),
            errors=errors,
        )
