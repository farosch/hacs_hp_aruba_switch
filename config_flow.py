import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_EXCLUDE_PORTS

class HP2530ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow für HP 2530 Switch Integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=f"HP 2530 Switch ({user_input[CONF_HOST]})",
                data=user_input
            )

        # Form für die UI
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_EXCLUDE_PORTS, default=""): str,  # z.B. "1/1,1/2,1/5"
            })
        )
