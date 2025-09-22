# HP/Aruba Switch Integration for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

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

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the "+" button
4. Search for "HP/Aruba Switch"
5. Install the integration
6. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `aruba_switch` folder to your `custom_components` directory
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
   - **Exclude Ports**: Comma-separated list of ports to exclude (optional)

### Configuration Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| Host | Yes | - | IP address or hostname of the switch |
| Username | Yes | - | Administrator username |
| Password | Yes | - | Administrator password |
| SSH Port | No | 22 | SSH port number |
| Exclude Ports | No | - | Ports to exclude (e.g., "1,24") |

## Entities Created

After successful configuration, the integration creates the following entities:

### Switch Entities
For each port (e.g., port 1):
- `switch.aruba_switch_xxx_xxx_xxx_xxx_port_1` - Port control
- `switch.aruba_switch_xxx_xxx_xxx_xxx_poe_1` - PoE control

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
        entity_id: switch.aruba_switch_192_168_1_100_poe_1
```

**Monitor port status:**
```yaml
automation:
  - alias: "Alert on port down"
    trigger:
      platform: state
      entity_id: switch.aruba_switch_192_168_1_100_port_24
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
          entity_id: switch.aruba_switch_192_168_1_100_poe_1
      - delay: "00:00:10"
      - service: switch.turn_on
        target:
          entity_id: switch.aruba_switch_192_168_1_100_poe_1
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
- Use "Exclude Ports" to reduce entity count
- Check network latency to switch
- Monitor Home Assistant resource usage

### Debug Logging

Add to your `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.aruba_switch: debug
    paramiko: debug
```

### Entity Naming

Entities are named using the format:
- `switch.aruba_switch_{ip_with_underscores}_{port}_{type}`
- Example: `switch.aruba_switch_192_168_1_100_port_1`

## Switch Commands Used

The integration uses these switch commands:

### Port Control
```bash
configure
interface X
no shutdown  # or shutdown
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
show interface X
show power-over-ethernet all
```

## 🎯 **Performance & Reliability**
```

### Fan Control
```bash
configure
fan auto  # or fan speed low/medium/high
write mem
exit
```

## Performance Considerations

- **Update Intervals**: Switch entities update every 35 seconds with intelligent staggering
- **Connection Limits**: Maximum 3 concurrent SSH connections
- **Staggered Updates**: Entities update with random offsets to prevent overload
- **Timeout Settings**: Optimized for network switches (8-second command timeout)

## Languages Supported

The integration is available in multiple languages:
- English (default)
- German (Deutsch)
- French (Français)
- Italian (Italiano)
- Spanish (Español)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/hp-aruba-switch/issues)
- **Discussions**: [Home Assistant Community](https://community.home-assistant.io/)

---

**Note**: This integration requires SSH access to your switch. Ensure you understand the security implications and follow your organization's security policies.

[commits-shield]: https://img.shields.io/github/commit-activity/y/yourusername/hp-aruba-switch.svg?style=for-the-badge
[commits]: https://github.com/yourusername/hp-aruba-switch/commits/main
[license-shield]: https://img.shields.io/github/license/yourusername/hp-aruba-switch.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/yourusername/hp-aruba-switch.svg?style=for-the-badge
[releases]: https://github.com/yourusername/hp-aruba-switch/releases