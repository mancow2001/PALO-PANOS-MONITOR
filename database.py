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
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from contextlib import contextmanager
from queue import Queue, Empty

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

        # Connection pooling to reduce overhead from creating/destroying connections
        # SQLite doesn't have true pooling, but we can reuse connections per thread
        self._connection_pool = Queue(maxsize=10)  # Pool of 10 reusable connections
        self._pool_lock = threading.Lock()
        self._thread_local = threading.local()

        LOG.info(f"🔧 Initializing database at: {self.db_path}")
        self._init_database()
        LOG.info(f"✅ Database ready with connection pooling at: {self.db_path}")
    
    def _init_database(self):
        """Initialize database schema with automatic migration"""
        with self._get_connection() as conn:
            # Create firewalls table FIRST (before metrics table due to foreign key)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS firewalls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    host TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            LOG.info("✓ Firewalls table created/verified")
            
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
            LOG.info("✓ Metrics table created/verified")
            
            # Create indexes for better query performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_firewall_timestamp 
                ON metrics (firewall_name, timestamp)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_timestamp 
                ON metrics (timestamp)
            """)
            LOG.info("✓ Metrics indexes created/verified")
            
            # Create configuration table for storing runtime config
            conn.execute("""
                CREATE TABLE IF NOT EXISTS configuration (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            LOG.info("✓ Configuration table created/verified")
            
            conn.commit()
            
            # Verify critical tables exist
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='firewalls'")
            if not cursor.fetchone():
                LOG.error("❌ CRITICAL: Firewalls table was not created!")
                raise RuntimeError("Failed to create firewalls table")
            
            LOG.info("✅ Core database tables initialized")
        
        # Automatically migrate schema to add enhanced statistics and interface monitoring
        self._migrate_schema()
        
        LOG.info(f"Enhanced database initialized with interface monitoring: {self.db_path}")
    
    def _migrate_schema(self):
        """Automatically detect schema changes and migrate database"""
        with self._get_connection() as conn:
            # Check what columns currently exist in metrics table
            cursor = conn.execute("PRAGMA table_info(metrics)")
            existing_columns = [row[1] for row in cursor.fetchall()]
            
            # Define columns that should be REMOVED (no longer collected)
            obsolete_columns = [
                'throughput_mbps_total',      # Session-based throughput (replaced by interface metrics)
                'throughput_mbps_max',        # Session-based throughput max
                'throughput_mbps_min',        # Session-based throughput min
                'throughput_mbps_p95',        # Session-based throughput p95
                'pps_total',                  # Session-based PPS (replaced by interface metrics)
                'pps_max',                    # Session-based PPS max
                'pps_min',                    # Session-based PPS min
                'pps_p95',                    # Session-based PPS p95
                'session_sample_count',       # Session sampling metadata
                'session_success_rate',       # Session sampling metadata
                'session_sampling_period',    # Session sampling metadata
            ]
            
            # Check if any obsolete columns exist
            columns_to_remove = [col for col in obsolete_columns if col in existing_columns]
            
            if columns_to_remove:
                LOG.info(f"🔍 Schema migration: Detected {len(columns_to_remove)} obsolete columns (no longer collected)")
                LOG.info(f"   Removing session-based throughput columns (now using interface-based monitoring)")
                
                # SQLite doesn't support DROP COLUMN easily, so we need to recreate the table
                # Get the columns we want to keep
                columns_to_keep = [col for col in existing_columns if col not in obsolete_columns]
                
                # Build the new table schema with only columns we want
                new_columns_def = []
                cursor = conn.execute("PRAGMA table_info(metrics)")
                for row in cursor.fetchall():
                    col_name = row[1]
                    if col_name in columns_to_keep:
                        col_type = row[2]
                        not_null = " NOT NULL" if row[3] else ""
                        default = f" DEFAULT {row[4]}" if row[4] is not None else ""
                        pk = " PRIMARY KEY AUTOINCREMENT" if row[5] else ""
                        new_columns_def.append(f"{col_name} {col_type}{not_null}{default}{pk}")
                
                # Add foreign key constraint
                if 'firewall_name' in columns_to_keep:
                    new_columns_def.append("FOREIGN KEY (firewall_name) REFERENCES firewalls (name)")
                
                try:
                    # Create new table with updated schema
                    conn.execute(f"""
                        CREATE TABLE metrics_new (
                            {', '.join(new_columns_def)}
                        )
                    """)
                    
                    # Copy data from old table to new table
                    columns_str = ', '.join(columns_to_keep)
                    conn.execute(f"""
                        INSERT INTO metrics_new ({columns_str})
                        SELECT {columns_str} FROM metrics
                    """)
                    
                    # Drop old table
                    conn.execute("DROP TABLE metrics")
                    
                    # Rename new table
                    conn.execute("ALTER TABLE metrics_new RENAME TO metrics")
                    
                    # Recreate indexes
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_metrics_firewall_timestamp 
                        ON metrics (firewall_name, timestamp)
                    """)
                    
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_metrics_timestamp 
                        ON metrics (timestamp)
                    """)
                    
                    conn.commit()
                    
                    LOG.info(f"✅ Schema migration successful: Removed {len(columns_to_remove)} obsolete columns")
                    for col in columns_to_remove:
                        LOG.info(f"   ✓ Removed: {col}")
                    LOG.info(f"📈 Throughput now tracked via interface_metrics table (more accurate)")
                    
                except Exception as e:
                    LOG.error(f"❌ Schema migration failed: {e}")
                    conn.rollback()
                    LOG.warning("   Database rolled back to previous state")
                    LOG.warning("   Obsolete columns will remain but won't receive new data")
            else:
                LOG.debug("✅ Schema is up-to-date: No obsolete columns found")

            # Migrate firewalls table to add hardware info columns
            cursor = conn.execute("PRAGMA table_info(firewalls)")
            firewall_columns = [row[1] for row in cursor.fetchall()]

            hardware_columns = {
                'model': 'TEXT',
                'family': 'TEXT',
                'platform_family': 'TEXT',
                'serial': 'TEXT',
                'hostname': 'TEXT',
                'sw_version': 'TEXT'
            }

            for col_name, col_type in hardware_columns.items():
                if col_name not in firewall_columns:
                    try:
                        conn.execute(f"ALTER TABLE firewalls ADD COLUMN {col_name} {col_type}")
                        LOG.info(f"✅ Added {col_name} column to firewalls table")
                    except Exception as e:
                        LOG.warning(f"Could not add {col_name} column: {e}")

            conn.commit()

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

            # Additional optimized indexes for common query patterns
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_interface_metrics_firewall_timestamp
                ON interface_metrics (firewall_name, timestamp DESC)
            """)

            # Note: Partial indexes with datetime() are not supported in all SQLite versions
            # Removed partial indexes to ensure compatibility

            # Create indexes for session statistics
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_statistics_firewall_timestamp
                ON session_statistics (firewall_name, timestamp)
            """)
            
            # Commit all changes
            conn.commit()
            
            # Check if new tables were created
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('interface_metrics', 'session_statistics')")
            new_tables = [row[0] for row in cursor.fetchall()]
            
            if new_tables:
                LOG.info(f"📊 Interface monitoring tables ready: {', '.join(new_tables)}")
            else:
                LOG.debug("✅ Interface monitoring tables already exist")
    
    @contextmanager
    def _get_connection(self):
        """
        Context manager for database connections with pooling
        Reuses connections from pool to reduce overhead
        """
        conn = None
        from_pool = False

        try:
            # Try to get connection from pool (non-blocking)
            try:
                conn = self._connection_pool.get_nowait()
                from_pool = True
                LOG.debug(f"Reusing connection from pool (pool size: {self._connection_pool.qsize()})")
            except Empty:
                # Pool is empty, create new connection
                conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                LOG.debug("Created new database connection")

            yield conn

        finally:
            if conn:
                try:
                    # Return connection to pool if possible (and it's healthy)
                    if from_pool or self._connection_pool.qsize() < 10:
                        # Reset any uncommitted transactions
                        try:
                            conn.rollback()
                        except:
                            pass
                        # Try to return to pool
                        try:
                            self._connection_pool.put_nowait(conn)
                            LOG.debug(f"Returned connection to pool (pool size: {self._connection_pool.qsize()})")
                        except:
                            # Pool is full, close this connection
                            conn.close()
                            LOG.debug("Pool full, closed excess connection")
                    else:
                        # Pool is full, close connection
                        conn.close()
                        LOG.debug("Closed database connection (pool full)")
                except Exception as e:
                    LOG.debug(f"Error managing connection: {e}")
                    try:
                        conn.close()
                    except:
                        pass
    
    def register_firewall(self, name: str, host: str, hardware_info: Optional[Dict[str, str]] = None) -> bool:
        """
        Register a firewall in the database with optional hardware information

        Args:
            name: Firewall name
            host: Firewall host/IP
            hardware_info: Optional dict with model, family, serial, etc.
        """
        try:
            with self._get_connection() as conn:
                if hardware_info:
                    # Store hardware info if provided
                    conn.execute("""
                        INSERT OR REPLACE INTO firewalls
                        (name, host, model, family, platform_family, serial, hostname, sw_version, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        name,
                        host,
                        hardware_info.get('model'),
                        hardware_info.get('family'),
                        hardware_info.get('platform_family'),
                        hardware_info.get('serial'),
                        hardware_info.get('hostname'),
                        hardware_info.get('sw_version')
                    ))
                    model_info = f" [Model: {hardware_info.get('model', 'unknown')}]" if hardware_info.get('model') else ""
                    LOG.info(f"Registered firewall: {name} ({host}){model_info}")
                else:
                    # Just update name and host
                    conn.execute("""
                        INSERT OR REPLACE INTO firewalls (name, host, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """, (name, host))
                    LOG.info(f"Registered firewall: {name} ({host})")
                conn.commit()
                return True
        except Exception as e:
            LOG.error(f"Failed to register firewall {name}: {e}")
            return False
    
    def insert_metrics(self, firewall_name: str, metrics: Dict[str, Any]) -> bool:
        """Insert enhanced metrics data for a firewall"""
        try:
            # Auto-register firewall if metrics include host information
            if 'firewall_host' in metrics:
                self.register_firewall(firewall_name, metrics['firewall_host'])
            
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
                
                # Only insert columns that are present in current schema
                # These obsolete columns are no longer used after migration
                conn.execute("""
                    INSERT INTO metrics (
                        firewall_name, timestamp, cpu_user, cpu_system, cpu_idle,
                        mgmt_cpu, data_plane_cpu, data_plane_cpu_mean, data_plane_cpu_max, 
                        data_plane_cpu_p95, pbuf_util_percent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            # Auto-register firewall if metrics include host information
            if 'firewall_host' in interface_metrics:
                self.register_firewall(firewall_name, interface_metrics['firewall_host'])
            
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
            # Auto-register firewall if metrics include host information
            if 'firewall_host' in session_stats:
                self.register_firewall(firewall_name, session_stats['firewall_host'])
            
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

    def get_interface_metrics_batch(self, firewall_name: str, interface_names: List[str],
                                   start_time: Optional[datetime] = None,
                                   end_time: Optional[datetime] = None,
                                   limit: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get interface metrics for multiple interfaces in a single query (fixes N+1 problem)
        Returns dict mapping interface_name to list of metrics
        """
        if not interface_names:
            return {}

        try:
            with self._get_connection() as conn:
                # Build query with IN clause for multiple interfaces
                placeholders = ','.join('?' * len(interface_names))
                query = f"""
                    SELECT * FROM interface_metrics
                    WHERE firewall_name = ?
                    AND interface_name IN ({placeholders})
                """
                params = [firewall_name] + list(interface_names)

                if start_time:
                    query += " AND timestamp >= ?"
                    params.append(start_time)

                if end_time:
                    query += " AND timestamp <= ?"
                    params.append(end_time)

                # FIXED: Apply limit PER interface, not globally
                # Strategy: Fetch all matching rows, then limit per interface in Python
                # This ensures each interface gets up to 'limit' data points

                query += " ORDER BY interface_name, timestamp DESC"

                cursor = conn.execute(query, params)
                rows = cursor.fetchall()

                # Group results by interface_name and apply per-interface limit
                result = {}
                for row in rows:
                    row_dict = dict(row)
                    iface = row_dict['interface_name']
                    if iface not in result:
                        result[iface] = []

                    # Apply limit PER interface (e.g., 500 points per interface, not 500 total)
                    if limit is None or len(result[iface]) < limit:
                        result[iface].append(row_dict)

                LOG.info(f"Batch query fetched data for {len(result)} interfaces (up to {limit or 'all'} points per interface)")
                if limit:
                    total_points = sum(len(points) for points in result.values())
                    LOG.debug(f"Returned {total_points} total data points across {len(result)} interfaces")

                return result

        except Exception as e:
            LOG.error(f"Failed to get interface metrics batch for {firewall_name}: {e}")
            return {}

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

    def get_latest_interface_summary(self, firewall_name: str, interface_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get latest metrics for multiple interfaces in a single query (fixes N+1 problem for dashboard)
        Returns dict mapping interface_name to latest metrics
        """
        if not interface_names:
            return {}

        try:
            with self._get_connection() as conn:
                # Build query with IN clause and get latest record per interface
                placeholders = ','.join('?' * len(interface_names))
                query = f"""
                    SELECT im.*
                    FROM interface_metrics im
                    INNER JOIN (
                        SELECT interface_name, MAX(timestamp) as max_timestamp
                        FROM interface_metrics
                        WHERE firewall_name = ? AND interface_name IN ({placeholders})
                        GROUP BY interface_name
                    ) latest ON im.interface_name = latest.interface_name
                              AND im.timestamp = latest.max_timestamp
                    WHERE im.firewall_name = ?
                """
                params = [firewall_name] + list(interface_names) + [firewall_name]

                cursor = conn.execute(query, params)
                rows = cursor.fetchall()

                # Map interface_name to metrics
                result = {}
                for row in rows:
                    row_dict = dict(row)
                    result[row_dict['interface_name']] = row_dict

                LOG.debug(f"Fetched latest metrics for {len(result)} interfaces in single query")
                return result

        except Exception as e:
            LOG.error(f"Failed to get latest interface summary for {firewall_name}: {e}")
            return {}
    
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
        """Get list of all registered firewalls with hardware info"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT f.name, f.host, f.created_at, f.updated_at,
                           f.model, f.family, f.platform_family, f.serial,
                           f.hostname, f.sw_version,
                           COUNT(m.id) as metric_count,
                           MAX(m.timestamp) as last_metric_time
                    FROM firewalls f
                    LEFT JOIN metrics m ON f.name = m.firewall_name
                    GROUP BY f.name, f.host, f.created_at, f.updated_at,
                             f.model, f.family, f.platform_family, f.serial,
                             f.hostname, f.sw_version
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
