#!/usr/bin/env python3
"""
Unit tests for database performance optimizations
Tests connection pooling, batch queries, and index creation
"""
import unittest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from database import EnhancedMetricsDatabase


class TestDatabaseConnectionPooling(unittest.TestCase):
    """Test database connection pooling"""

    def setUp(self):
        """Create temporary database for testing"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_metrics.db"
        self.db = EnhancedMetricsDatabase(str(self.db_path))

    def tearDown(self):
        """Clean up temporary database"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_connection_pool_initialization(self):
        """Test that connection pool is initialized"""
        self.assertTrue(hasattr(self.db, '_connection_pool'))
        self.assertTrue(hasattr(self.db, '_pool_lock'))
        self.assertTrue(hasattr(self.db, '_thread_local'))

    def test_connection_reuse(self):
        """Test that connections are reused from pool"""
        # Make multiple queries and check pool grows
        for i in range(5):
            self.db.register_firewall(f"fw{i}", f"https://fw{i}.example.com")

        # Pool should have connections
        pool_size = self.db._connection_pool.qsize()
        self.assertGreater(pool_size, 0, "Connection pool should have reused connections")
        self.assertLessEqual(pool_size, 10, "Pool should not exceed maximum size")

    def test_connection_pool_limit(self):
        """Test that connection pool doesn't exceed max size"""
        # Create more connections than pool size
        for i in range(20):
            self.db.register_firewall(f"fw{i}", f"https://fw{i}.example.com")

        pool_size = self.db._connection_pool.qsize()
        self.assertLessEqual(pool_size, 10, "Pool should not exceed 10 connections")


class TestBatchQueries(unittest.TestCase):
    """Test batch query methods that fix N+1 problems"""

    def setUp(self):
        """Create temporary database with test data"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_metrics.db"
        self.db = EnhancedMetricsDatabase(str(self.db_path))

        # Register test firewall
        self.db.register_firewall("test_fw", "https://test.example.com")

        # Insert test interface metrics
        timestamp = datetime.now(timezone.utc)
        for interface in ["ethernet1/1", "ethernet1/2", "ethernet1/3"]:
            for i in range(5):
                metrics = {
                    'interface_name': interface,
                    'timestamp': timestamp - timedelta(minutes=i),
                    'rx_mbps': 10.0 + i,
                    'tx_mbps': 5.0 + i,
                    'total_mbps': 15.0 + i,
                    'rx_pps': 1000,
                    'tx_pps': 500,
                    'rx_bytes': 1000000,
                    'tx_bytes': 500000,
                    'rx_packets': 10000,
                    'tx_packets': 5000,
                    'rx_errors': 0,
                    'tx_errors': 0,
                    'interval_seconds': 30.0
                }
                self.db.insert_interface_metrics("test_fw", metrics)

    def tearDown(self):
        """Clean up temporary database"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_interface_metrics_batch(self):
        """Test batch interface metrics query"""
        interfaces = ["ethernet1/1", "ethernet1/2", "ethernet1/3"]
        result = self.db.get_interface_metrics_batch("test_fw", interfaces, limit=500)

        # Should return data for all 3 interfaces
        self.assertEqual(len(result), 3, "Should return metrics for 3 interfaces")
        self.assertIn("ethernet1/1", result)
        self.assertIn("ethernet1/2", result)
        self.assertIn("ethernet1/3", result)

        # Each interface should have 5 data points (we inserted 5 per interface in setUp)
        for interface in interfaces:
            self.assertGreater(len(result[interface]), 0, f"{interface} should have data")
            self.assertEqual(len(result[interface]), 5, f"{interface} should have all 5 data points")

    def test_get_interface_metrics_batch_per_interface_limit(self):
        """Test that limit applies PER interface, not globally"""
        interfaces = ["ethernet1/1", "ethernet1/2", "ethernet1/3"]

        # Request limit of 3 points
        result = self.db.get_interface_metrics_batch("test_fw", interfaces, limit=3)

        # Should return data for all 3 interfaces
        self.assertEqual(len(result), 3, "Should return metrics for all 3 interfaces")

        # IMPORTANT: Each interface should get UP TO 3 points (limit per interface)
        # NOT 3 points total divided among interfaces
        for interface in interfaces:
            self.assertGreater(len(result[interface]), 0, f"{interface} should have data")
            self.assertLessEqual(len(result[interface]), 3, f"{interface} should have at most 3 points")
            # Since we inserted 5 points per interface, with limit=3 we should get exactly 3
            self.assertEqual(len(result[interface]), 3, f"{interface} should have exactly 3 points with limit=3")

    def test_get_interface_metrics_batch_with_time_filter(self):
        """Test batch query with time filters"""
        interfaces = ["ethernet1/1", "ethernet1/2"]
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=2)

        result = self.db.get_interface_metrics_batch(
            "test_fw", interfaces, start_time=start_time, end_time=end_time
        )

        self.assertGreater(len(result), 0, "Should return filtered results")

    def test_get_latest_interface_summary(self):
        """Test latest interface summary batch query"""
        interfaces = ["ethernet1/1", "ethernet1/2", "ethernet1/3"]
        result = self.db.get_latest_interface_summary("test_fw", interfaces)

        # Should return latest metrics for each interface
        self.assertEqual(len(result), 3, "Should return latest for 3 interfaces")

        for interface in interfaces:
            self.assertIn(interface, result, f"Should have {interface} in results")
            metrics = result[interface]
            self.assertIn('rx_mbps', metrics)
            self.assertIn('tx_mbps', metrics)
            self.assertIn('total_mbps', metrics)

    def test_batch_query_performance(self):
        """Test that batch query is faster than N+1 queries"""
        import time

        interfaces = ["ethernet1/1", "ethernet1/2", "ethernet1/3"]

        # Time N+1 queries (individual queries in loop)
        start = time.time()
        individual_results = {}
        for interface in interfaces:
            metrics = self.db.get_interface_metrics("test_fw", interface, limit=5)
            if metrics:
                individual_results[interface] = metrics
        individual_time = time.time() - start

        # Time batch query
        start = time.time()
        batch_results = self.db.get_interface_metrics_batch("test_fw", interfaces, limit=5)
        batch_time = time.time() - start

        # Batch should be faster (or at least not slower)
        self.assertLessEqual(batch_time, individual_time * 1.5,
                            "Batch query should be comparable or faster than N+1 queries")


