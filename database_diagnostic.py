#!/usr/bin/env python3
"""
Database Schema Diagnostic Tool
Check if enhanced schema migration completed successfully
"""
import sqlite3
import sys
from pathlib import Path

def check_database_schema(db_path):
    """Check database schema and migration status"""
    print("=" * 60)
    print("DATABASE SCHEMA DIAGNOSTIC")
    print("=" * 60)
    
    if not Path(db_path).exists():
        print(f"❌ Database file not found: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if enhanced tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"📊 Database: {db_path}")
        print(f"📋 Tables found: {len(tables)}")
        for table in sorted(tables):
            print(f"   - {table}")
        
        # Check metrics table schema
        print("\n🔍 METRICS TABLE ANALYSIS:")
        cursor.execute("PRAGMA table_info(metrics)")
        metrics_columns = [row[1] for row in cursor.fetchall()]
        
        print(f"   Columns: {len(metrics_columns)}")
        for col in metrics_columns:
            print(f"   - {col}")
        
        # Check for enhanced columns
        enhanced_columns = [
            'throughput_mbps_max', 'throughput_mbps_min', 'throughput_mbps_p95',
            'pps_max', 'pps_min', 'pps_p95',
            'session_sample_count', 'session_success_rate', 'session_sampling_period'
        ]
        
        print("\n✅ ENHANCED COLUMNS STATUS:")
        missing_columns = []
        for col in enhanced_columns:
            if col in metrics_columns:
                print(f"   ✓ {col}")
            else:
                print(f"   ❌ {col} - MISSING")
                missing_columns.append(col)
        
        # Check interface_metrics table
        print("\n🌐 INTERFACE METRICS TABLE:")
        if 'interface_metrics' in tables:
            print("   ✓ interface_metrics table exists")
            cursor.execute("PRAGMA table_info(interface_metrics)")
            interface_cols = [row[1] for row in cursor.fetchall()]
            print(f"   Columns: {', '.join(interface_cols)}")
            
            # Check data
            cursor.execute("SELECT COUNT(*) FROM interface_metrics")
            count = cursor.fetchone()[0]
            print(f"   Records: {count}")
            
            if count > 0:
                cursor.execute("SELECT DISTINCT firewall_name FROM interface_metrics")
                firewalls = [row[0] for row in cursor.fetchall()]
                print(f"   Firewalls with interface data: {', '.join(firewalls)}")
                
                cursor.execute("SELECT DISTINCT interface_name FROM interface_metrics LIMIT 10")
                interfaces = [row[0] for row in cursor.fetchall()]
                print(f"   Sample interfaces: {', '.join(interfaces)}")
        else:
            print("   ❌ interface_metrics table NOT FOUND")
        
        # Check session_statistics table
        print("\n🔗 SESSION STATISTICS TABLE:")
        if 'session_statistics' in tables:
            print("   ✓ session_statistics table exists")
            cursor.execute("PRAGMA table_info(session_statistics)")
            session_cols = [row[1] for row in cursor.fetchall()]
            print(f"   Columns: {', '.join(session_cols)}")
            
            # Check data
            cursor.execute("SELECT COUNT(*) FROM session_statistics")
            count = cursor.fetchone()[0]
            print(f"   Records: {count}")
        else:
            print("   ❌ session_statistics table NOT FOUND")
        
        # Check recent data
        print("\n📅 RECENT DATA:")
        cursor.execute("SELECT COUNT(*) FROM metrics WHERE timestamp > datetime('now', '-1 hour')")
        recent_metrics = cursor.fetchone()[0]
        print(f"   Recent metrics (last hour): {recent_metrics}")
        
        if 'interface_metrics' in tables:
            cursor.execute("SELECT COUNT(*) FROM interface_metrics WHERE timestamp > datetime('now', '-1 hour')")
            recent_interfaces = cursor.fetchone()[0]
            print(f"   Recent interface metrics (last hour): {recent_interfaces}")
        
        conn.close()
        
        # Summary
        print("\n" + "=" * 60)
        print("MIGRATION STATUS SUMMARY")
        print("=" * 60)
        
        if missing_columns:
            print(f"❌ Schema migration INCOMPLETE - {len(missing_columns)} columns missing")
            print("   Missing enhanced columns:")
            for col in missing_columns:
                print(f"   - {col}")
            print("\n💡 SOLUTION: Run the enhanced database migration")
            return False
        else:
            print("✅ Schema migration COMPLETE - all enhanced columns present")
            
        if 'interface_metrics' not in tables:
            print("❌ Interface monitoring tables missing")
            return False
        else:
            print("✅ Interface monitoring tables present")
            
        if 'session_statistics' not in tables:
            print("❌ Session statistics tables missing")
            return False
        else:
            print("✅ Session statistics tables present")
        
        print("✅ Database schema is fully migrated for enhanced monitoring")
        return True
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        import traceback
        traceback.print_exc()
        return False

def migrate_database_schema(db_path):
    """Force database schema migration"""
    print("\n" + "=" * 60)
    print("FORCING DATABASE SCHEMA MIGRATION")
    print("=" * 60)
    
    try:
        # Import the enhanced database class
        from database import EnhancedMetricsDatabase
        
        print(f"🔄 Initializing enhanced database: {db_path}")
        db = EnhancedMetricsDatabase(db_path)
        
        print("✅ Enhanced database initialization complete")
        print("   Schema migration should have run automatically")
        
        # Re-check schema
        return check_database_schema(db_path)
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main diagnostic routine"""
    if len(sys.argv) < 2:
        print("Usage: python3 database_diagnostic.py DATABASE_PATH [--migrate]")
        print("\nExample:")
        print("  python3 database_diagnostic.py ./data/metrics.db")
        print("  python3 database_diagnostic.py ./data/metrics.db --migrate")
        return 1
    
    db_path = sys.argv[1]
    should_migrate = "--migrate" in sys.argv
    
    # Check current schema
    schema_ok = check_database_schema(db_path)
    
    if not schema_ok and should_migrate:
        print("\n🔧 Schema issues detected, attempting migration...")
        schema_ok = migrate_database_schema(db_path)
    
    if not schema_ok:
        print("\n💡 To fix schema issues, run:")
        print(f"   python3 database_diagnostic.py {db_path} --migrate")
    
    return 0 if schema_ok else 1

if __name__ == "__main__":
    sys.exit(main())
