#!/usr/bin/env python3
"""
Interface Monitoring for PAN-OS Multi-Firewall Monitor
Provides accurate bandwidth calculation from interface statistics and session tracking
Uses delta calculations like SolarWinds for precise throughput measurement
"""
import time
import logging
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from threading import Thread, Event, Lock
from dataclasses import dataclass, field

LOG = logging.getLogger("panos_monitor.interface_monitor")

@dataclass
class InterfaceConfig:
    """Configuration for monitoring a specific interface"""
    name: str
    display_name: str
    enabled: bool = True
    description: str = ""

@dataclass
class InterfaceSample:
    """Single interface statistics sample"""
    timestamp: datetime
    interface_name: str
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    rx_errors: int = 0
    tx_errors: int = 0
    success: bool = True
    error: Optional[str] = None

@dataclass
class InterfaceMetrics:
    """Calculated interface metrics between two samples"""
    interface_name: str
    interval_seconds: float
    rx_bps: float  # bits per second
    tx_bps: float  # bits per second
    rx_mbps: float  # Mbps
    tx_mbps: float  # Mbps
    rx_pps: float  # packets per second
    tx_pps: float  # packets per second
    utilization_percent: float = 0.0  # if interface speed is known
    total_mbps: float = 0.0  # combined rx + tx

@dataclass
class SessionStats:
    """Session statistics from firewall"""
    timestamp: datetime
    active_sessions: int
    max_sessions: int
    tcp_sessions: int = 0
    udp_sessions: int = 0
    icmp_sessions: int = 0
    session_rate: float = 0.0  # sessions/second
    success: bool = True
    error: Optional[str] = None

def parse_interface_statistics(xml_text: str) -> Dict[str, InterfaceSample]:
    """
    Parse interface statistics from PAN-OS
    Uses: <show><interface>all</interface></show>
    """
    interfaces = {}
    timestamp = datetime.now(timezone.utc)
    
    try:
        root = ET.fromstring(xml_text)
        
        # Look for interface entries
        for interface in root.findall(".//entry"):
            name_elem = interface.find("name")
            if name_elem is None:
                continue
                
            interface_name = name_elem.text
            if not interface_name:
                continue
            
            # Skip management interfaces and unwanted types
            if interface_name.startswith(("mgmt", "loopback", "tunnel")):
                continue
            
            # Get counters
            counters = interface.find("counters")
            if counters is None:
                continue
            
            try:
                rx_bytes = int(counters.findtext("ibytes", "0"))
                tx_bytes = int(counters.findtext("obytes", "0"))
                rx_packets = int(counters.findtext("ipackets", "0"))
                tx_packets = int(counters.findtext("opackets", "0"))
                rx_errors = int(counters.findtext("ierrors", "0"))
                tx_errors = int(counters.findtext("oerrors", "0"))
                
                interfaces[interface_name] = InterfaceSample(
                    timestamp=timestamp,
                    interface_name=interface_name,
                    rx_bytes=rx_bytes,
                    tx_bytes=tx_bytes,
                    rx_packets=rx_packets,
                    tx_packets=tx_packets,
                    rx_errors=rx_errors,
                    tx_errors=tx_errors,
                    success=True
                )
                
            except (ValueError, AttributeError) as e:
                LOG.debug(f"Failed to parse counters for interface {interface_name}: {e}")
                continue
        
        return interfaces
        
    except Exception as e:
        LOG.error(f"Failed to parse interface statistics: {e}")
        return {}

