# Release Notes

## Version 1.0.8 - Major Architecture Overhaul ⚠️ BREAKING CHANGES
**October 4, 2025**

> **⚠️ WARNING: BREAKING CHANGES**  
> **This version requires a complete reinstall:**
> This release completely restructures entity handling for massive performance improvements.  
> **ALL ENTITIES WILL BE RECREATED WITH NEW IDS.**  
> Backup your automation, dashboards and configuration then remove the integration and reinstall it.

#### Improvements
- Consolidated port sensors into multi-attribute sensor
- Combined port + PoE switches into single select entity per port
- Enhanced parsers to extract comprehensive port statistics (error counters, utilization, packet rates)
- Added PoE power monitoring (voltage, amperage, actual power draw, PoE class/type, LLDP data)
- Added port details (port type, intrusion alerts, flow control, MAC addresses)
- Improved config flow with dynamic checkbox generation based on port count
- Updated translations (German, Spanish, French, Italian)
- Faster startup time
- Restore entity state after restart
- Better entity naming with has_entity_name pattern
- Python 3.13 testing alignment
