# Unit Tests for PAN-OS Multi-Firewall Monitor

This directory contains unit tests for the performance optimizations and memory leak fixes.

## Test Files

### test_database.py
Tests database performance optimizations:
- **Connection pooling**: Validates that connections are reused from pool
- **Batch queries**: Tests N+1 query fixes for interface metrics
- **Database indexes**: Verifies that performance indexes are created
- **Latest interface summary**: Tests batch query for dashboard overview

### test_memory_leaks.py
Tests memory leak fixes:
- **Deque with maxlen**: Validates automatic size limiting
- **Queue size limits**: Tests that queues don't grow unbounded
- **Session cleanup**: Verifies requests.Session is properly closed
- **Garbage collection**: Tests GC integration
- **Memory monitoring**: Validates psutil integration

### test_web_dashboard.py
Tests web dashboard caching and health endpoint:
- **SimpleCache**: Tests TTL-based caching implementation
- **Cache expiration**: Validates entries expire after TTL
- **Health endpoint**: Tests health check data structure
- **Status determination**: Tests healthy/warning/critical logic

### test_collectors.py
Tests collector queue limits and cleanup:
- **Queue maxsize**: Validates queue size limits
- **Overflow handling**: Tests behavior when queue is full
- **Collector cleanup**: Tests session cleanup on stop
- **Thread management**: Tests daemon threads and timeouts

## Running Tests

### Setup Virtual Environment
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Run All Tests
```bash
# From project root
python -m pytest tests/

# With verbose output
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=. --cov-report=html
```

### Run Specific Test Files
```bash
# Database tests only
python -m pytest tests/test_database.py -v

# Memory leak tests only
python -m pytest tests/test_memory_leaks.py -v

# Web dashboard tests only
python -m pytest tests/test_web_dashboard.py -v

# Collector tests only
python -m pytest tests/test_collectors.py -v
```

### Run Specific Test Classes or Methods
```bash
# Run specific test class
python -m pytest tests/test_database.py::TestDatabaseConnectionPooling -v

# Run specific test method
python -m pytest tests/test_database.py::TestDatabaseConnectionPooling::test_connection_reuse -v
```

## Test Coverage

The tests cover the following optimizations:

### Memory Leak Fixes (Priority: CRITICAL)
- ✅ Deque with maxlen instead of unbounded lists
- ✅ Queue with maxsize to prevent unbounded growth
- ✅ Connection pooling to prevent connection leaks
- ✅ Requests.Session cleanup
- ✅ Periodic garbage collection

### Query Optimizations (Priority: CRITICAL)
- ✅ Batch query for interface metrics (N+1 fix)
- ✅ Latest interface summary batch query (dashboard N+1 fix)
- ✅ Database indexes for common query patterns
- ✅ Partial indexes for recent data

### Performance Enhancements (Priority: HIGH)
- ✅ Dashboard caching with TTL
- ✅ Health check endpoint
- ✅ Memory monitoring

## Expected Test Results

All tests should pass with the optimizations implemented:

```
tests/test_database.py::TestDatabaseConnectionPooling ✓✓✓
tests/test_database.py::TestBatchQueries ✓✓✓✓
tests/test_database.py::TestDatabaseIndexes ✓✓✓
tests/test_memory_leaks.py::TestInterfaceMonitorMemoryFixes ✓✓
tests/test_memory_leaks.py::TestQueueSizeLimits ✓✓
tests/test_memory_leaks.py::TestRequestsSessionCleanup ✓✓
tests/test_memory_leaks.py::TestGarbageCollection ✓✓
tests/test_web_dashboard.py::TestSimpleCache ✓✓✓✓✓
tests/test_web_dashboard.py::TestHealthEndpoint ✓✓✓
tests/test_web_dashboard.py::TestDashboardCaching ✓✓
tests/test_collectors.py::TestCollectorQueueLimits ✓✓✓✓✓
tests/test_collectors.py::TestEnhancedFirewallCollectorCleanup ✓
tests/test_collectors.py::TestCollectorThreadManagement ✓✓
tests/test_collectors.py::TestCollectorErrorHandling ✓✓

======================== XX passed in X.XXs ========================
```

## Continuous Integration

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.8'
      - run: pip install -r requirements.txt
      - run: python -m pytest tests/ -v --cov=.
```

## Troubleshooting

### Import Errors
If you get import errors, ensure you're running from the project root:
```bash
cd /path/to/PALO-PANOS-MONITOR
python -m pytest tests/
```

### Missing Dependencies
Install test dependencies:
```bash
pip install pytest pytest-cov pytest-mock
```

### Database Lock Errors
Tests create temporary databases. If you see lock errors:
```bash
# Kill any hanging Python processes
pkill -9 python

# Run tests again
python -m pytest tests/
```

## Adding New Tests

When adding new optimizations, create corresponding tests:

1. Create test file in `tests/` directory
2. Name file `test_<module>.py`
3. Create test classes inheriting from `unittest.TestCase`
4. Name test methods starting with `test_`
5. Update this README with test descriptions

Example:
```python
class TestNewOptimization(unittest.TestCase):
    """Test description"""

    def setUp(self):
        """Setup test fixtures"""
        pass

    def test_optimization_works(self):
        """Test that optimization performs as expected"""
        # Arrange
        # Act
        # Assert
        pass
```
