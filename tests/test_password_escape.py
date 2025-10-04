"""Test different password escaping scenarios for SSH authentication."""
import sys
from pathlib import Path
import importlib.util

# Load ssh_manager directly
ssh_manager_path = Path(__file__).parent.parent / "custom_components" / "hp_aruba_switch" / "ssh_manager.py"
spec = importlib.util.spec_from_file_location("ssh_manager", ssh_manager_path)
ssh_manager_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssh_manager_module)
ArubaSSHManager = ssh_manager_module.ArubaSSHManager

import asyncio


async def test_password_variant(password_variant, description):
    """Test a specific password variant."""
    print(f"\n{'='*60}")
    print(f"Testing: {description}")
    print(f"{'='*60}")
    print(f"Password: '{password_variant}'")
    print(f"Length: {len(password_variant)} characters")
    print(f"Bytes: {password_variant.encode('utf-8').hex()}")
    print(f"Repr: {repr(password_variant)}")
    
    manager = ArubaSSHManager("10.4.20.65", "manager", password_variant, 22)
    
    try:
        # Quick connectivity test with short timeout
        output = await manager.execute_command("show version", timeout=8)
        if output and len(output.strip()) > 10:
            print("✅ SUCCESS - Authentication worked!")
            print(f"Response preview: {output[:100]}...")
            return True
        else:
            print("❌ FAILED - No valid response")
            return False
    except Exception as e:
        print(f"❌ FAILED - {type(e).__name__}: {str(e)[:100]}")
        return False


async def main():
    """Test different password variations."""
    print("\n" + "="*60)
    print("PASSWORD ESCAPING TEST FOR SSH AUTHENTICATION")
    print("="*60)
    print("\nOriginal password from PuTTY: SY\\=ojE3%'_s")
    print("(PuTTY shows the backslash in the UI)")
    print("\nTesting different interpretations...")
    
    test_cases = [
        # What the user typed in PuTTY (backslash is literal in PuTTY password field)
        (r"SY\=ojE3%'_s", "PuTTY literal (backslash + equals)"),
        
        # What if the actual password doesn't have backslash (backslash was just for display)
        ("SY=ojE3%'_s", "No backslash (just equals)"),
        
        # Python raw string with backslash
        (r"SY\=ojE3%'_s", "Python raw string r\"SY\\=ojE3%'_s\""),
        
        # Regular string with escaped backslash
        ("SY\\=ojE3%'_s", "Python escaped string \"SY\\\\=ojE3%'_s\""),
        
        # URL encoded versions (in case it's stored that way)
        ("SY%3DojE3%25'_s", "URL encoded equals and percent"),
    ]
    
    results = []
    for password, description in test_cases:
        result = await test_password_variant(password, description)
        results.append((description, result))
        await asyncio.sleep(1)  # Brief pause between attempts
    
    print("\n" + "="*60)
    print("SUMMARY OF RESULTS")
    print("="*60)
    
    for description, success in results:
        status = "✅ WORKED" if success else "❌ FAILED"
        print(f"{status}: {description}")
    
    successful = [desc for desc, result in results if result]
    if successful:
        print(f"\n✅ Successful password format: {successful[0]}")
    else:
        print("\n❌ None of the password formats worked")
        print("\nPossible issues:")
        print("1. The password might be different than what PuTTY shows")
        print("2. SSH server might require specific authentication methods")
        print("3. Network or firewall issues")
        print("4. Try connecting with verbose SSH logging to see actual errors")


if __name__ == "__main__":
    asyncio.run(main())
