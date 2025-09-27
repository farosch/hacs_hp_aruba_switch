#!/usr/bin/env python3

"""Test script to verify the parsing fixes work correctly."""

import re

def extract_numbers(text):
    """Extract numbers from text (simulating the existing function)."""
    import re
    numbers = []
    for match in re.finditer(r'(\d{1,3}(?:,\d{3})*)', text):
        number_str = match.group(1).replace(',', '')
        try:
            numbers.append(int(number_str))
        except ValueError:
            continue
    return numbers

def test_statistics_parsing():
    """Test that statistics parsing works with HP/Aruba format."""
    print("=== Testing Statistics Parsing ===")
    
    # Sample data from the log
    test_lines = [
        "Bytes Rx        : 171,771,942          Bytes Tx        : 142,120,852",
        "Unicast Rx      : 239,357              Unicast Tx      : 195,819",
        "Bcast/Mcast Rx  : 334,435              Bcast/Mcast Tx  : 4,134"
    ]
    
    statistics = {"1": {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}}
    current_interface = "1"
    
    for line in test_lines:
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip().lower()
                value_str = parts[1].strip()
                
                print(f"Processing: key='{key}', value='{value_str}'")
                
                if "bytes rx" in key:
                    numbers = extract_numbers(value_str)
                    print(f"  Bytes numbers extracted: {numbers}")
                    if len(numbers) >= 2:
                        statistics[current_interface]["bytes_in"] = numbers[0]
                        statistics[current_interface]["bytes_out"] = numbers[1]
                        print(f"  Set bytes_in={numbers[0]}, bytes_out={numbers[1]}")
                    elif len(numbers) == 1:
                        statistics[current_interface]["bytes_in"] = numbers[0]
                        print(f"  Set bytes_in={numbers[0]}")
                        
                elif "unicast rx" in key:
                    numbers = extract_numbers(value_str)
                    print(f"  Packets numbers extracted: {numbers}")
                    if len(numbers) >= 2:
                        statistics[current_interface]["packets_in"] = numbers[0]
                        statistics[current_interface]["packets_out"] = numbers[1]
                        print(f"  Set packets_in={numbers[0]}, packets_out={numbers[1]}")
                    elif len(numbers) == 1:
                        statistics[current_interface]["packets_in"] = numbers[0]
                        print(f"  Set packets_in={numbers[0]}")
    
    print(f"\nFinal statistics: {statistics[current_interface]}")
    return statistics[current_interface]

def test_model_parsing():
    """Test that model parsing works with HP/Aruba format."""
    print("\n=== Testing Model Parsing ===")
    
    # Sample data from the log
    test_lines = [
        "HP-2530-24G-PoEP# show interface brief",
        "HP-2530-24G-PoEP# show power-over-ethernet all", 
        "HP-2530-24G-PoEP# show version",
        "Some other line with HP-2530-24G-PoEP# embedded",
        "Regular line without model"
    ]
    
    version_info = {}
    
    for line in test_lines:
        line_lower = line.lower()
        print(f"Processing line: '{line}'")
        
        # Enhanced model detection logic
        if ('hp-' in line_lower or 'aruba-' in line_lower) and ('#' in line or 'show' in line_lower):
            model_match = re.search(r'((?:HP|Aruba)-[A-Z0-9-]+)', line, re.IGNORECASE)
            if model_match:
                version_info["model"] = model_match.group(1)
                print(f"  ✅ Found model: {model_match.group(1)}")
            else:
                print(f"  ❌ No model match found")
        elif line.endswith('#') and '-' in line and 'hp' in line_lower:
            # Fallback logic
            model_match = re.search(r'(HP-[A-Z0-9-]+)', line, re.IGNORECASE)
            if model_match:
                version_info["model"] = model_match.group(1)
                print(f"  ✅ Found model (fallback): {model_match.group(1)}")
        else:
            print(f"  ➖ No model pattern detected")
    
    final_model = version_info.get("model", "HP/Aruba Switch")
    print(f"\nFinal model: {final_model}")
    return final_model

if __name__ == "__main__":
    print("Testing HP/Aruba Switch Parsing Fixes\n")
    
    # Test statistics parsing
    stats = test_statistics_parsing()
    
    # Test model parsing  
    model = test_model_parsing()
    
    print("\n=== Summary ===")
    print(f"Statistics parsing: {'✅ PASS' if stats['bytes_in'] > 0 and stats['packets_in'] > 0 else '❌ FAIL'}")
    print(f"Model parsing: {'✅ PASS' if 'HP-2530-24G-PoEP' in model else '❌ FAIL'}")
    print(f"Expected bytes_in: 171771942, Got: {stats['bytes_in']}")
    print(f"Expected packets_in: 239357, Got: {stats['packets_in']}")
    print(f"Expected model: HP-2530-24G-PoEP, Got: {model}")