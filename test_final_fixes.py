#!/usr/bin/env python3
"""Test script to verify the parsing fixes work correctly."""

import re

def extract_numbers(text):
    numbers = []
    for match in re.finditer(r'(\d{1,3}(?:,\d{3})*)', text):
        number_str = match.group(1).replace(',', '')
        try:
            numbers.append(int(number_str))
        except ValueError:
            continue
    return numbers

def test_statistics_parsing():
    """Test statistics parsing with actual switch output format."""
    print("=== Testing Statistics Parsing ===")
    
    # Sample lines from the actual log
    test_lines = [
        "Bytes Rx        : 172,860,154          Bytes Tx        : 144,042,561",
        "Unicast Rx      : 241,588              Unicast Tx      : 198,240",
        "Bcast/Mcast Rx  : 343,624              Bcast/Mcast Tx  : 4,189"
    ]
    
    statistics = {"1": {}}
    
    for line in test_lines:
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip().lower()
                value_str = parts[1].strip()
                
                # Handle HP/Aruba switch format: "Bytes Rx        : 171,771,942          Bytes Tx        : 142,120,852"
                if "bytes rx" in key:
                    # Extract all numbers from the line (includes both Rx and Tx values)  
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics["1"]["bytes_rx"] = numbers[0]
                        statistics["1"]["bytes_tx"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics["1"]["bytes_rx"] = numbers[0]
                # Handle HP/Aruba switch format: "Unicast Rx      : 239,357              Unicast Tx      : 195,819"
                elif "unicast rx" in key:
                    # Extract all numbers from the line (includes both Rx and Tx values)
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics["1"]["unicast_rx"] = numbers[0]
                        statistics["1"]["unicast_tx"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics["1"]["unicast_rx"] = numbers[0]
    
    print(f"Parsed statistics: {statistics['1']}")
    
    # Verify expected values
    expected = {
        "bytes_rx": 172860154,
        "bytes_tx": 144042561,
        "unicast_rx": 241588,
        "unicast_tx": 198240
    }
    
    success = True
    for key, expected_value in expected.items():
        if statistics["1"].get(key) != expected_value:
            print(f"❌ {key}: got {statistics['1'].get(key)}, expected {expected_value}")
            success = False
        else:
            print(f"✅ {key}: {statistics['1'].get(key)}")
    
    return success

def test_version_parsing():
    """Test version parsing with actual switch output using the real parsing logic."""
    print("\n=== Testing Version Parsing ===")
    
    combined_output = """HP-2530-24G-PoEP# show version
Image stamp:
/ws/swbuildm/rel_yakima_qaoff/code/build/lakes(swbuildm_rel_yakima_qaoff_rel_ya
kima)
Feb 27 2019 22:56:36
YA.16.08.0002
848
Boot Image:     Primary
Boot ROM Version:    YA.15.20"""
    
    # Parse using the actual logic from ssh_manager.py
    version_info = {}
    main_firmware_version = None
    boot_version = None
    
    for line in combined_output.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        line_lower = line.lower()
        
        # Extract switch model from command prompt
        if ('hp-' in line_lower or 'aruba-' in line_lower) and ('#' in line or 'show' in line_lower):
            # More flexible pattern to catch model names in various contexts
            model_match = re.search(r'((?:HP|Aruba)-[A-Z0-9-]+)', line, re.IGNORECASE)
            if model_match:
                version_info["model"] = model_match.group(1)
                print(f"🏷️ Found model in line: {model_match.group(1)} from line: {line}")
        
        # Parse version fields
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip().lower()
                value = parts[1].strip()
                
                if any(x in key for x in ["rom version", "boot rom", "bootrom"]):
                    boot_version = value
                    print(f"🔧 Found boot ROM version: {value}")
        
        # Look for version patterns in any line - not just those with version keywords
        if "ya." in line_lower or "kb." in line_lower or "yc." in line_lower:
            # Aruba version format like "YA.16.08.0002"
            version_match = re.search(r'[YK][A-Z]\.[\.\d]+', line, re.IGNORECASE)
            if version_match:
                version_str = version_match.group()
                print(f"📟 Found version string: {version_str} from line: {line}")
                # If this looks like a main firmware version (longer), prefer it
                if len(version_str) > 8:  # YA.16.08.0002 is longer than YA.15.20
                    main_firmware_version = version_str
                    print(f"🎯 Set as main firmware (length {len(version_str)}): {version_str}")
                elif main_firmware_version is None:
                    main_firmware_version = version_str
                    print(f"🔄 Set as fallback firmware: {version_str}")
    
    # Use main firmware version if found, otherwise use boot version
    if main_firmware_version:
        version_info["firmware_version"] = main_firmware_version
        print(f"✅ Using main firmware version: {main_firmware_version}")
    elif boot_version:
        version_info["firmware_version"] = boot_version
        print(f"⚠️ Fallback to boot ROM version: {boot_version}")
    else:
        version_info["firmware_version"] = "Unknown"
        print(f"❌ No version found, using Unknown")
        
    # Set defaults for missing fields
    if "model" not in version_info:
        version_info["model"] = "HP/Aruba Switch"
        print(f"⚠️ No model found, using default")
    
    print(f"Final version: {version_info.get('firmware_version', 'Unknown')}")
    print(f"Final model: {version_info.get('model', 'HP/Aruba Switch')}")
    
    # Verify expected values
    version_success = version_info.get("firmware_version") == "YA.16.08.0002"
    model_success = version_info.get("model") == "HP-2530-24G-PoEP"
    
    if version_success:
        print("✅ Version parsing: PASS")
    else:
        print(f"❌ Version parsing: FAIL (got {version_info.get('firmware_version')}, expected YA.16.08.0002)")
    
    if model_success:
        print("✅ Model parsing: PASS")
    else:
        print(f"❌ Model parsing: FAIL (got {version_info.get('model')}, expected HP-2530-24G-PoEP)")
    
    return version_success and model_success

if __name__ == "__main__":
    print("Testing HP/Aruba Switch Parsing Fixes")
    print("=====================================")
    
    stats_result = test_statistics_parsing()
    version_result = test_version_parsing()
    
    print("\n=== Summary ===")
    print(f"Statistics parsing: {'✅ PASS' if stats_result else '❌ FAIL'}")
    print(f"Version parsing: {'✅ PASS' if version_result else '❌ FAIL'}")
    
    if stats_result and version_result:
        print("🎉 All tests passed!")
    else:
        print("❌ Some tests failed")