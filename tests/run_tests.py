"""Simple test runner for SSH manager parsing without Home Assistant dependencies."""
import sys
import os
from pathlib import Path
import importlib.util

# Load ssh_manager directly without importing the package
ssh_manager_path = Path(__file__).parent.parent / "custom_components" / "hp_aruba_switch" / "ssh_manager.py"
spec = importlib.util.spec_from_file_location("ssh_manager", ssh_manager_path)
ssh_manager_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssh_manager_module)
ArubaSSHManager = ssh_manager_module.ArubaSSHManager


def load_test_data(filename):
    """Load test data from file."""
    test_data_dir = Path(__file__).parent / "test_data"
    filepath = test_data_dir / filename
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return None


def test_parse_show_interface_all():
    """Test parsing show interface all output."""
    print("\n" + "="*60)
    print("TEST: Parse Show Interface All")
    print("="*60)
    
    manager = ArubaSSHManager("test", "test", "test")
    output = load_test_data("show_interface_all.txt")
    
    if not output:
        print("❌ Test data file not found")
        return False
    
    try:
        interfaces, statistics, link_details = manager.parse_show_interface_all(output)
        
        print(f"✅ Parsed {len(interfaces)} interfaces")
        print(f"✅ Parsed {len(statistics)} statistics entries")
        print(f"✅ Parsed {len(link_details)} link detail entries")
        
        # Check port 1 details
        if "1" in interfaces:
            print(f"\n📊 Port 1 Details:")
            print(f"   Link Status: {interfaces['1'].get('link_status')}")
            print(f"   Port Enabled: {interfaces['1'].get('port_enabled')}")
            print(f"   Bytes RX: {statistics['1'].get('bytes_rx', 0):,}")
            print(f"   Bytes TX: {statistics['1'].get('bytes_tx', 0):,}")
            print(f"   Link Up: {link_details['1'].get('link_up')}")
        
        # Check port 20 (should be up)
        if "20" in interfaces:
            print(f"\n📊 Port 20 Details:")
            print(f"   Link Status: {interfaces['20'].get('link_status')}")
            print(f"   Port Enabled: {interfaces['20'].get('port_enabled')}")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_parse_show_interface_brief():
    """Test parsing show interface brief output."""
    print("\n" + "="*60)
    print("TEST: Parse Show Interface Brief")
    print("="*60)
    
    manager = ArubaSSHManager("test", "test", "test")
    output = load_test_data("show_interface_brief.txt")
    
    if not output:
        print("❌ Test data file not found")
        return False
    
    try:
        brief_info = manager.parse_show_interface_brief(output)
        
        print(f"✅ Parsed {len(brief_info)} ports")
        
        # Show first few ports
        for i, (port, info) in enumerate(list(brief_info.items())[:5]):
            print(f"   Port {port}: {info['link_speed_mbps']} Mbps, {info['duplex']} duplex, mode={info.get('mode')}")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_parse_show_power_over_ethernet():
    """Test parsing show power-over-ethernet all output."""
    print("\n" + "="*60)
    print("TEST: Parse Show Power-over-Ethernet All")
    print("="*60)
    
    manager = ArubaSSHManager("test", "test", "test")
    output = load_test_data("show_power_over_ethernet_all.txt")
    
    if not output:
        print("❌ Test data file not found")
        return False
    
    try:
        poe_ports = manager.parse_show_power_over_ethernet_all(output)
        
        print(f"✅ Parsed {len(poe_ports)} PoE ports")
        
        # Show first few ports
        for i, (port, info) in enumerate(list(poe_ports.items())[:5]):
            print(f"   Port {port}: Power Enable={info['power_enable']}, Status={info['poe_status']}")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_parse_show_version():
    """Test parsing show version output."""
    print("\n" + "="*60)
    print("TEST: Parse Show Version")
    print("="*60)
    
    manager = ArubaSSHManager("test", "test", "test")
    output = load_test_data("show_version.txt")
    
    if not output:
        print("❌ Test data file not found")
        return False
    
    try:
        version_info = manager.parse_show_version(output)
        
        print(f"✅ Parsed version info:")
        print(f"   Model: {version_info.get('model', 'Unknown')}")
        print(f"   Firmware: {version_info.get('firmware_version', 'Unknown')}")
        print(f"   Serial: {version_info.get('serial_number', 'Unknown')}")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import asyncio
    
    print("\n=== HP/Aruba Switch SSH Manager Tests ===\n")
    print("="*60)
    
    # Run local file tests
    results = []
    results.append(("Parse Interface All", test_parse_show_interface_all()))
    results.append(("Parse Interface Brief", test_parse_show_interface_brief()))
    results.append(("Parse PoE", test_parse_show_power_over_ethernet()))
    results.append(("Parse Version", test_parse_show_version()))
    
    # Run real switch test
    print("\n" + "="*60)
    print("REAL SWITCH TESTS")
    print("="*60)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} tests passed")
    print("="*60)
    
    sys.exit(0 if passed == total else 1)
