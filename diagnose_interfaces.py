#!/usr/bin/env python3
"""
Diagnostic script to troubleshoot interface monitoring issues
"""
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(name)s %(levelname)s %(message)s'
)
LOG = logging.getLogger("interface_diagnostic")

def check_database_interfaces(db_path="metrics.db"):
    """Check what interfaces are in the database"""
    try:
        from database import EnhancedMetricsDatabase
        
        db = EnhancedMetricsDatabase(db_path)
        
        print("=" * 80)
        print("DATABASE INTERFACE CHECK")
        print("=" * 80)
        
        # Get all firewalls
        firewalls = db.get_all_firewalls()
        print(f"\nFound {len(firewalls)} firewalls in database")
        
        for fw in firewalls:
            fw_name = fw['name']
            print(f"\n--- Firewall: {fw_name} ---")
            
            # Check if get_available_interfaces method exists
            if hasattr(db, 'get_available_interfaces'):
                interfaces = db.get_available_interfaces(fw_name)
                print(f"Available interfaces: {len(interfaces)}")
                if interfaces:
                    for iface in interfaces:
                        print(f"  - {iface}")
                else:
                    print("  (no interfaces found)")
            else:
                print("ERROR: get_available_interfaces method not found in database!")
            
            # Check if interface_metrics table has data
            if hasattr(db, 'get_interface_metrics'):
                print(f"\nChecking for interface metrics data...")
                
                # Try to get any interface metrics
                cursor = db.conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT interface_name 
                    FROM interface_metrics 
                    WHERE firewall_name = ?
                    LIMIT 20
                """, (fw_name,))
                
                db_interfaces = [row[0] for row in cursor.fetchall()]
                if db_interfaces:
                    print(f"Interfaces with data in database: {len(db_interfaces)}")
                    for iface in db_interfaces[:10]:  # Show first 10
                        # Get count of records
                        cursor.execute("""
                            SELECT COUNT(*) 
                            FROM interface_metrics 
                            WHERE firewall_name = ? AND interface_name = ?
                        """, (fw_name, iface))
                        count = cursor.fetchone()[0]
                        print(f"  - {iface}: {count} records")
                else:
                    print("  No interface data found in database!")
                    
                    # Check if table exists and is empty
                    cursor.execute("""
                        SELECT COUNT(*) FROM interface_metrics
                    """)
                    total_count = cursor.fetchone()[0]
                    print(f"  Total interface_metrics records (all firewalls): {total_count}")
            else:
                print("ERROR: get_interface_metrics method not found in database!")
        
        return True
        
    except Exception as e:
        print(f"ERROR checking database: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_firewall_config(config_path="config.yaml"):
    """Check firewall configuration for interface monitoring"""
    try:
        from config import ConfigManager
        
        print("\n" + "=" * 80)
        print("FIREWALL CONFIGURATION CHECK")
        print("=" * 80)
        
        config_manager = ConfigManager(config_path)
        
        for fw in config_manager.firewalls.values():
            print(f"\n--- Firewall: {fw.name} ---")
            print(f"Host: {fw.host}")
            print(f"Enabled: {fw.enabled}")
            
            # Check interface monitoring settings
            if hasattr(fw, 'interface_monitoring'):
                print(f"Interface Monitoring: {fw.interface_monitoring}")
            else:
                print("Interface Monitoring: NOT CONFIGURED (will default to False)")
            
            if hasattr(fw, 'auto_discover_interfaces'):
                print(f"Auto Discover Interfaces: {fw.auto_discover_interfaces}")
            else:
                print("Auto Discover Interfaces: NOT CONFIGURED")
            
            if hasattr(fw, 'monitor_interfaces'):
                print(f"Monitor Interfaces: {fw.monitor_interfaces}")
            else:
                print("Monitor Interfaces: NOT CONFIGURED")
            
            if hasattr(fw, 'exclude_interfaces'):
                print(f"Exclude Interfaces: {fw.exclude_interfaces}")
            else:
                print("Exclude Interfaces: NOT CONFIGURED")
            
            if hasattr(fw, 'interface_configs'):
                print(f"Interface Configs: {len(fw.interface_configs) if fw.interface_configs else 0} configured")
                if fw.interface_configs:
                    for ic in fw.interface_configs[:5]:  # Show first 5
                        print(f"  - {ic.name}: enabled={ic.enabled}, display={ic.display_name}")
            
            # Test should_monitor_interface if available
            if hasattr(fw, 'should_monitor_interface'):
                print("\nTesting should_monitor_interface() method:")
                test_interfaces = ['ethernet1/1', 'ethernet1/2', 'ae1', 'tunnel.1']
                for iface in test_interfaces:
                    result = fw.should_monitor_interface(iface)
                    print(f"  {iface}: {'YES' if result else 'NO'}")
        
        return True
        
    except Exception as e:
        print(f"ERROR checking config: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_collector_status():
    """Check if interface collector is running"""
    print("\n" + "=" * 80)
    print("COLLECTOR STATUS CHECK")
    print("=" * 80)
    
    try:
        from collectors import EnhancedMetricsCollector
        
        print("\nEnhancedMetricsCollector features:")
        print(f"- Has collect_interface_metrics: {hasattr(EnhancedMetricsCollector, 'collect_interface_metrics')}")
        print(f"- Has _collect_interface_counters: {hasattr(EnhancedMetricsCollector, '_collect_interface_counters')}")
        
        return True
    except Exception as e:
        print(f"ERROR checking collectors: {e}")
        return False

def suggest_fixes():
    """Suggest fixes based on findings"""
    print("\n" + "=" * 80)
    print("SUGGESTED FIXES")
    print("=" * 80)
    
    print("""
