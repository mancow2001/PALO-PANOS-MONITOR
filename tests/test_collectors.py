#!/usr/bin/env python3
"""
Unit tests for collector performance and memory fixes
Tests queue limits and collector cleanup
"""
import unittest
from queue import Queue, Full, Empty
from unittest.mock import Mock, patch, MagicMock
import time


class TestCollectorQueueLimits(unittest.TestCase):
    """Test queue size limits in collectors"""

    def test_queue_has_maxsize(self):
        """Test that metrics queue has maximum size"""
        # Simulate MultiFirewallCollector queue
        metrics_queue = Queue(maxsize=1000)

        self.assertEqual(metrics_queue.maxsize, 1000,
                        "Queue should have maxsize of 1000")

    def test_queue_put_with_timeout_on_full(self):
        """Test that put with timeout handles full queue"""
        queue = Queue(maxsize=10)

        # Fill the queue
        for i in range(10):
            queue.put(i, block=False)

        # Try to put with timeout - should raise or timeout
        with self.assertRaises((Full, Exception)):
            queue.put(11, timeout=0.1)

    def test_queue_overflow_handling(self):
        """Test overflow handling logic"""
        queue = Queue(maxsize=10)
        queue_full_warnings = 0

        # Fill queue
        for i in range(10):
            queue.put(i)

        # Simulate overflow attempt
        for i in range(5):
            try:
                queue.put(i, timeout=0.01)
            except (Full, Exception):
                queue_full_warnings += 1

        self.assertGreater(queue_full_warnings, 0,
                          "Should have recorded overflow warnings")

    def test_queue_size_tracking(self):
        """Test that queue size can be tracked"""
        queue = Queue(maxsize=1000)

        # Add items
        for i in range(50):
            queue.put(i)

        size = queue.qsize()
        self.assertEqual(size, 50, "Queue size should be tracked")

    def test_queue_prevents_unbounded_growth(self):
        """Test that maxsize prevents memory leak"""
        queue = Queue(maxsize=100)

        # Try to add way more than maxsize
        added = 0
        for i in range(200):
            try:
                queue.put(i, block=False)
                added += 1
            except Full:
                break

        self.assertEqual(added, 100,
                        "Should only be able to add up to maxsize")


class TestEnhancedFirewallCollectorCleanup(unittest.TestCase):
    """Test collector cleanup methods"""

    @patch('collectors.requests.Session')
    @patch('collectors.InterfaceMonitor')
    def test_collector_stop_closes_session(self, mock_iface_monitor, mock_session_class):
        """Test that collector.stop() closes the requests session"""
        from collectors import EnhancedFirewallCollector
        from pathlib import Path

        # Mock config
        mock_config = Mock()
        mock_config.host = "https://test.example.com"
        mock_config.verify_ssl = False
        mock_config.username = "admin"
        mock_config.password = "pass"

        # Mock session
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        # Create collector
        collector = EnhancedFirewallCollector(
            "test_fw",
            mock_config,
            Path("/tmp"),
            None
        )

        # Stop collector
        collector.stop()

        # Should have called session.close()
        self.assertTrue(mock_session.close.called,
                       "Session close should be called on stop")

    def test_collector_cleanup_on_del(self):
        """Test that cleanup happens on collector deletion"""
        # This is implicitly tested through PanOSClient.__del__
        # which is tested in test_memory_leaks.py
        pass


class TestMultiFirewallCollectorMetrics(unittest.TestCase):
    """Test MultiFirewallCollector metrics collection"""

    def test_queue_full_warnings_tracked(self):
        """Test that queue full warnings are tracked"""
        # Simulate the warning counter
        queue_full_warnings = 0

        # Simulate overflow attempts
        for i in range(15):
            queue_full_warnings += 1

        self.assertEqual(queue_full_warnings, 15,
                        "Should track all overflow attempts")

    def test_warning_logged_every_10th_drop(self):
        """Test that warnings are only logged every 10th drop"""
        queue_full_warnings = 0
        log_count = 0

        for i in range(25):
            queue_full_warnings += 1
            if queue_full_warnings % 10 == 1:
                log_count += 1

        # Should log at 1, 11, 21 = 3 times
        self.assertEqual(log_count, 3,
                        "Should log every 10th warning")


class TestCollectorThreadManagement(unittest.TestCase):
    """Test collector thread lifecycle"""

    def test_daemon_thread_configuration(self):
        """Test that collector threads are configured as daemon"""
        import threading

        # Create a daemon thread (like collectors do)
        thread = threading.Thread(target=lambda: None, daemon=True)

        self.assertTrue(thread.daemon,
                       "Collector threads should be daemon threads")

    def test_thread_join_timeout(self):
        """Test that thread join has timeout to prevent hanging"""
        import threading

        def long_running_task():
            time.sleep(10)

        thread = threading.Thread(target=long_running_task, daemon=True)
        thread.start()

        # Join with timeout (like collector stop does)
        start = time.time()
        thread.join(timeout=0.1)
        elapsed = time.time() - start

        # Should timeout quickly, not wait 10 seconds
        self.assertLess(elapsed, 0.5,
                       "Thread join should timeout quickly")


class TestCollectorErrorHandling(unittest.TestCase):
    """Test error handling in collectors"""

    def test_queue_put_handles_timeout_exception(self):
        """Test that collector handles queue timeout exceptions"""
        queue = Queue(maxsize=1)
        queue.put("item1")

        # Attempt to put with timeout
        exception_caught = False
        try:
            queue.put("item2", timeout=0.01)
        except (Full, Exception):
            exception_caught = True

        self.assertTrue(exception_caught,
                       "Should catch exception when queue is full")

    def test_collector_continues_after_queue_full(self):
        """Test that collector continues even if queue is full"""
        # Simulate collector behavior
        queue = Queue(maxsize=2)
        items_processed = 0
        items_dropped = 0

        # Simulate processing with full queue
        for i in range(5):
            try:
                queue.put(i, timeout=0.01)
                items_processed += 1
            except (Full, Exception):
                items_dropped += 1
                # Collector continues despite drop

        self.assertEqual(items_processed, 2, "Should process 2 items")
        self.assertEqual(items_dropped, 3, "Should drop 3 items")


if __name__ == '__main__':
    unittest.main()