def parse_session_statistics(xml_text: str) -> Optional[SessionStats]:
    """
    Parse session statistics from PAN-OS
    Uses: <show><session><info/></session></show>
    """
    timestamp = datetime.now(timezone.utc)
    
    try:
        root = ET.fromstring(xml_text)
        
        # Get session counts
        num_active = root.findtext(".//result/num-active")
        num_max = root.findtext(".//result/num-max")
        
        # Get detailed session info if available
        tcp_sessions = 0
        udp_sessions = 0
        icmp_sessions = 0
        session_rate = 0.0
        
        # Try to parse additional session details
        for entry in root.findall(".//entry"):
            proto = entry.findtext("proto", "").lower()
            if proto == "tcp":
                tcp_sessions += 1
            elif proto == "udp":
                udp_sessions += 1
            elif proto == "icmp":
                icmp_sessions += 1
        
        # Parse session rate if available
        rate_elem = root.findtext(".//result/pps")
        if rate_elem:
            try:
                session_rate = float(rate_elem)
            except ValueError:
                pass
        
        if num_active is not None and num_max is not None:
            return SessionStats(
                timestamp=timestamp,
                active_sessions=int(num_active),
                max_sessions=int(num_max),
                tcp_sessions=tcp_sessions,
                udp_sessions=udp_sessions,
                icmp_sessions=icmp_sessions,
                session_rate=session_rate,
                success=True
            )
        
        return None
        
    except Exception as e:
        LOG.error(f"Failed to parse session statistics: {e}")
        return SessionStats(
            timestamp=timestamp,
            active_sessions=0,
            max_sessions=0,
            success=False,
            error=str(e)
        )

def calculate_interface_metrics(prev_sample: InterfaceSample,
                              curr_sample: InterfaceSample) -> Optional[InterfaceMetrics]:
    """Calculate bandwidth metrics between two interface samples"""
    if prev_sample.interface_name != curr_sample.interface_name:
        return None
    
    # Calculate time interval
    interval = (curr_sample.timestamp - prev_sample.timestamp).total_seconds()
    if interval <= 0:
        return None
    
    # Calculate byte deltas (handle counter wraps)
    rx_delta = curr_sample.rx_bytes - prev_sample.rx_bytes
    tx_delta = curr_sample.tx_bytes - prev_sample.tx_bytes
    rx_pkt_delta = curr_sample.rx_packets - prev_sample.rx_packets
    tx_pkt_delta = curr_sample.tx_packets - prev_sample.tx_packets
    
    # Handle counter wraps (assume 32-bit counters)
    if rx_delta < 0:
        rx_delta += 2**32
    if tx_delta < 0:
        tx_delta += 2**32
    if rx_pkt_delta < 0:
        rx_pkt_delta += 2**32
    if tx_pkt_delta < 0:
        tx_pkt_delta += 2**32
    
    # Calculate rates
    rx_bps = (rx_delta * 8) / interval  # Convert bytes to bits
    tx_bps = (tx_delta * 8) / interval
    rx_mbps = rx_bps / (1000 * 1000)   # Convert to Mbps
    tx_mbps = tx_bps / (1000 * 1000)
    rx_pps = rx_pkt_delta / interval
    tx_pps = tx_pkt_delta / interval
    
    total_mbps = rx_mbps + tx_mbps
    
    return InterfaceMetrics(
        interface_name=curr_sample.interface_name,
        interval_seconds=interval,
        rx_bps=rx_bps,
        tx_bps=tx_bps,
        rx_mbps=rx_mbps,
        tx_mbps=tx_mbps,
        rx_pps=rx_pps,
        tx_pps=tx_pps,
        total_mbps=total_mbps
    )

