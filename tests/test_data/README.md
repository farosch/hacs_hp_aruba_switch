# Test Data Files

This directory contains sample output from SSH commands executed on HP/Aruba switches.

## Required Files

Please create these files with actual output from your switch:

### 1. `show_interface_all.txt`
Output from: `show interface all`

Contains:
- Port counters (bytes, packets)
- Unicast/broadcast/multicast statistics
- Error counters
- Link status

### 2. `show_interface_brief.txt`
Output from: `show interface brief`

Contains:
- Port number
- Type
- Link status
- Speed/Duplex mode
- MDI mode

### 3. `show_power_over_ethernet_all.txt`
Output from: `show power-over-ethernet all`

Contains:
- Port number
- PoE status
- Power consumption
- Power class
- Priority

### 4. `show_version.txt`
Output from: `show version`

Contains:
- Switch model
- Firmware version (Software revision)
- ROM version
- Serial number
- Uptime

## How to Generate

1. SSH into your HP/Aruba switch:
   ```bash
   ssh admin@192.168.1.100
   ```

2. Disable paging:
   ```
   no page
   ```

3. Run each command and save output:
   ```
   show interface all > show_interface_all.txt
   show interface brief > show_interface_brief.txt
   show power-over-ethernet all > show_power_over_ethernet_all.txt
   show version > show_version.txt
   ```

4. Copy the files to this directory

## Usage in Tests

These files are loaded by the test fixtures in `conftest.py` and used to test parsing logic without requiring a real switch connection.