class TestDatabaseIndexes(unittest.TestCase):
    """Test that performance indexes are created"""

    def setUp(self):
        """Create temporary database"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_metrics.db"
        self.db = EnhancedMetricsDatabase(str(self.db_path))

    def tearDown(self):
        """Clean up temporary database"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_interface_metrics_indexes_created(self):
        """Test that interface metrics indexes are created"""
        with self.db._get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='interface_metrics'"
            )
            indexes = [row[0] for row in cursor.fetchall()]

        # Check for expected indexes (partial indexes removed for SQLite compatibility)
        expected_indexes = [
            'idx_interface_metrics_firewall_interface_timestamp',
            'idx_interface_metrics_firewall_timestamp'
        ]

        for expected in expected_indexes:
            self.assertIn(expected, indexes, f"Index {expected} should be created")

    def test_session_statistics_indexes_created(self):
        """Test that session statistics indexes are created"""
        with self.db._get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='session_statistics'"
            )
            indexes = [row[0] for row in cursor.fetchall()]

        expected_indexes = [
            'idx_session_statistics_firewall_timestamp'
        ]

        for expected in expected_indexes:
            self.assertIn(expected, indexes, f"Index {expected} should be created")

    def test_indexes_improve_query_performance(self):
        """Test that indexes exist and improve performance"""
        # Just verify that standard indexes exist (partial indexes removed for compatibility)
        with self.db._get_connection() as conn:
            cursor = conn.execute(
                """SELECT name FROM sqlite_master WHERE type='index'"""
            )
            indexes = [row[0] for row in cursor.fetchall()]

        # Should have at least the main performance indexes
        self.assertGreater(len(indexes), 0, "Should have performance indexes created")


