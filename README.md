# HP/Aruba Switch Integration for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license-url]

A Home Assistant custom integration that provides control over HP/Aruba switch ports and PoE management through SSH connectivity.

## 🌟 **Key Features**

### 🔌 **Port Management**
- Enable/disable individual switch ports
- Real-time port status monitoring (link up/down)
- Support for 24-port switches (easily configurable)

### ⚡ **PoE Control**  
- Individual PoE port enable/disable
- Real-time PoE status monitoring
- Power delivery status tracking
- Separate control from regular port functions

### 🚀 **Performance Optimized**
- Connection pooling for efficient SSH management
- Staggered updates to prevent switch overload
- Configurable update intervals
- Error handling and automatic retry logic

### 🔄 **Reliability & Monitoring**
- Automatic offline detection with entity unavailability
- Switch connectivity status sensor
- Smart recovery when switch comes back online
- Clear logging for troubleshooting network issues

## Supported Devices

This integration works with HP/Aruba switches that support SSH access, including:

- HP 2530 Series (tested)
- HP 2540 Series
- HP 2920 Series
- HP 2930F Series
- Aruba 2540 Series
- Aruba 2930F Series
- Aruba 2930M Series

**Requirements:**
- SSH access enabled on the switch
- Valid administrator credentials
- Network connectivity between Home Assistant and the switch

## Architecture & Performance

The integration uses a **single SSH session** architecture for optimal performance:

- **Centralized Coordinator**: One coordinator manages all switch communication
- **Bulk Data Collection**: Every 30 seconds, executes 4 SSH commands to collect data for ALL ports
- **Efficient Caching**: All entities read from shared cache - no individual SSH calls
- **Switch Protection**: Maximum 1 concurrent SSH session prevents switch overload
- **Staggered Updates**: Entities update at different intervals to spread load
- **Smart Recovery**: Automatic reconnection and offline detection

This design ensures reliable operation even with 50+ entities without overwhelming the switch or network.

## Installation

### HACS (Recommended)

#### Use My Home Assistant link

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hp_aruba_switch)

#### Use HACS manually

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the "+" button
4. Search for "HP/Aruba Switch"
5. Install the integration
6. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `hp_aruba_switch` folder to your `custom_components` directory
3. Restart Home Assistant

## Configuration

### Initial Setup

1. In Home Assistant, go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "HP/Aruba Switch"
4. Enter your switch details:
   - **Host**: IP address or hostname of your switch
   - **Username**: Switch administrator username
   - **Password**: Switch administrator password
   - **SSH Port**: SSH port (default: 22)

### Configuration Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| Host | Yes | - | IP address or hostname of the switch |
| Username | Yes | - | Administrator username |
| Password | Yes | - | Administrator password |
| SSH Port | Yes | 22 | SSH port number |
| Ports | Yes | - | Amount of Ports (e.g., "24") |

## Entities Created

After successful configuration, the integration creates the following entities:

### Switch Entities
For each port (e.g., port 1):
- `sensor.hp_aruba_switch_xxx_xxx_xxx_xxx_port_1` - Port sensor with comprehensive data (link status, speed, traffic, PoE status, etc. as attributes)
- `switch.hp_aruba_switch_xxx_xxx_xxx_xxx_port_1` - Port control (enable/disable)
- `switch.hp_aruba_switch_xxx_xxx_xxx_xxx_poe_1` - PoE control (enable/disable)

### Switch Information
All switch information (firmware version, model, serial number, uptime, etc.) is available as device attributes and in the consolidated port sensors.

All entities are automatically created and registered in Home Assistant with proper device information.

## 🔧 **Configuration Options**

## Usage Examples

### Automations

**Turn off PoE overnight:**
```yaml
automation:
  - alias: "Turn off PoE at night"
    trigger:
      platform: time
      at: "23:00:00"
    action:
      service: switch.turn_off
      target:
        entity_id: switch.hp_aruba_switch_192_168_1_100_poe_1
```

**Monitor port status:**
```yaml
automation:
  - alias: "Alert on port down"
    trigger:
      platform: state
      entity_id: switch.hp_aruba_switch_192_168_1_100_port_24
      to: 'off'
    action:
      service: notify.mobile_app
      data:
        message: "Switch port 24 is down!"
```

### Scripts

**Reboot device on port:**
```yaml
script:
  reboot_device_port_1:
    sequence:
      - service: switch.turn_off
        target:
          entity_id: switch.hp_aruba_switch_192_168_1_100_poe_1
      - delay: "00:00:10"
      - service: switch.turn_on
        target:
          entity_id: switch.hp_aruba_switch_192_168_1_100_poe_1
```

## Troubleshooting

### Common Issues

**Cannot connect to switch:**
- Verify SSH is enabled on the switch
- Check firewall rules
- Ensure credentials are correct
- Verify network connectivity

**Entities not updating:**
- Check Home Assistant logs for SSH errors
- Verify switch command syntax compatibility
- Consider increasing update intervals for better performance

**Performance issues:**
- Check network latency to switch
- Monitor Home Assistant resource usage

### Debug Logging

Add to your `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.hp_aruba_switch: debug
    paramiko: debug
```

### Entity Naming

Entities are named using the format:
- `switch.hp_aruba_switch_{ip_with_underscores}_{port}_{type}`
- Example: `switch.hp_aruba_switch_192_168_1_100_port_1`

## Switch Commands Used

The integration uses these switch commands:

### Port Control
```bash
configure
interface X
enable  # or disable
exit
write mem
exit
```

### PoE Control
```bash
configure
interface X
power-over-ethernet  # or no power-over-ethernet
exit
write mem
exit
```

### Status Checking
```bash
show interface all
show power-over-ethernet
```

## Testing

### Running Tests Locally

```bash
# Install dependencies
pip install paramiko

# Run unit tests with test data
python tests/run_tests.py
```

### Test Data

Test data files are located in `tests/test_data/` and contain real output from HP/Aruba switches:
- `show_interface_all.txt`
- `show_interface_brief.txt`
- `show_power_over_ethernet_all.txt`
- `show_version.txt`

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

**Before submitting:**
1. Run tests locally: `python tests/run_tests.py`
2. Ensure all Python files compile: `python -m compileall custom_components/hp_aruba_switch/`
3. Update `RELEASE_NOTES.md` if adding features or fixing bugs

The CI/CD pipeline will automatically run tests on your pull request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/farosch/hacs_hp_aruba_switch/issues)
- **Discussions**: [Home Assistant Community](https://community.home-assistant.io/)

<!-- Badge Definitions -->
[releases-shield]: https://img.shields.io/github/release/farosch/hacs_hp_aruba_switch.svg?style=for-the-badge
[releases]: https://github.com/farosch/hacs_hp_aruba_switch/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/farosch/hacs_hp_aruba_switch.svg?style=for-the-badge
[commits]: https://github.com/farosch/hacs_hp_aruba_switch/commits/main
[license-shield]: https://img.shields.io/github/license/farosch/hacs_hp_aruba_switch.svg?style=for-the-badge
[license-url]: https://github.com/farosch/hacs_hp_aruba_switch/blob/main/LICENSE
