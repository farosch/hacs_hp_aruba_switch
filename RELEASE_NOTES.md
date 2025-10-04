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
- Faster startup time
- Restore entity state after restart
- Better entity naming with has_entity_name pattern
