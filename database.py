#!/usr/bin/env python3
"""
Enhanced Database Management for PAN-OS Multi-Firewall Monitor
Provides persistent storage for metrics data, interface monitoring, and session statistics
Includes automatic schema migration for interface and session data
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

def parse_iso_datetime_python36(timestamp_str: str) -> datetime:
    """
    Parse ISO datetime string - Python 3.6 compatible version
    Python 3.6 doesn't have datetime.fromisoformat()
    """
    if not timestamp_str:
        return datetime.now(timezone.utc)
    
    # Remove 'Z' and replace with +00:00 for UTC
    if timestamp_str.endswith('Z'):
        timestamp_str = timestamp_str[:-1] + '+00:00'
    
    # Handle space instead of 'T' separator
    if ' ' in timestamp_str and 'T' not in timestamp_str:
        timestamp_str = timestamp_str.replace(' ', 'T', 1)
    
    # Try manual parsing for Python 3.6
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
            try:
                dt = datetime.strptime(timestamp_str.replace('T', ' '), '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                dt = datetime.strptime(timestamp_str.replace('T', ' '), '%Y-%m-%d %H:%M:%S')
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

# Use the Python 3.6 compatible function
parse_iso_datetime = parse_iso_datetime_python36

class EnhancedMetricsDatabase:
    """SQLite database for storing firewall metrics, interface data, and session statistics"""
    
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
        
        # Automatically migrate schema to add enhanced statistics and interface monitoring
        self._migrate_schema()
        
        LOG.info(f"Enhanced database initialized with interface monitoring: {self.db_path}")
    
    def _migrate_schema(self):
        """Automatically detect and add new columns for enhanced statistics and interface monitoring"""
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
            
            # Create interface metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interface_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firewall_name TEXT NOT NULL,
                    interface_name TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    rx_mbps REAL NOT NULL,
                    tx_mbps REAL NOT NULL,
                    total_mbps REAL NOT NULL,
                    rx_pps REAL NOT NULL,
                    tx_pps REAL NOT NULL,
                    interval_seconds REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (firewall_name) REFERENCES firewalls (name)
                )
            """)
            
            # Create session statistics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firewall_name TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    active_sessions INTEGER NOT NULL,
                    max_sessions INTEGER NOT NULL,
                    tcp_sessions INTEGER DEFAULT 0,
                    udp_sessions INTEGER DEFAULT 0,
                    icmp_sessions INTEGER DEFAULT 0,
                    session_rate REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (firewall_name) REFERENCES firewalls (name)
                )
            """)
            
            # Create indexes for interface metrics
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_interface_metrics_firewall_interface_timestamp 
                ON interface_metrics (firewall_name, interface_name, timestamp)
            """)
            
            # Create indexes for session statistics
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_statistics_firewall_timestamp 
                ON session_statistics (firewall_name, timestamp)
            """)
            
            # Commit all changes
            conn.commit()
            
            # Log migration summary
            if added_columns:
                LOG.info(f"🚀 Schema migration completed: Added {len(added_columns)} new columns for enhanced statistics")
                LOG.info(f"   New capabilities: Enhanced throughput and PPS tracking with min/max/P95 statistics")
            
            # Check if new tables were created
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('interface_metrics', 'session_statistics')")
            new_tables = [row[0] for row in cursor.fetchall()]
            
            if new_tables:
                LOG.info(f"📊 Interface monitoring tables created: {', '.join(new_tables)}")
                LOG.info(f"   New capabilities: Accurate interface bandwidth and session tracking")
            else:
                LOG.debug("✅ Interface monitoring tables already exist")
    
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
    
    def insert_interface_metrics(self, firewall_name: str, interface_metrics: Dict[str, Any]) -> bool:
        """Insert interface metrics data"""
        try:
            with self._get_connection() as conn:
                timestamp = interface_metrics.get('timestamp')
                if isinstance(timestamp, str):
                    timestamp = parse_iso_datetime(timestamp)
                elif timestamp is None:
                    timestamp = datetime.now(timezone.utc)
                elif isinstance(timestamp, datetime) and timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                
                conn.execute("""
                    INSERT INTO interface_metrics (
                        firewall_name, interface_name, timestamp, rx_mbps, tx_mbps,
                        total_mbps, rx_pps, tx_pps, interval_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    firewall_name,
                    interface_metrics.get('interface_name'),
                    timestamp,
                    interface_metrics.get('rx_mbps', 0),
                    interface_metrics.get('tx_mbps', 0),
                    interface_metrics.get('total_mbps', 0),
                    interface_metrics.get('rx_pps', 0),
                    interface_metrics.get('tx_pps', 0),
                    interface_metrics.get('interval_seconds', 0)
                ))
                conn.commit()
                return True
        except Exception as e:
            LOG.error(f"Failed to insert interface metrics for {firewall_name}: {e}")
            return False
    
    def insert_session_statistics(self, firewall_name: str, session_stats: Dict[str, Any]) -> bool:
        """Insert session statistics data"""
        try:
            with self._get_connection() as conn:
                timestamp = session_stats.get('timestamp')
                if isinstance(timestamp, str):
                    timestamp = parse_iso_datetime(timestamp)
                elif timestamp is None:
                    timestamp = datetime.now(timezone.utc)
                elif isinstance(timestamp, datetime) and timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                
                conn.execute("""
                    INSERT INTO session_statistics (
                        firewall_name, timestamp, active_sessions, max_sessions,
                        tcp_sessions, udp_sessions, icmp_sessions, session_rate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    firewall_name,
                    timestamp,
                    session_stats.get('active_sessions', 0),
                    session_stats.get('max_sessions', 0),
                    session_stats.get('tcp_sessions', 0),
                    session_stats.get('udp_sessions', 0),
                    session_stats.get('icmp_sessions', 0),
                    session_stats.get('session_rate', 0.0)
                ))
                conn.commit()
                return True
        except Exception as e:
            LOG.error(f"Failed to insert session statistics for {firewall_name}: {e}")
            return False
    
    def get_interface_metrics(self, firewall_name: str, interface_name: str = None,
                            start_time: Optional[datetime] = None,
                            end_time: Optional[datetime] = None,
                            limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get interface metrics for a firewall"""
        try:
            with self._get_connection() as conn:
                query = """
                    SELECT * FROM interface_metrics 
                    WHERE firewall_name = ?
                """
                params = [firewall_name]
                
                if interface_name:
                    query += " AND interface_name = ?"
                    params.append(interface_name)
                
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
                
                return [dict(row) for row in rows]
        except Exception as e:
            LOG.error(f"Failed to get interface metrics for {firewall_name}: {e}")
            return []
    
    def get_session_statistics(self, firewall_name: str,
                             start_time: Optional[datetime] = None,
                             end_time: Optional[datetime] = None,
                             limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get session statistics for a firewall"""
        try:
            with self._get_connection() as conn:
                query = """
                    SELECT * FROM session_statistics 
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
                
                return [dict(row) for row in rows]
        except Exception as e:
            LOG.error(f"Failed to get session statistics for {firewall_name}: {e}")
            return []
    
    def get_available_interfaces(self, firewall_name: str) -> List[str]:
        """Get list of available interfaces for a firewall"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT DISTINCT interface_name 
                    FROM interface_metrics 
                    WHERE firewall_name = ?
                    ORDER BY interface_name
                """, (firewall_name,))
                
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            LOG.error(f"Failed to get available interfaces for {firewall_name}: {e}")
            return []
    
    # Include all original methods from the base database class
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
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get enhanced database statistics including interface data"""
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
                
                # Get interface metrics count
                cursor = conn.execute("SELECT COUNT(*) as interface_metrics FROM interface_metrics")
                interface_metrics_count = cursor.fetchone()['interface_metrics']
                
                # Get session statistics count
                cursor = conn.execute("SELECT COUNT(*) as session_stats FROM session_statistics")
                session_stats_count = cursor.fetchone()['session_stats']
                
                # Get database file size
                db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
                
                stats = {
                    'total_metrics': total_metrics,
                    'interface_metrics_count': interface_metrics_count,
                    'session_statistics_count': session_stats_count,
                    'firewall_counts': firewall_counts,
                    'earliest_metric': date_range['earliest'],
                    'latest_metric': date_range['latest'],
                    'database_size_bytes': db_size,
                    'database_size_mb': round(db_size / (1024 * 1024), 2),
                    'enhanced_monitoring_available': True
                }
                
                return stats
        except Exception as e:
            LOG.error(f"Failed to get enhanced database stats: {e}")
            return {}
    
    def cleanup_old_metrics(self, days_to_keep: int = 30) -> int:
        """Remove metrics older than specified days from all tables"""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            total_deleted = 0
            
            with self._get_connection() as conn:
                # Clean main metrics
                cursor = conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff_time,))
                deleted_metrics = cursor.rowcount
                
                # Clean interface metrics
                cursor = conn.execute("DELETE FROM interface_metrics WHERE timestamp < ?", (cutoff_time,))
                deleted_interface = cursor.rowcount
                
                # Clean session statistics
                cursor = conn.execute("DELETE FROM session_statistics WHERE timestamp < ?", (cutoff_time,))
                deleted_sessions = cursor.rowcount
                
                conn.commit()
                
                total_deleted = deleted_metrics + deleted_interface + deleted_sessions
                
                if total_deleted > 0:
                    LOG.info(f"Cleaned up {deleted_metrics} metrics, {deleted_interface} interface records, "
                           f"{deleted_sessions} session records (older than {days_to_keep} days)")
                
                return total_deleted
        except Exception as e:
            LOG.error(f"Failed to cleanup old data: {e}")
            return 0
    
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

# Maintain backward compatibility
class MetricsDatabase(EnhancedMetricsDatabase):
    """Backward compatibility alias for the enhanced database"""
    pass

if __name__ == "__main__":
    # Example usage demonstrating interface monitoring
    db = EnhancedMetricsDatabase("test_enhanced_interface_metrics.db")
    
    # Register a firewall
    db.register_firewall("test_fw", "https://192.168.1.1")
    
    # Insert test interface metrics
    interface_data = {
        'interface_name': 'ethernet1/1',
        'timestamp': datetime.now(timezone.utc),
        'rx_mbps': 150.5,
        'tx_mbps': 75.2,
        'total_mbps': 225.7,
        'rx_pps': 25000,
        'tx_pps': 12500,
        'interval_seconds': 30.0
    }
    db.insert_interface_metrics("test_fw", interface_data)
    
    # Insert test session statistics
    session_data = {
        'timestamp': datetime.now(timezone.utc),
        'active_sessions': 15000,
        'max_sessions': 100000,
        'tcp_sessions': 12000,
        'udp_sessions': 2800,
        'icmp_sessions': 200,
        'session_rate': 150.0
    }
    db.insert_session_statistics("test_fw", session_data)
    
    # Get enhanced database stats
    stats = db.get_database_stats()
    print(f"📊 Enhanced Database Stats: {stats}")
    
    # Get interface metrics
    interface_metrics = db.get_interface_metrics("test_fw", "ethernet1/1")
    print(f"📈 Interface Metrics: {len(interface_metrics)} records")
    
    # Get session statistics
    session_stats = db.get_session_statistics("test_fw")
    print(f"🔗 Session Statistics: {len(session_stats)} records")