class InterfaceMonitor:
    """Interface and session monitoring for a single firewall"""
    
    def __init__(self, name: str, client, firewall_config=None):
        self.name = name
        self.client = client
        self.firewall_config = firewall_config
        self.running = False
        self.thread: Optional[Thread] = None
        self.stop_event = Event()
        
        # Initialize interface configuration
        if firewall_config:
            self.interface_configs = {cfg.name: cfg for cfg in create_interface_configs_from_firewall_config(firewall_config)}
            self.auto_discover = getattr(firewall_config, 'auto_discover_interfaces', False)
            self.exclude_patterns = getattr(firewall_config, 'exclude_interfaces', ['mgmt', 'loopback', 'tunnel'])
        else:
            # Fallback to default configs
            default_configs = self._create_default_interface_configs()
            self.interface_configs = {cfg.name: cfg for cfg in default_configs}
            self.auto_discover = True
            self.exclude_patterns = ['mgmt', 'loopback', 'tunnel']
        
        # Data storage with locks
        self.interface_samples: Dict[str, List[InterfaceSample]] = {}
        self.interface_metrics: Dict[str, List[InterfaceMetrics]] = {}
        self.session_stats: List[SessionStats] = []
        self.data_lock = Lock()
        
        # Discovered interfaces (for auto-discovery)
        self.discovered_interfaces: Set[str] = set()
        
        # Sampling interval
        self.sample_interval = 30  # seconds
    
    def _create_default_interface_configs(self) -> List[InterfaceConfig]:
        """Create default interface configurations for common PAN-OS interfaces"""
        return [
            InterfaceConfig(
                name="ethernet1/1",
                display_name="Internet/WAN",
                description="Primary internet connection"
            ),
            InterfaceConfig(
                name="ethernet1/2",
                display_name="LAN/Internal",
                description="Internal network connection"
            ),
            InterfaceConfig(
                name="ethernet1/3",
                display_name="DMZ",
                description="DMZ network connection"
            ),
            InterfaceConfig(
                name="ae1",
                display_name="Aggregate 1",
                description="Link aggregation group 1",
                enabled=False  # Disabled by default for auto-discovery
            ),
            InterfaceConfig(
                name="ae2",
                display_name="Aggregate 2",
                description="Link aggregation group 2",
                enabled=False  # Disabled by default for auto-discovery
            )
        ]
    
    def _should_monitor_interface(self, interface_name: str) -> bool:
        """Determine if an interface should be monitored"""
        # Check exclusion patterns first
        for pattern in self.exclude_patterns:
            if pattern.lower() in interface_name.lower():
                return False
        
        # If we have firewall config, use its logic
        if self.firewall_config and hasattr(self.firewall_config, 'should_monitor_interface'):
            return self.firewall_config.should_monitor_interface(interface_name)
        
        # If explicitly configured, check if enabled
        if interface_name in self.interface_configs:
            return self.interface_configs[interface_name].enabled
        
        # If auto-discovery enabled and not excluded, monitor it
        if self.auto_discover:
            return True
        
        return False
    
    def _auto_discover_interfaces(self, available_interfaces: Dict[str, InterfaceSample]):
        """Auto-discover new interfaces and add them to monitoring"""
        if not self.auto_discover:
            return
        
        for interface_name in available_interfaces.keys():
            if interface_name not in self.discovered_interfaces:
                if self._should_monitor_interface(interface_name):
                    # Add to discovered interfaces
                    self.discovered_interfaces.add(interface_name)
                    
                    # Create interface config if not exists
                    if interface_name not in self.interface_configs:
                        display_name = self._generate_display_name(interface_name)
                        self.interface_configs[interface_name] = InterfaceConfig(
                            name=interface_name,
                            display_name=display_name,
                            enabled=True,
                            description=f"Auto-discovered interface {interface_name}"
                        )
                        
                        LOG.info(f"{self.name}: Auto-discovered interface {interface_name} ({display_name})")
    
    def _generate_display_name(self, interface_name: str) -> str:
        """Generate a user-friendly display name from interface name"""
        name = interface_name.lower()
        
        # Common interface type mappings
        if name.startswith("ethernet1/1"):
            return "WAN/Internet"
        elif name.startswith("ethernet1/2"):
            return "LAN/Internal"
        elif name.startswith("ethernet1/3"):
            return "DMZ"
        elif name.startswith("ethernet"):
            # Extract port number
            port = name.replace("ethernet", "").replace("1/", "Port ")
            return f"Port {port}"
        elif name.startswith("ae"):
            # Aggregate interface
            agg_num = name.replace("ae", "")
            return f"Aggregate {agg_num}"
        elif name.startswith("vlan"):
            # VLAN interface
            vlan_num = name.replace("vlan", "")
            return f"VLAN {vlan_num}"
        elif name.startswith("tunnel"):
            return f"Tunnel {name.replace('tunnel.', '')}"
        else:
            # Capitalize first letter for unknown interfaces
            return interface_name.capitalize()
    
    def start_monitoring(self):
        """Start interface and session monitoring"""
        if self.running:
            return
        
        self.running = True
        self.stop_event.clear()
        self.thread = Thread(
            target=self._monitoring_worker,
            daemon=True,
            name=f"interface-monitor-{self.name}"
        )
        self.thread.start()
        LOG.info(f"{self.name}: Started interface monitoring for {len(self.interface_configs)} interfaces")
    
    def stop_monitoring(self):
        """Stop interface and session monitoring"""
        if not self.running:
            return
        
        self.running = False
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        LOG.info(f"{self.name}: Stopped interface monitoring")
    
    def _monitoring_worker(self):
        """Worker thread for interface and session monitoring"""
        while not self.stop_event.is_set():
            start_time = time.time()
            
            # Collect interface statistics
            self._collect_interface_stats()
            
            # Collect session statistics
            self._collect_session_stats()
            
            # Sleep for remaining interval time
            elapsed = time.time() - start_time
            sleep_time = max(0, self.sample_interval - elapsed)
            if sleep_time > 0:
                self.stop_event.wait(sleep_time)
    
    def _collect_interface_stats(self):
        """Collect interface statistics"""
        try:
            xml = self.client.op("<show><interface>all</interface></show>")
            if not xml:
                LOG.warning(f"{self.name}: Failed to get interface statistics")
                return
            
            current_samples = parse_interface_statistics(xml)
            
            with self.data_lock:
                for interface_name, sample in current_samples.items():
                    # Only monitor configured interfaces
                    if interface_name not in self.interface_configs:
                        continue
                    
                    # Store sample
                    if interface_name not in self.interface_samples:
                        self.interface_samples[interface_name] = []
                    self.interface_samples[interface_name].append(sample)
                    
                    # Calculate metrics if we have a previous sample
                    samples = self.interface_samples[interface_name]
                    if len(samples) >= 2:
                        prev_sample = samples[-2]
                        metrics = calculate_interface_metrics(prev_sample, sample)
                        
                        if metrics:
                            if interface_name not in self.interface_metrics:
                                self.interface_metrics[interface_name] = []
                            self.interface_metrics[interface_name].append(metrics)
                            
                            LOG.debug(f"{self.name}: {interface_name} - "
                                    f"RX: {metrics.rx_mbps:.2f} Mbps, "
                                    f"TX: {metrics.tx_mbps:.2f} Mbps")
                    
                    # Keep only recent samples (last 24 hours)
                    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                    self.interface_samples[interface_name] = [
                        s for s in self.interface_samples[interface_name]
                        if s.timestamp > cutoff_time
                    ]
                    
                    if interface_name in self.interface_metrics:
                        # Keep metrics for same time period
                        self.interface_metrics[interface_name] = [
                            m for m in self.interface_metrics[interface_name]
                            if len([s for s in self.interface_samples[interface_name]
                                   if s.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24)]) > 0
                        ]
            
        except Exception as e:
            LOG.error(f"{self.name}: Interface collection error: {e}")
    
    def _collect_session_stats(self):
        """Collect session statistics"""
        try:
            xml = self.client.op("<show><session><info/></session></show>")
            if not xml:
                LOG.warning(f"{self.name}: Failed to get session statistics")
                return
            
            session_stats = parse_session_statistics(xml)
            if session_stats:
                with self.data_lock:
                    self.session_stats.append(session_stats)
                    
                    # Keep only recent stats (last 24 hours)
                    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                    self.session_stats = [
                        s for s in self.session_stats if s.timestamp > cutoff_time
                    ]
                    
                    LOG.debug(f"{self.name}: Sessions - Active: {session_stats.active_sessions}, "
                             f"Max: {session_stats.max_sessions}")
            
        except Exception as e:
            LOG.error(f"{self.name}: Session collection error: {e}")
    
    def get_interface_metrics(self, interface_name: str,
                            start_time: Optional[datetime] = None,
                            end_time: Optional[datetime] = None) -> List[InterfaceMetrics]:
        """Get interface metrics for specified time range"""
        with self.data_lock:
            metrics = self.interface_metrics.get(interface_name, [])
            
            if start_time or end_time:
                filtered_metrics = []
                for metric in metrics:
                    # Find corresponding sample timestamp
                    samples = self.interface_samples.get(interface_name, [])
                    metric_sample = next((s for s in samples
                                        if s.interface_name == interface_name), None)
                    
                    if metric_sample:
                        timestamp = metric_sample.timestamp
                        if start_time and timestamp < start_time:
                            continue
                        if end_time and timestamp > end_time:
                            continue
                        filtered_metrics.append(metric)
                
                return filtered_metrics
            
            return metrics.copy()
    
    def get_session_stats(self, start_time: Optional[datetime] = None,
                         end_time: Optional[datetime] = None) -> List[SessionStats]:
        """Get session statistics for specified time range"""
        with self.data_lock:
            stats = self.session_stats.copy()
            
            if start_time or end_time:
                filtered_stats = []
                for stat in stats:
                    if start_time and stat.timestamp < start_time:
                        continue
                    if end_time and stat.timestamp > end_time:
                        continue
                    filtered_stats.append(stat)
                
                return filtered_stats
            
            return stats
    
    def get_available_interfaces(self) -> List[str]:
        """Get list of interfaces that have been discovered"""
        with self.data_lock:
            return list(self.interface_samples.keys())
    
    def get_latest_interface_metrics(self, interface_name: str) -> Optional[InterfaceMetrics]:
        """Get latest metrics for an interface"""
        with self.data_lock:
            metrics = self.interface_metrics.get(interface_name, [])
            return metrics[-1] if metrics else None
    
    def get_latest_session_stats(self) -> Optional[SessionStats]:
        """Get latest session statistics"""
        with self.data_lock:
            return self.session_stats[-1] if self.session_stats else None

