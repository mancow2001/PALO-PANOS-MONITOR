#!/usr/bin/env python3
"""
Diagnostic script to troubleshoot CPU monitoring issues
"""
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(name)s %(levelname)s %(message)s'
)
LOG = logging.getLogger("cpu_diagnostic")

def test_cpu_collection(firewall_name, config_path="config.yaml"):
    """Test CPU collection methods for a specific firewall"""
    try:
        from config import ConfigManager
        from panos_api import PanOSAPI
        
        print("=" * 80)
        print(f"CPU COLLECTION TEST: {firewall_name}")
        print("=" * 80)
        
        # Load config
        config_manager = ConfigManager(config_path)
        fw_config = config_manager.get_firewall(firewall_name)
        
        if not fw_config:
            print(f"ERROR: Firewall '{firewall_name}' not found in config")
            return False
        
        print(f"\nFirewall: {fw_config.name}")
        print(f"Host: {fw_config.host}")
        print(f"Enabled: {fw_config.enabled}")
        
        # Initialize API
        print("\nInitializing API connection...")
        api = PanOSAPI(
            fw_config.host,
            fw_config.api_key,
            verify_ssl=fw_config.verify_ssl
        )
        
        print("\n--- Testing CPU Collection Methods ---\n")
        
        # Method 1: show system resources
        print("1. Testing: show system resources")
        try:
            result = api.execute_op_command("show system resources")
            
            if result and 'result' in result:
                content = result['result']
                print(f"   Response type: {type(content)}")
                print(f"   Response length: {len(str(content))}")
                
                # Try to parse CPU
                if isinstance(content, dict):
                    if 'platform' in content:
                        print(f"   ✓ Found 'platform' section")
                        platform = content['platform']
                        print(f"     Platform type: {type(platform)}")
                        if 'cpu' in platform:
                            print(f"   ✓ Found 'cpu' data: {platform['cpu']}")
                        else:
                            print(f"   ✗ No 'cpu' in platform")
                            print(f"     Available keys: {list(platform.keys())}")
                    else:
                        print(f"   ✗ No 'platform' section")
                        print(f"     Available keys: {list(content.keys())}")
                
                elif isinstance(content, str):
                    print(f"   Response is string, first 500 chars:")
                    print(f"   {content[:500]}")
                    
                    # Try to parse as text
                    if 'CPU' in content or 'cpu' in content:
                        print(f"   ✓ Contains CPU info")
                    else:
                        print(f"   ✗ No CPU info found in text")
                
                else:
                    print(f"   Unexpected response type")
            else:
                print(f"   ✗ No result returned")
                print(f"   Full response: {result}")
        except Exception as e:
            print(f"   ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
        
        # Method 2: show running resource-monitor
        print("\n2. Testing: show running resource-monitor")
        try:
            result = api.execute_op_command("show running resource-monitor")
            
            if result and 'result' in result:
                content = result['result']
                print(f"   Response type: {type(content)}")
                
                if isinstance(content, dict):
                    print(f"   Response keys: {list(content.keys())}")
                    if 'data-processors' in content:
                        print(f"   ✓ Found 'data-processors' section")
                        dp = content['data-processors']
                        if 'dp' in dp:
                            print(f"   ✓ Found DP CPU data")
                            dp_list = dp['dp'] if isinstance(dp['dp'], list) else [dp['dp']]
                            print(f"     Number of DP cores: {len(dp_list)}")
                            for i, core in enumerate(dp_list[:3]):  # Show first 3
                                if 'cpu-load-average' in core:
                                    print(f"     Core {i}: {core['cpu-load-average']}%")
                        else:
                            print(f"   ✗ No 'dp' in data-processors")
                    
                    if 'resource-monitor' in content:
                        print(f"   ✓ Found 'resource-monitor' section")
                        rm = content['resource-monitor']
                        print(f"     Keys: {list(rm.keys())}")
                
                elif isinstance(content, str):
                    print(f"   Response is string, first 500 chars:")
                    print(f"   {content[:500]}")
            else:
                print(f"   ✗ No result returned")
        except Exception as e:
            print(f"   ✗ FAILED: {e}")
        
        # Method 3: show system state filter sys.s*.cpu*
        print("\n3. Testing: show system state filter sys.s*.cpu*")
        try:
            result = api.execute_op_command("show system state filter sys.s*.cpu*")
            
            if result and 'result' in result:
                content = result['result']
                print(f"   Response type: {type(content)}")
                
                if isinstance(content, str):
                    lines = content.split('\n')
                    print(f"   Lines returned: {len(lines)}")
                    print(f"   First 10 lines:")
                    for line in lines[:10]:
                        if line.strip():
                            print(f"     {line}")
                    
                    # Look for CPU values
                    cpu_lines = [l for l in lines if 'cpu' in l.lower()]
                    if cpu_lines:
                        print(f"   ✓ Found {len(cpu_lines)} CPU-related lines")
                elif isinstance(content, dict):
                    print(f"   Response keys: {list(content.keys())}")
            else:
                print(f"   ✗ No result returned")
        except Exception as e:
            print(f"   ✗ FAILED: {e}")
        
        # Method 4: Direct XML API
        print("\n4. Testing: Direct XML API - show system resources")
        try:
            import requests
            
            url = f"https://{fw_config.host}/api/"
            params = {
                'type': 'op',
                'cmd': '<show><system><resources></resources></system></show>',
                'key': fw_config.api_key
            }
            
            response = requests.get(
                url,
                params=params,
                verify=fw_config.verify_ssl,
                timeout=30
            )
            
            print(f"   Status: {response.status_code}")
            print(f"   Content type: {response.headers.get('content-type')}")
            print(f"   Content length: {len(response.text)}")
            
            # Parse XML
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.text)
            
            print(f"   XML root tag: {root.tag}")
            print(f"   XML attributes: {root.attrib}")
            
            # Look for CPU data
            cpu_elements = root.findall('.//cpu')
            if cpu_elements:
                print(f"   ✓ Found {len(cpu_elements)} CPU elements")
                for elem in cpu_elements[:3]:
                    print(f"     {elem.tag}: {elem.text}")
            else:
                print(f"   ✗ No CPU elements found")
                
                # Show structure
                print(f"   XML structure (first level):")
                for child in root:
                    print(f"     - {child.tag}: {len(list(child))} children")
        
        except Exception as e:
            print(f"   ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
        
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_api_permissions(firewall_name, config_path="config.yaml"):
    """Check API key permissions"""
    print("\n" + "=" * 80)
    print("API PERMISSIONS CHECK")
    print("=" * 80)
    
    try:
        from config import ConfigManager
        from panos_api import PanOSAPI
        
        config_manager = ConfigManager(config_path)
        fw_config = config_manager.get_firewall(firewall_name)
        
        api = PanOSAPI(
            fw_config.host,
            fw_config.api_key,
            verify_ssl=fw_config.verify_ssl
        )
        
        # Test basic connectivity
        print("\n1. Testing basic API connectivity...")
        try:
            result = api.execute_op_command("show system info")
            if result:
                print("   ✓ API is accessible")
                if 'result' in result and 'system' in result['result']:
                    system = result['result']['system']
                    print(f"   Hostname: {system.get('hostname', 'unknown')}")
                    print(f"   Model: {system.get('model', 'unknown')}")
                    print(f"   Version: {system.get('sw-version', 'unknown')}")
            else:
                print("   ✗ No response from API")
        except Exception as e:
            print(f"   ✗ FAILED: {e}")
        
        # Test operational commands
        print("\n2. Testing operational command access...")
        test_commands = [
            "show system resources",
            "show running resource-monitor",
            "show system state"
        ]
        
        for cmd in test_commands:
            try:
                result = api.execute_op_command(cmd)
                if result and 'result' in result:
                    print(f"   ✓ {cmd}: OK")
                else:
                    print(f"   ✗ {cmd}: No result")
            except Exception as e:
                print(f"   ✗ {cmd}: FAILED - {e}")
        
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def suggest_cpu_fixes():
    """Suggest fixes for CPU monitoring"""
    print("\n" + "=" * 80)
    print("CPU MONITORING FIXES")
    print("=" * 80)
    
    print("""
Common CPU Monitoring Issues:

1. API KEY PERMISSIONS
   The API key needs 'XML API' access.
   
   To fix in PAN-OS:
   - Device > Admin Roles > Create/Edit role
   - Enable: XML API
   - Optional: Dashboard (for resource-monitor command)
   - Device > Administrators > Edit admin > assign role

2. INCOMPATIBLE PAN-OS VERSION
   Older PAN-OS versions may not support all commands.
   
   Supported commands by version:
   - show system resources: PAN-OS 7.0+
   - show running resource-monitor: PAN-OS 8.0+
   - show system state: PAN-OS 7.0+

3. RESPONSE FORMAT CHANGED
   PAN-OS API responses can vary by version.
   
   Fix: Update collectors.py to handle your version's format

4. SSL CERTIFICATE ISSUES
   If using self-signed certs.
   
   Fix in config.yaml:
   ```
   verify_ssl: false
   ```

DEBUGGING STEPS:
1. Run: python3 diagnose_cpu.py FIREWALL_NAME
2. Check which methods work
3. Update collectors.py to use working method
4. Check API key permissions in PAN-OS
5. Verify PAN-OS version compatibility

collectors.PY FIX:
If you need to add a fallback method, I can provide updated code
for the _collect_cpu_metrics method that handles your specific
PAN-OS version and response format.
""")

def main():
    """Main diagnostic routine"""
    if len(sys.argv) < 2:
        print("Usage: python3 diagnose_cpu.py FIREWALL_NAME [config_path]")
        print("\nExample: python3 diagnose_cpu.py DATA-CENTER config.yaml")
        return 1
    
    firewall_name = sys.argv[1]
    config_path = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"
    
    if not Path(config_path).exists():
        print(f"ERROR: Config file not found: {config_path}")
        return 1
    
    print("PAN-OS CPU Monitoring Diagnostic Tool")
    print("=" * 80)
    print(f"Firewall: {firewall_name}")
    print(f"Config: {config_path}")
    
    # Run tests
    success = test_cpu_collection(firewall_name, config_path)
    check_api_permissions(firewall_name, config_path)
    suggest_cpu_fixes()
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
