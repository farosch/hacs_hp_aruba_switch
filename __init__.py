from homeassistant.helpers import discovery
from .const import DOMAIN, CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_EXCLUDE_PORTS

async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass, entry):
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    exclude_ports_str = entry.data.get(CONF_EXCLUDE_PORTS, "")
    exclude_ports = [p.strip() for p in exclude_ports_str.split(",") if p.strip()]

    hass.data[DOMAIN][entry.entry_id] = {
        CONF_HOST: host,
        CONF_USERNAME: username,
        CONF_PASSWORD: password,
        CONF_EXCLUDE_PORTS: exclude_ports,
    }

    # Switches registrieren
    hass.async_create_task(
        discovery.async_load_platform(hass, "switch", DOMAIN, entry.data, entry)
    )
    return True
