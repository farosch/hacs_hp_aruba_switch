# Release Notes

## Version 1.0.7 - Comprehensive Monitoring & Enhanced Features
**September 25, 2025**

### ✨ **New Monitoring Features**

#### **Port Activity Sensors**
- Real-time port activity monitoring (active/idle status)
- Traffic rate calculations with threshold-based activity detection
- Detailed traffic statistics in sensor attributes

#### **Traffic Statistics Sensors** 
- Individual bytes in/out sensors per port
- Individual packets in/out sensors per port
- Total increasing counters for long-term monitoring

#### **Link Status Sensors**
- Port link status with speed and duplex information
- Auto-negotiation status and cable type detection
- Enhanced speed detection supporting HP/Aruba formats

#### **Binary Link Sensors**
- Simple on/off connectivity status per port
- Rich attributes with detailed link information
- Perfect for automations and notifications

### ⚙️ **Configuration Enhancements**

#### **Options Flow Support**
- Added ability to modify configuration after initial setup
- Access via Settings → Devices & Services → HP/Aruba Switch → Configure
- No need to delete and re-add integration for configuration changes

#### **Reconfigurable Settings**
- Username and password (with connection validation)
- SSH port and port count settings
- Port exclusions and PoE port exclusions
- Refresh interval (10-300 seconds with validation)

#### **Enhanced User Experience**
- Real-time credential validation when changing username/password
- Automatic entity reload when configuration changes
- Multi-language support for options flow
- Improved error handling and user feedback

### � **Technical Improvements**

#### **Optimized SSH Operations** 
- Single SSH session for all commands instead of multiple connections
- Combined command execution with intelligent output parsing
- Reduced connection overhead and improved reliability

#### **Enhanced HP/Aruba Compatibility**
- Better parsing of comma-separated statistics
- Improved interface brief format support  
- Enhanced PoE status detection and parsing
- Support for various HP/Aruba output formats

#### **Rich Entity Attributes**
- Switch entities expose comprehensive port data
- Traffic statistics, link details, and timestamps
- PoE entities include detailed power information
- Perfect for advanced automations and dashboards

### 🌍 **User Experience**

#### **Staggered Entity Updates**
- Prevents overwhelming switches with simultaneous queries
- Intelligent timing offsets for different entity types
- Maintains data freshness while being switch-friendly

#### **Expanded Language Support**
- Updated translations for new configuration options
- Consistent entity naming across all supported languages

### 🐛 **Bug Fixes**

- Fixed sensors showing 0 values for traffic statistics
- Improved speed sensor parsing for HP/Aruba "1000FDx" format
- Better error handling for SSH timeouts and connection issues
- Enhanced debug logging for easier troubleshooting

---
**Note**: Restart Home Assistant to activate new features. Reconfigure integration to access refresh interval setting.

## Version 1.0.2 - HACS Compatibility
**September 23, 2025**

### 🎉 Reworked Repository for HACS comptibility

This version has been reworked to prepare for distributing this integration through HACS.

---
**Full documentation**: [README](https://github.com/farosch/hacs_hp_aruba_switch#readme)

## Version 1.0.1 - Initial Release
**September 23, 2025**

### 🎉 First stable release of HP/Aruba Switch Integration for Home Assistant

### ✨ Features
- **Port Control**: Enable/disable individual switch ports via Home Assistant
- **PoE Management**: Independent PoE control for each port
- **Configurable Port Count**: Support for 1-48 ports (default: 24)
- **Real-time Status**: Live monitoring of port and PoE status
- **Bulk Operations**: Optimized SSH queries for better performance
- **Multi-language Support**: English, German, French, Italian, Spanish

### 🔧 Technical
- **Supported Devices**: HP 2530/2540/2920/2930F Series, Aruba 2540/2930F/2930M Series
- **Requirements**: SSH access, administrator credentials
- **Performance**: 35-second update intervals with connection pooling
- **Integration Type**: Hub with local polling

### 📦 Installation
- **HACS**: Search for "HP/Aruba Switch" in integrations
- **Manual**: Copy `hp_aruba_switch` folder to `custom_components/`

### 🐛 Known Issues
- Switch must have SSH enabled before setup
- Large switches may need longer update intervals

---
**Full documentation**: [README](https://github.com/farosch/hacs_hp_aruba_switch#readme)