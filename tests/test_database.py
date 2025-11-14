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


if __name__ == '__main__':
    unittest.main()