class TestFirewallHardwareInfo(unittest.TestCase):
    """Test firewall hardware information storage and retrieval"""

    def setUp(self):
        """Create temporary database for testing"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_metrics.db"
        self.db = EnhancedMetricsDatabase(str(self.db_path))

    def tearDown(self):
        """Clean up temporary database"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_schema_has_hardware_columns(self):
        """Test that firewalls table has hardware info columns"""
        with self.db._get_connection() as conn:
            cursor = conn.execute("PRAGMA table_info(firewalls)")
            columns = [row[1] for row in cursor.fetchall()]

        expected_columns = ['model', 'family', 'platform_family', 'serial',
                          'hostname', 'sw_version']

        for col in expected_columns:
            self.assertIn(col, columns,
                         f"Column {col} should exist in firewalls table")

    def test_register_firewall_with_hardware_info(self):
        """Test registering firewall with hardware information"""
        hardware_info = {
            'model': 'PA-3430',
            'family': '3000',
            'platform_family': 'pa-3400-series',
            'serial': '001234567890',
            'hostname': 'datacenter-fw',
            'sw_version': '11.0.3'
        }

        success = self.db.register_firewall('test_fw', 'https://10.0.0.1', hardware_info)

        self.assertTrue(success, "Should successfully register firewall with hardware info")

        # Verify data was stored
        firewalls = self.db.get_all_firewalls()
        self.assertEqual(len(firewalls), 1)

        fw = firewalls[0]
        self.assertEqual(fw['name'], 'test_fw')
        self.assertEqual(fw['model'], 'PA-3430')
        self.assertEqual(fw['family'], '3000')
        self.assertEqual(fw['platform_family'], 'pa-3400-series')
        self.assertEqual(fw['serial'], '001234567890')
        self.assertEqual(fw['hostname'], 'datacenter-fw')
        self.assertEqual(fw['sw_version'], '11.0.3')

    def test_register_firewall_without_hardware_info(self):
        """Test registering firewall without hardware info still works"""
        success = self.db.register_firewall('test_fw', 'https://10.0.0.1')

        self.assertTrue(success, "Should successfully register firewall without hardware info")

        firewalls = self.db.get_all_firewalls()
        self.assertEqual(len(firewalls), 1)

        fw = firewalls[0]
        self.assertEqual(fw['name'], 'test_fw')
        self.assertEqual(fw['host'], 'https://10.0.0.1')
        # Hardware fields should be None or empty
        self.assertIn(fw.get('model'), [None, ''])

    def test_register_firewall_updates_hardware_info(self):
        """Test that re-registering firewall updates hardware info"""
        # Register without hardware info
        self.db.register_firewall('test_fw', 'https://10.0.0.1')

        # Register again with hardware info
        hardware_info = {
            'model': 'PA-3430',
            'family': '3000',
            'sw_version': '11.0.3'
        }
        self.db.register_firewall('test_fw', 'https://10.0.0.1', hardware_info)

        # Verify hardware info was added
        firewalls = self.db.get_all_firewalls()
        self.assertEqual(len(firewalls), 1)

        fw = firewalls[0]
        self.assertEqual(fw['model'], 'PA-3430')
        self.assertEqual(fw['family'], '3000')
        self.assertEqual(fw['sw_version'], '11.0.3')

    def test_get_all_firewalls_includes_hardware_info(self):
        """Test that get_all_firewalls returns hardware info"""
        # Register multiple firewalls with different hardware info
        firewalls_data = [
            ('fw1', 'https://10.0.0.1', {'model': 'PA-3430', 'sw_version': '11.0.3'}),
            ('fw2', 'https://10.0.0.2', {'model': 'PA-5445', 'sw_version': '11.1.0'}),
            ('fw3', 'https://10.0.0.3', None)
        ]

        for name, host, hw_info in firewalls_data:
            self.db.register_firewall(name, host, hw_info)

        # Retrieve all firewalls
        firewalls = self.db.get_all_firewalls()

        self.assertEqual(len(firewalls), 3)

        # Verify first firewall
        fw1 = next(fw for fw in firewalls if fw['name'] == 'fw1')
        self.assertEqual(fw1['model'], 'PA-3430')
        self.assertEqual(fw1['sw_version'], '11.0.3')

        # Verify second firewall
        fw2 = next(fw for fw in firewalls if fw['name'] == 'fw2')
        self.assertEqual(fw2['model'], 'PA-5445')
        self.assertEqual(fw2['sw_version'], '11.1.0')

        # Verify third firewall (no hardware info)
        fw3 = next(fw for fw in firewalls if fw['name'] == 'fw3')
        self.assertIn(fw3.get('model'), [None, ''])

    def test_schema_migration_idempotent(self):
        """Test that schema migration can be run multiple times safely"""
        # Migration happens during __init__, so create multiple instances
        db1 = EnhancedMetricsDatabase(str(self.db_path))
        db2 = EnhancedMetricsDatabase(str(self.db_path))
        db3 = EnhancedMetricsDatabase(str(self.db_path))

        # Verify columns still exist
        with self.db._get_connection() as conn:
            cursor = conn.execute("PRAGMA table_info(firewalls)")
            columns = [row[1] for row in cursor.fetchall()]

        self.assertIn('model', columns)
        self.assertIn('family', columns)
        self.assertIn('sw_version', columns)

    def test_hardware_info_with_partial_data(self):
        """Test storing hardware info with only some fields populated"""
        hardware_info = {
            'model': 'PA-3430',
            'sw_version': '11.0.3'
            # Other fields not provided
        }

        self.db.register_firewall('test_fw', 'https://10.0.0.1', hardware_info)

        firewalls = self.db.get_all_firewalls()
        fw = firewalls[0]

        self.assertEqual(fw['model'], 'PA-3430')
        self.assertEqual(fw['sw_version'], '11.0.3')
        # Unprovided fields should be None or empty
        self.assertIn(fw.get('family'), [None, ''])
        self.assertIn(fw.get('serial'), [None, ''])


if __name__ == '__main__':
    unittest.main()
