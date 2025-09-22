# Release Notes

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