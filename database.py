#!/usr/bin/env python3
"""
Database management for PAN-OS Multi-Firewall Monitor
Provides persistent storage for metrics data using SQLite
Enhanced with automatic schema migration for throughput and PPS statistics
"""
import sqlite3
import logging
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from contextlib import contextmanager

LOG = logging.getLogger("panos_monitor.database")

def parse_iso_datetime(timestamp_str: str) -> datetime:
    """
    Parse ISO datetime string - simplified and more robust version
    """
    if not timestamp_str:
        return datetime.now(timezone.utc)
    
    # Remove 'Z' and replace with +00:00 for UTC
    if timestamp_str.endswith('Z'):
        timestamp_str = timestamp_str[:-1] + '+00:00'
    
    try:
        # First, try the built-in fromisoformat (Python 3.7+)
        return datetime.fromisoformat(timestamp_str)
    except (ValueError, AttributeError):
        pass
    
    try:
        # Handle space instead of 'T' separator
        if ' ' in timestamp_str and 'T' not in timestamp_str:
            timestamp_str = timestamp_str.replace(' ', 'T', 1)
        
        # Try again with T separator
        return datetime.fromisoformat(timestamp_str)
    except ValueError:
        pass
    
    # Try manual parsing for edge cases
    try:
        # Remove timezone for strptime, then add it back
        if '+' in timestamp_str:
            dt_part, tz_part = timestamp_str.rsplit('+', 1)
            sign = 1
        elif timestamp_str.count('-') > 2:  # Has timezone
            dt_part, tz_part = timestamp_str.rsplit('-', 1)
            sign = -1
        else:
            # No timezone, assume UTC
            dt = datetime.strptime(timestamp_str.replace('T', ' '), '%Y-%m-%d %H:%M:%S.%f')
            return dt.replace(tzinfo=timezone.utc)
        
        # Parse the datetime part
        try:
            dt = datetime.strptime(dt_part.replace('T', ' '), '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            dt = datetime.strptime(dt_part.replace('T', ' '), '%Y-%m-%d %H:%M:%S')
        
        # Parse timezone
        if ':' in tz_part:
            hours, minutes = map(int, tz_part.split(':'))
        else:
            hours = int(tz_part[:2])
            minutes = int(tz_part[2:]) if len(tz_part) > 2 else 0
        
        offset = timedelta(hours=sign*hours, minutes=sign*minutes)
        tz = timezone(offset)
        return dt.replace(tzinfo=tz)
        
    except Exception as e:
        LOG.debug(f"Manual parsing failed for '{timestamp_str}': {e}")
        
        # Last resort: try common formats without timezone, assume UTC
        formats = [
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d'
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(timestamp_str.split('+')[0].split('Z')[0], fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    
    LOG.warning(f"Could not parse timestamp '{timestamp_str}', using current time")
    return datetime.now(timezone.utc)

class MetricsDatabase:
    """SQLite database for storing firewall metrics with automatic schema migration"""
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """Initialize database schema with automatic migration"""
        with self._get_connection() as conn:
            # Create firewalls table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS firewalls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    host TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firewall_name TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    cpu_user REAL,
                    cpu_system REAL,
                    cpu_idle REAL,
                    mgmt_cpu REAL,
                    data_plane_cpu REAL,
                    data_plane_cpu_mean REAL,
                    data_plane_cpu_max REAL,
                    data_plane_cpu_p95 REAL,
                    throughput_mbps_total REAL,
                    pps_total REAL,
                    pbuf_util_percent REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (firewall_name) REFERENCES firewalls (name)
                )
            """)
            
            # Create indexes for better query performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_firewall_timestamp 
                ON metrics (firewall_name, timestamp)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_timestamp 
                ON metrics (timestamp)
            """)
            
            # Create configuration table for storing runtime config
            conn.execute("""
                CREATE TABLE IF NOT EXISTS configuration (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
        
        # Automatically migrate schema to add enhanced statistics columns
        self._migrate_schema()
        
        LOG.info(f"Database initialized with schema migration: {self.db_path}")
    
    def _migrate_schema(self):
        """Automatically detect and add new columns for enhanced statistics"""
        with self._get_connection() as conn:
            # Check what columns currently exist in metrics table
            cursor = conn.execute("PRAGMA table_info(metrics)")
            existing_columns = [row[1] for row in cursor.fetchall()]
            
            # Define enhanced columns we want to add
            enhanced_columns = [
                ('throughput_mbps_max', 'REAL', 'Maximum throughput during sampling period'),
                ('throughput_mbps_min', 'REAL', 'Minimum throughput during sampling period'),
                ('throughput_mbps_p95', 'REAL', '95th percentile throughput'),
                ('pps_max', 'REAL', 'Maximum packets per second'),
                ('pps_min', 'REAL', 'Minimum packets per second'),
                ('pps_p95', 'REAL', '95th percentile packets per second'),
                ('session_sample_count', 'INTEGER', 'Number of per-second samples'),
                ('session_success_rate', 'REAL', 'Success rate of sampling (0.0-1.0)'),
                ('session_sampling_period', 'REAL', 'Actual sampling period in seconds')
            ]
            
            # Track migration progress
            added_columns = []
            
            # Add any missing columns
            for column_name, column_type, description in enhanced_columns:
                if column_name not in existing_columns:
                    try:
                        conn.execute(f"ALTER TABLE metrics ADD COLUMN {column_name} {column_type}")
                        added_columns.append(column_name)
                        LOG.info(f"✅ Enhanced database: Added '{column_name}' column ({description})")
                    except Exception as e:
                        LOG.warning(f"❌ Could not add column '{column_name}': {e}")
            
            # Commit all changes
            conn.commit()
            
            # Log migration summary
            if added_columns:
                LOG.info(f"🚀 Schema migration completed: Added {len(added_columns)} new columns for enhanced statistics")
                LOG.info(f"   New capabilities: Enhanced throughput and PPS tracking with min/max/P95 statistics")
            else:
                LOG.debug("✅ Database schema is up to date - no migration needed")
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
        finally:
            conn.close()
    
    def register_firewall(self, name: str, host: str) -> bool:
        """Register a firewall in the database"""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO firewalls (name, host, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (name, host))
                conn.commit()
                LOG.info(f"Registered firewall: {name} ({host})")
                return True
        except Exception as e:
            LOG.error(f"Failed to register firewall {name}: {e}")
            return False
    
    def insert_metrics(self, firewall_name: str, metrics: Dict[str, Any]) -> bool:
        """Insert enhanced metrics data for a firewall"""
        try:
            with self._get_connection() as conn:
                # Convert timestamp string to datetime if needed
                timestamp = metrics.get('timestamp')
                if isinstance(timestamp, str):
                    timestamp = parse_iso_datetime(timestamp)
                elif timestamp is None:
                    timestamp = datetime.now(timezone.utc)
                elif isinstance(timestamp, datetime) and timestamp.tzinfo is None:
                    # Add UTC timezone if missing
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                
                # Enhanced INSERT statement with all new columns
                conn.execute("""
                    INSERT INTO metrics (
                        firewall_name, timestamp, cpu_user, cpu_system, cpu_idle,
                        mgmt_cpu, data_plane_cpu, data_plane_cpu_mean, data_plane_cpu_max, 
                        data_plane_cpu_p95, throughput_mbps_total, throughput_mbps_max,
                        throughput_mbps_min, throughput_mbps_p95, pps_total, pps_max,
                        pps_min, pps_p95, session_sample_count, session_success_rate,
                        session_sampling_period, pbuf_util_percent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    firewall_name,
                    timestamp,
                    metrics.get('cpu_user'),
                    metrics.get('cpu_system'),
                    metrics.get('cpu_idle'),
                    metrics.get('mgmt_cpu'),
                    metrics.get('data_plane_cpu'),
                    metrics.get('data_plane_cpu_mean'),
                    metrics.get('data_plane_cpu_max'),
                    metrics.get('data_plane_cpu_p95'),
                    metrics.get('throughput_mbps_total'),
                    metrics.get('throughput_mbps_max'),      # Enhanced
                    metrics.get('throughput_mbps_min'),      # Enhanced
                    metrics.get('throughput_mbps_p95'),      # Enhanced
                    metrics.get('pps_total'),
                    metrics.get('pps_max'),                  # Enhanced
                    metrics.get('pps_min'),                  # Enhanced
                    metrics.get('pps_p95'),                  # Enhanced
                    metrics.get('session_sample_count'),     # Enhanced
                    metrics.get('session_success_rate'),     # Enhanced
                    metrics.get('session_sampling_period'),  # Enhanced
                    metrics.get('pbuf_util_percent')
                ))
                conn.commit()
                return True
        except Exception as e:
            LOG.error(f"Failed to insert enhanced metrics for {firewall_name}: {e}")
            return False
    
    def get_metrics(self, firewall_name: str, start_time: Optional[datetime] = None,
                   end_time: Optional[datetime] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve metrics for a firewall within time range"""
        try:
            with self._get_connection() as conn:
                query = """
                    SELECT * FROM metrics 
                    WHERE firewall_name = ?
                """
                params = [firewall_name]
                
                if start_time:
                    query += " AND timestamp >= ?"
                    params.append(start_time)
                
                if end_time:
                    query += " AND timestamp <= ?"
                    params.append(end_time)
                
                query += " ORDER BY timestamp DESC"
                
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
                
                # Convert to list of dictionaries
                return [dict(row) for row in rows]
        except Exception as e:
            LOG.error(f"Failed to retrieve metrics for {firewall_name}: {e}")
            return []
    
    def get_latest_metrics(self, firewall_name: str, count: int = 100) -> List[Dict[str, Any]]:
        """Get the latest N metrics for a firewall"""
        return self.get_metrics(firewall_name, limit=count)
    
    def get_all_firewalls(self) -> List[Dict[str, Any]]:
        """Get list of all registered firewalls"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT f.name, f.host, f.created_at, f.updated_at,
                           COUNT(m.id) as metric_count,
                           MAX(m.timestamp) as last_metric_time
                    FROM firewalls f
                    LEFT JOIN metrics m ON f.name = m.firewall_name
                    GROUP BY f.name, f.host, f.created_at, f.updated_at
                    ORDER BY f.name
                """)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            LOG.error(f"Failed to retrieve firewalls: {e}")
            return []
    
    def get_firewall_summary(self, firewall_name: str) -> Optional[Dict[str, Any]]:
        """Get enhanced summary statistics for a firewall"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total_metrics,
                        MIN(timestamp) as first_metric,
                        MAX(timestamp) as last_metric,
                        AVG(mgmt_cpu) as avg_mgmt_cpu,
                        AVG(data_plane_cpu_mean) as avg_dp_cpu_mean,
                        AVG(data_plane_cpu_max) as avg_dp_cpu_max,
                        AVG(data_plane_cpu_p95) as avg_dp_cpu_p95,
                        AVG(throughput_mbps_total) as avg_throughput,
                        MAX(throughput_mbps_total) as max_throughput,
                        AVG(throughput_mbps_max) as avg_throughput_max,
                        MAX(throughput_mbps_max) as peak_throughput_max,
                        AVG(throughput_mbps_p95) as avg_throughput_p95,
                        AVG(pps_total) as avg_pps,
                        MAX(pps_total) as max_pps,
                        AVG(pps_max) as avg_pps_max,
                        MAX(pps_max) as peak_pps_max,
                        AVG(pps_p95) as avg_pps_p95,
                        AVG(session_sample_count) as avg_sample_count,
                        AVG(session_success_rate) as avg_success_rate,
                        AVG(pbuf_util_percent) as avg_pbuf_util
                    FROM metrics 
                    WHERE firewall_name = ?
                """, (firewall_name,))
                
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            LOG.error(f"Failed to get enhanced summary for {firewall_name}: {e}")
            return None
    
    def cleanup_old_metrics(self, days_to_keep: int = 30) -> int:
        """Remove metrics older than specified days"""
        try:
            from datetime import timedelta
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    DELETE FROM metrics 
                    WHERE timestamp < ?
                """, (cutoff_time,))
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    LOG.info(f"Cleaned up {deleted_count} old metrics (older than {days_to_keep} days)")
                
                return deleted_count
        except Exception as e:
            LOG.error(f"Failed to cleanup old metrics: {e}")
            return 0
    
    def get_metrics_for_date_range(self, firewall_name: str, start_date: str,
                                  end_date: str) -> List[Dict[str, Any]]:
        """Get metrics for a specific date range (YYYY-MM-DD format)"""
        try:
            start_dt = parse_iso_datetime(f"{start_date}T00:00:00+00:00")
            end_dt = parse_iso_datetime(f"{end_date}T23:59:59+00:00")
            return self.get_metrics(firewall_name, start_dt, end_dt)
        except Exception as e:
            LOG.error(f"Failed to get metrics for date range: {e}")
            return []
    
    def export_metrics_to_dict(self, firewall_name: str, start_time: Optional[datetime] = None,
                              end_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Export enhanced metrics to dictionary format suitable for pandas/CSV"""
        metrics = self.get_metrics(firewall_name, start_time, end_time)
        
        # Convert timestamps to ISO format strings for export
        for metric in metrics:
            if 'timestamp' in metric and metric['timestamp']:
                if isinstance(metric['timestamp'], str):
                    # Already a string, ensure it's ISO format
                    try:
                        dt = parse_iso_datetime(metric['timestamp'])
                        metric['timestamp'] = dt.isoformat()
                    except:
                        pass  # Keep original if parsing fails
                else:
                    # Convert datetime to ISO string
                    metric['timestamp'] = metric['timestamp'].isoformat()
        
        return metrics
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get enhanced database statistics"""
        try:
            with self._get_connection() as conn:
                # Get total metrics count
                cursor = conn.execute("SELECT COUNT(*) as total_metrics FROM metrics")
                total_metrics = cursor.fetchone()['total_metrics']
                
                # Get metrics per firewall
                cursor = conn.execute("""
                    SELECT firewall_name, COUNT(*) as count 
                    FROM metrics 
                    GROUP BY firewall_name
                """)
                firewall_counts = {row['firewall_name']: row['count'] for row in cursor.fetchall()}
                
                # Get date range
                cursor = conn.execute("""
                    SELECT MIN(timestamp) as earliest, MAX(timestamp) as latest 
                    FROM metrics
                """)
                date_range = cursor.fetchone()
                
                # Get enhanced sampling statistics
                cursor = conn.execute("""
                    SELECT 
                        AVG(session_sample_count) as avg_samples,
                        AVG(session_success_rate) as avg_success_rate,
                        AVG(session_sampling_period) as avg_sampling_period
                    FROM metrics 
                    WHERE session_sample_count IS NOT NULL
                """)
                sampling_stats = cursor.fetchone()
                
                # Get database file size
                db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
                
                stats = {
                    'total_metrics': total_metrics,
                    'firewall_counts': firewall_counts,
                    'earliest_metric': date_range['earliest'],
                    'latest_metric': date_range['latest'],
                    'database_size_bytes': db_size,
                    'database_size_mb': round(db_size / (1024 * 1024), 2)
                }
                
                # Add enhanced sampling statistics if available
                if sampling_stats and sampling_stats['avg_samples']:
                    stats.update({
                        'avg_samples_per_poll': round(sampling_stats['avg_samples'] or 0, 1),
                        'avg_success_rate_percent': round((sampling_stats['avg_success_rate'] or 0) * 100, 1),
                        'avg_sampling_period_seconds': round(sampling_stats['avg_sampling_period'] or 0, 1),
                        'enhanced_statistics_available': True
                    })
                else:
                    stats['enhanced_statistics_available'] = False
                
                return stats
        except Exception as e:
            LOG.error(f"Failed to get enhanced database stats: {e}")
            return {}
    
    def set_config_value(self, key: str, value: Any):
        """Store a configuration value"""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO configuration (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (key, json.dumps(value)))
                conn.commit()
        except Exception as e:
            LOG.error(f"Failed to set config value {key}: {e}")
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Retrieve a configuration value"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT value FROM configuration WHERE key = ?
                """, (key,))
                row = cursor.fetchone()
                if row:
                    return json.loads(row['value'])
                return default
        except Exception as e:
            LOG.error(f"Failed to get config value {key}: {e}")
            return default

# Database utility functions
def create_database(db_path: str) -> MetricsDatabase:
    """Create and initialize a new metrics database"""
    return MetricsDatabase(db_path)

def migrate_csv_to_database(csv_file: str, db: MetricsDatabase, firewall_name: str):
    """Migrate existing CSV data to database"""
    try:
        import pandas as pd
        
        df = pd.read_csv(csv_file)
        LOG.info(f"Migrating {len(df)} records from {csv_file} to database")
        
        # Register firewall first
        db.register_firewall(firewall_name, "migrated_from_csv")
        
        # Convert and insert each row
        for _, row in df.iterrows():
            metrics = row.to_dict()
            db.insert_metrics(firewall_name, metrics)
        
        LOG.info(f"Successfully migrated {len(df)} records for {firewall_name}")
        
    except Exception as e:
        LOG.error(f"Failed to migrate CSV to database: {e}")

if __name__ == "__main__":
    # Example usage demonstrating automatic migration
    db = MetricsDatabase("test_enhanced_metrics.db")
    
    # Register a firewall
    db.register_firewall("test_fw", "https://192.168.1.1")
    
    # Insert enhanced test metrics
    import time
    for i in range(3):
        enhanced_metrics = {
            'timestamp': datetime.now(timezone.utc),
            'cpu_user': 10.0 + i,
            'cpu_system': 5.0 + i,
            'mgmt_cpu': 15.0 + i,
            'data_plane_cpu': 20.0 + i,
            'data_plane_cpu_mean': 20.0 + i,
            'data_plane_cpu_max': 25.0 + i * 2,
            'data_plane_cpu_p95': 23.0 + i * 1.5,
            'throughput_mbps_total': 100.0 + i * 10,
            'throughput_mbps_max': 150.0 + i * 15,     # Enhanced
            'throughput_mbps_min': 50.0 + i * 5,       # Enhanced
            'throughput_mbps_p95': 130.0 + i * 12,     # Enhanced
            'pps_total': 1000 + i * 100,
            'pps_max': 1500 + i * 150,                 # Enhanced
            'pps_min': 500 + i * 50,                   # Enhanced
            'pps_p95': 1300 + i * 130,                 # Enhanced
            'session_sample_count': 30,                # Enhanced
            'session_success_rate': 0.95,              # Enhanced
            'session_sampling_period': 30.0,           # Enhanced
            'pbuf_util_percent': 2.0 + i * 0.5
        }
        db.insert_metrics("test_fw", enhanced_metrics)
        time.sleep(1)
    
    # Retrieve and display enhanced metrics
    metrics = db.get_latest_metrics("test_fw", 3)
    print(f"📊 Retrieved {len(metrics)} enhanced metrics")
    
    if metrics:
        latest = metrics[0]
        print("🚀 Latest Enhanced Metrics Sample:")
        print(f"   Throughput: mean={latest.get('throughput_mbps_total', 'N/A')}, "
              f"max={latest.get('throughput_mbps_max', 'N/A')}, "
              f"p95={latest.get('throughput_mbps_p95', 'N/A')} Mbps")
        print(f"   PPS: mean={latest.get('pps_total', 'N/A')}, "
              f"max={latest.get('pps_max', 'N/A')}, "
              f"p95={latest.get('pps_p95', 'N/A')}")
        print(f"   Sample Quality: {latest.get('session_sample_count', 'N/A')} samples, "
              f"{(latest.get('session_success_rate', 0) * 100):.1f}% success")
    
    # Get enhanced summary
    summary = db.get_firewall_summary("test_fw")
    print(f"📈 Enhanced Summary: {summary}")
    
    # Get enhanced database stats
    stats = db.get_database_stats()
    print(f"🗄️  Enhanced Database Stats: {stats}")