def create_interface_configs_from_firewall_config(firewall_config) -> List[InterfaceConfig]:
    """Create interface configs from enhanced firewall configuration"""
    interface_configs = []
    
    # If we have detailed interface configs, use them
    if hasattr(firewall_config, 'interface_configs') and firewall_config.interface_configs:
        interface_configs.extend(firewall_config.interface_configs)
    
    # If we have simple monitor_interfaces list, convert to configs
    if hasattr(firewall_config, 'monitor_interfaces') and firewall_config.monitor_interfaces:
        for interface_name in firewall_config.monitor_interfaces:
            # Check if not already in interface_configs
            existing_names = [ic.name for ic in interface_configs]
            if interface_name not in existing_names:
                display_name = firewall_config._generate_display_name(interface_name) if hasattr(firewall_config, '_generate_display_name') else interface_name
                interface_configs.append(InterfaceConfig(
                    name=interface_name,
                    display_name=display_name,
                    enabled=True,
                    description=f"Monitored interface {interface_name}"
                ))
    
    return interface_configs

if __name__ == "__main__":
    # Example usage
    from collectors import PanOSClient
    
    # Create test client
    client = PanOSClient("https://192.168.1.1", verify_ssl=False)
    
    # Create interface configs
    interface_configs = create_default_interface_configs()
    
    # Create monitor
    monitor = InterfaceMonitor("test_fw", client, interface_configs)
    
    print("Interface monitoring test - this would run with real authentication")
    # monitor.start_monitoring()
    # time.sleep(60)
    # monitor.stop_monitoring()