Common Interface Monitoring Issues:

1. INTERFACE MONITORING NOT ENABLED
   Fix: In config.yaml, set for each firewall:
   ```
   interface_monitoring: true
   auto_discover_interfaces: true
   ```

2. NO INTERFACES IN DATABASE
   Possible causes:
   - Collector hasn't run yet (wait 60 seconds)
   - Interface monitoring disabled in config
   - API permissions issue
   - Firewall doesn't have any up interfaces
   
   Fix: Check logs for interface collection errors

3. INTERFACES COLLECTED BUT NOT SHOWING
   Possible causes:
   - Web dashboard cache issue (refresh page)
   - API endpoint returning empty data
   - JavaScript not loading properly
   
   Fix: Check browser console for errors

4. PERMISSION ISSUES
   The PAN-OS API key needs these permissions:
   - XML API
   - Dashboard (or Network > Interfaces Read)
   
   Fix: Update API key permissions in PAN-OS

DEBUGGING STEPS:
1. Run this diagnostic script
2. Check if interface_monitoring: true in config.yaml
3. Restart collector and wait 60 seconds
4. Check database with: sqlite3 metrics.db "SELECT * FROM interface_metrics LIMIT 5;"
5. Check API endpoint: curl http://localhost:8080/api/firewall/FIREWALL_NAME/interfaces
6. Check browser console for JavaScript errors
""")

def main():
    """Main diagnostic routine"""
    print("PAN-OS Interface Monitoring Diagnostic Tool")
    print("=" * 80)
    
    # Get paths from command line or use defaults
    db_path = sys.argv[1] if len(sys.argv) > 1 else "metrics.db"
    config_path = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"
    
    print(f"Database: {db_path}")
    print(f"Config: {config_path}")
    
    # Check if files exist
    if not Path(db_path).exists():
        print(f"\nERROR: Database file not found: {db_path}")
        print("Usage: python3 diagnose_interfaces.py [db_path] [config_path]")
        return 1
    
    if not Path(config_path).exists():
        print(f"\nERROR: Config file not found: {config_path}")
        return 1
    
    # Run checks
    results = {
        'database': check_database_interfaces(db_path),
        'config': check_firewall_config(config_path),
        'collectors': check_collector_status()
    }
    
    # Show summary
    print("\n" + "=" * 80)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 80)
    for check, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{check.upper()}: {status}")
    
    # Suggest fixes
    suggest_fixes()
    
    return 0 if all(results.values()) else 1

if __name__ == "__main__":
    sys.exit(main())

