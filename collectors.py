#!/usr/bin/env python3
"""
Enhanced Data Collection with Interface Monitoring for PAN-OS Multi-Firewall Monitor
Integrates interface bandwidth monitoring and session tracking alongside existing metrics
"""
import time
import logging
import xml.etree.ElementTree as ET
import re
import glob
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any
from threading import Thread, Event, Lock
from queue import Queue
from dataclasses import dataclass, field
import statistics

import requests
from requests.exceptions import RequestException
import urllib3

# Import our interface monitoring module
from interface_monitor import (
    InterfaceMonitor, InterfaceConfig,
    parse_interface_statistics, parse_session_statistics
)

# Suppress TLS warnings when verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOG = logging.getLogger("panos_monitor.enhanced_collectors")

@dataclass
class CollectionResult:
    """Result of a metrics collection attempt"""
    success: bool
    firewall_name: str
    metrics: Optional[Dict[str, Any]] = None
    interface_metrics: Optional[Dict[str, List[Any]]] = None
    session_stats: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: Optional[datetime] = None

@dataclass
class SessionInfoSample:
    """Single session info sample with timestamp"""
    timestamp: datetime
    kbps: float
    pps: float
    success: bool
    error: Optional[str] = None

@dataclass
class SessionInfoAggregates:
    """Aggregated session info over sampling period"""
    sample_count: int = 0
    kbps_samples: List[float] = field(default_factory=list)
    pps_samples: List[float] = field(default_factory=list)
    kbps_mean: float = 0.0
    kbps_max: float = 0.0
    kbps_min: float = 0.0
    kbps_p95: float = 0.0
    pps_mean: float = 0.0
    pps_max: float = 0.0
    pps_min: float = 0.0
    pps_p95: float = 0.0
    sampling_period: float = 0.0
    success_rate: float = 0.0

def create_default_interface_configs() -> List[InterfaceConfig]:
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

class PanOSClient:
    """PAN-OS API client for a single firewall"""
    
    def __init__(self, host: str, verify_ssl: bool = True):
        self.base = host.rstrip("/")
        if not self.base.startswith("http"):
            self.base = "https://" + self.base
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.api_key: Optional[str] = None
        self.last_error: Optional[str] = None

    def keygen(self, username: str, password: str) -> bool:
        """Generate API key and return success status"""
        url = f"{self.base}/api/"
        try:
            resp = self.session.get(
                url,
                params={"type": "keygen", "user": username, "password": password},
                timeout=20
            )
            resp.raise_for_status()
            
            root = ET.fromstring(resp.text)
            key = root.findtext("result/key")
            if not key:
                self.last_error = f"Key not found in keygen response: {resp.text[:400]}..."
                return False
                
            self.api_key = key
            self.last_error = None
            return True
            
        except RequestException as e:
            self.last_error = f"Keygen HTTP error: {e}"
            return False
        except Exception as e:
            self.last_error = f"Keygen parse error: {e}"
            return False

    def op(self, xml_cmd: str, timeout: int = 30) -> Optional[str]:
        """Execute operational command and return XML response"""
        if not self.api_key:
            self.last_error = "API key not set; call keygen() first"
            return None
            
        url = f"{self.base}/api/"
        params = {"type": "op", "cmd": xml_cmd, "key": self.api_key}
        
        try:
            resp = self.session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            self.last_error = None
            return resp.text
            
        except RequestException as e:
            self.last_error = f"API request error: {e}"
            return None
        except Exception as e:
            self.last_error = f"Unexpected error: {e}"
            return None

    def op_fast(self, xml_cmd: str) -> Optional[str]:
        """Execute operational command with shorter timeout for frequent polling"""
        return self.op(xml_cmd, timeout=5)

    def request(self, xml_cmd: str) -> Optional[str]:
        """Execute request command and return XML response"""
        if not self.api_key:
            self.last_error = "API key not set; call keygen() first"
            return None
            
        url = f"{self.base}/api/"
        params = {"type": "op", "cmd": xml_cmd, "key": self.api_key}
        
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            self.last_error = None
            return resp.text
            
        except RequestException as e:
            self.last_error = f"API request error: {e}"
            return None
        except Exception as e:
            self.last_error = f"Unexpected error: {e}"
            return None

# Include all existing parsing functions from the original collectors.py
# (parse_cpu_from_debug_status, parse_dp_cpu_from_rm, etc.)

def _numbers_from_csv(text: str) -> List[float]:
    """Extract numbers from comma-separated text"""
    nums: List[float] = []
    for x in (text or "").split(","):
        xs = x.strip()
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", xs or ""):
            nums.append(float(xs))
    return nums

def _aggregate(values: List[float], mode: str = "mean") -> float:
    """Aggregate list of values using specified mode"""
    if not values:
        return 0.0
    mode = (mode or "mean").lower()
    if mode == "max":
        return max(values)
    if mode == "min":
        return min(values)
    if mode == "p95":
        return calculate_percentile(values, 0.95)
    return sum(values) / len(values)

def calculate_percentile(values: List[float], percentile: float) -> float:
    """Calculate percentile - Python 3.6 compatible version"""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    
    # Calculate index for the percentile
    index = (len(sorted_values) - 1) * percentile
    lower_index = int(index)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    
    if lower_index == upper_index:
        return sorted_values[lower_index]
    
    # Linear interpolation
    weight = index - lower_index
    return sorted_values[lower_index] * (1 - weight) + sorted_values[upper_index] * weight

def parse_cpu_from_debug_status(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Parse management CPU from debug status - most accurate method"""
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        
        # Look for the mp-cpu-utilization field
        mp_cpu = root.findtext(".//mp-cpu-utilization")
        if mp_cpu:
            try:
                cpu_percent = float(mp_cpu)
                out.update({
                    "mgmt_cpu": cpu_percent,
                    "mgmt_cpu_debug": cpu_percent
                })
                return out, f"cpu: debug status {cpu_percent}%"
            except ValueError:
                pass
        
        return {}, "cpu: no mp-cpu-utilization in debug status"
    except Exception as e:
        return {}, f"cpu parse error from debug status: {e}"

def parse_dp_cpu_from_rm(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Parse data plane CPU from resource monitor - collect all aggregation methods"""
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        per_core_latest: List[float] = []
        
        # Get CPU load maximum values for all cores
        for node in root.findall(".//data-processors/*/minute/cpu-load-maximum/entry/value"):
            arr = _numbers_from_csv(node.text or "")
            if not arr:
                continue
            newest = arr[0]
            
            # Check if values are fractional (0.0-1.0) and convert to percentage
            has_decimals = any(v != int(v) for v in arr if v > 0)
            if has_decimals and max(arr) <= 1.0:
                newest *= 100.0
                
            per_core_latest.append(newest)

        # Calculate all three aggregation methods
        if per_core_latest:
            out["data_plane_cpu_mean"] = _aggregate(per_core_latest, "mean")
            out["data_plane_cpu_max"] = _aggregate(per_core_latest, "max")
            out["data_plane_cpu_p95"] = _aggregate(per_core_latest, "p95")
            
            # Keep the original field for backward compatibility (defaults to mean)
            out["data_plane_cpu"] = out["data_plane_cpu_mean"]
        else:
            out["data_plane_cpu_mean"] = 0.0
            out["data_plane_cpu_max"] = 0.0
            out["data_plane_cpu_p95"] = 0.0
            out["data_plane_cpu"] = 0.0

        return out, f"dp-cpu cores={len(per_core_latest)} (collected mean/max/p95)"
    except Exception as e:
        return {}, f"dp-cpu parse error: {e}"

def parse_pbuf_live_from_rm(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Parse packet buffer utilization from resource monitor"""
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        latest_vals: List[float] = []
        
        # Get packet buffer maximum values
        for e in root.findall(".//data-processors/*/minute/resource-utilization/entry"):
            name = (e.findtext("name") or "").lower()
            if "packet buffer (maximum)" in name:
                arr = _numbers_from_csv(e.findtext("value") or "")
                if arr:
                    latest_vals.append(arr[0])
                    
        out["pbuf_util_percent"] = _aggregate(latest_vals, "mean")
        return out, f"pbuf live groups={len(latest_vals)}"
    except Exception as e:
        return {}, f"pbuf parse error: {e}"

def parse_throughput_from_session_info(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Parse throughput and PPS from session info - single sample"""
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        kbps = root.findtext(".//result/kbps")
        pps = root.findtext(".//result/pps")
        
        if kbps is not None:
            try:
                out["kbps"] = float(kbps)
                out["throughput_mbps"] = float(kbps) / 1000.0
            except ValueError:
                pass
                
        if pps is not None:
            try:
                out["pps"] = float(pps)
            except ValueError:
                pass
                
        return out, "throughput: parsed session info"
    except Exception as e:
        return {}, f"throughput parse error: {e}"

def aggregate_session_info_samples(samples: List[SessionInfoSample]) -> SessionInfoAggregates:
    """Aggregate per-second session info samples into statistics"""
    if not samples:
        return SessionInfoAggregates()
    
    successful_samples = [s for s in samples if s.success]
    
    if not successful_samples:
        return SessionInfoAggregates(
            sample_count=len(samples),
            success_rate=0.0,
            sampling_period=(samples[-1].timestamp - samples[0].timestamp).total_seconds()
        )
    
    kbps_values = [s.kbps for s in successful_samples]
    pps_values = [s.pps for s in successful_samples]
    
    aggregates = SessionInfoAggregates(
        sample_count=len(samples),
        kbps_samples=kbps_values,
        pps_samples=pps_values,
        success_rate=len(successful_samples) / len(samples),
        sampling_period=(samples[-1].timestamp - samples[0].timestamp).total_seconds()
    )
    
    if kbps_values:
        aggregates.kbps_mean = statistics.mean(kbps_values)
        aggregates.kbps_max = max(kbps_values)
        aggregates.kbps_min = min(kbps_values)
        aggregates.kbps_p95 = calculate_percentile(kbps_values, 0.95)
    
    if pps_values:
        aggregates.pps_mean = statistics.mean(pps_values)
        aggregates.pps_max = max(pps_values)
        aggregates.pps_min = min(pps_values)
        aggregates.pps_p95 = calculate_percentile(pps_values, 0.95)
    
    return aggregates

class SessionInfoSampler:
    """Per-second session info sampler for a single firewall"""
    
    def __init__(self, name: str, client: PanOSClient):
        self.name = name
        self.client = client
        self.running = False
        self.samples: List[SessionInfoSample] = []
        self.samples_lock = Lock()
        self.thread: Optional[Thread] = None
        self.stop_event = Event()
        
    def start_sampling(self):
        """Start per-second sampling"""
        if self.running:
            return
        
        self.running = True
        self.stop_event.clear()
        self.thread = Thread(
            target=self._sampling_worker,
            daemon=True,
            name=f"session-sampler-{self.name}"
        )
        self.thread.start()
        LOG.debug(f"{self.name}: Started session info sampling")
    
    def stop_sampling(self):
        """Stop per-second sampling"""
        if not self.running:
            return
        
        self.running = False
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        LOG.debug(f"{self.name}: Stopped session info sampling")
    
    def _sampling_worker(self):
        """Worker thread for per-second session info sampling"""
        while not self.stop_event.is_set():
            start_time = time.time()
            timestamp = datetime.now(timezone.utc)
            
            # Sample session info
            xml = self.client.op_fast("<show><session><info/></session></show>")
            
            if xml:
                metrics, msg = parse_throughput_from_session_info(xml)
                if metrics and "kbps" in metrics and "pps" in metrics:
                    sample = SessionInfoSample(
                        timestamp=timestamp,
                        kbps=metrics["kbps"],
                        pps=metrics["pps"],
                        success=True
                    )
                else:
                    sample = SessionInfoSample(
                        timestamp=timestamp,
                        kbps=0.0,
                        pps=0.0,
                        success=False,
                        error="Failed to parse session info"
                    )
            else:
                sample = SessionInfoSample(
                    timestamp=timestamp,
                    kbps=0.0,
                    pps=0.0,
                    success=False,
                    error=self.client.last_error
                )
            
            # Store sample with thread safety
            with self.samples_lock:
                self.samples.append(sample)
                # Keep only recent samples (last 5 minutes worth)
                cutoff_time = timestamp - timedelta(minutes=5)
                self.samples = [s for s in self.samples if s.timestamp > cutoff_time]
            
            # Sleep for remaining time to maintain 1-second intervals
            elapsed = time.time() - start_time
            sleep_time = max(0, 1.0 - elapsed)
            if sleep_time > 0:
                self.stop_event.wait(sleep_time)
    
    def get_samples_since(self, since_time: datetime) -> List[SessionInfoSample]:
        """Get all samples since the given time"""
        with self.samples_lock:
            return [s for s in self.samples if s.timestamp >= since_time]

class EnhancedFirewallCollector:
    """Enhanced collector with interface monitoring and session tracking"""
    
    def __init__(self, name: str, config, output_dir: Path, global_config=None):
        self.name = name
        self.config = config
        self.global_config = global_config
        self.client = PanOSClient(config.host, config.verify_ssl)
        self.output_dir = output_dir
        self.xml_dir = output_dir / "raw_xml" / name
        self.xml_dir.mkdir(parents=True, exist_ok=True)
        self.authenticated = False
        self.last_poll_time = None
        self.poll_count = 0
        
        # Session info sampler (existing functionality)
        self.session_sampler = SessionInfoSampler(name, self.client)
        self.last_collection_time = datetime.now(timezone.utc)
        
        # NEW: Interface monitoring
        interface_configs = getattr(config, 'interface_configs', None)
        if not interface_configs:
            # Use default interface configs if not specified
            interface_configs = create_default_interface_configs()
        
        self.interface_monitor = InterfaceMonitor(name, self.client, config)
        
        LOG.info(f"{self.name}: Enhanced collector initialized with interface monitoring")
        
    def authenticate(self) -> bool:
        """Authenticate with the firewall"""
        success = self.client.keygen(self.config.username, self.config.password)
        if success:
            self.authenticated = True
            # Start session sampling after authentication
            self.session_sampler.start_sampling()
            
            # NEW: Start interface monitoring
            self.interface_monitor.start_monitoring()
            
            LOG.info(f"Successfully authenticated with {self.name} and started enhanced monitoring")
        else:
            LOG.error(f"Failed to authenticate with {self.name}: {self.client.last_error}")
        return success
    
    def _save_raw_xml(self, name: str, content: str):
        """Save raw XML response for debugging"""
        if not self.global_config or not getattr(self.global_config, 'save_raw_xml', False):
            return
        
        if content and ('status="error"' in content or 'code="17"' in content):
            LOG.debug(f"{self.name}: Skipping save of error response for {name}")
            return
            
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_path = self.xml_dir / f"{ts}_{name}.xml"
        try:
            file_path.write_text(content, encoding="utf-8")
            LOG.debug(f"Saved raw XML to {file_path}")
        except Exception as e:
            LOG.warning(f"Failed to save XML for {self.name}: {e}")
    
    def collect_management_cpu_enhanced(self) -> Dict[str, float]:
        """Collect Management CPU using enhanced method with fallback"""
        cpu_metrics = {}
        
        # Method 1: Debug status (most accurate - matches GUI)
        try:
            xml = self.client.request("<request><s><debug><status/></debug></s></request>")
            if xml:
                self._save_raw_xml("debug_status", xml)
                metrics, msg = parse_cpu_from_debug_status(xml)
                if metrics:
                    cpu_metrics.update(metrics)
                    LOG.debug(f"{self.name}: {msg}")
                    return cpu_metrics
            else:
                LOG.debug(f"{self.name}: Debug status failed: {self.client.last_error}")
        except Exception as e:
            LOG.debug(f"{self.name}: Debug status CPU failed: {e}")
        
        LOG.warning(f"{self.name}: All CPU monitoring methods failed")
        return {}
    
    def collect_session_info_aggregated(self) -> Dict[str, float]:
        """Collect aggregated session info from per-second samples"""
        current_time = datetime.now(timezone.utc)
        
        # Get samples since last collection
        samples = self.session_sampler.get_samples_since(self.last_collection_time)
        
        if not samples:
            LOG.warning(f"{self.name}: No session info samples available for aggregation")
            return {}
        
        # Aggregate the samples
        aggregates = aggregate_session_info_samples(samples)
        
        # Convert to enhanced metrics dictionary
        metrics = {
            # Original metrics (backward compatibility)
            "throughput_mbps_total": aggregates.kbps_mean / 1000.0,
            "pps_total": aggregates.pps_mean,
            
            # Enhanced throughput statistics
            "throughput_mbps_max": aggregates.kbps_max / 1000.0,
            "throughput_mbps_min": aggregates.kbps_min / 1000.0,
            "throughput_mbps_p95": aggregates.kbps_p95 / 1000.0,
            
            # Enhanced PPS statistics
            "pps_max": aggregates.pps_max,
            "pps_min": aggregates.pps_min,
            "pps_p95": aggregates.pps_p95,
            
            # Sampling metadata
            "session_sample_count": aggregates.sample_count,
            "session_success_rate": aggregates.success_rate,
            "session_sampling_period": aggregates.sampling_period
        }
        
        # Update last collection time
        self.last_collection_time = current_time
        
        return metrics

    def collect_metrics(self) -> CollectionResult:
        """Enhanced metrics collection including interface and session data"""
        if not self.authenticated:
            if not self.authenticate():
                return CollectionResult(
                    success=False,
                    firewall_name=self.name,
                    error="Authentication failed"
                )
        
        metrics = {}
        interface_metrics = {}
        session_stats = {}
        timestamp = datetime.now(timezone.utc)
        self.poll_count += 1
        
        # Enhanced Management CPU collection
        cpu_metrics = self.collect_management_cpu_enhanced()
        metrics.update(cpu_metrics)
        
        # Data plane CPU and packet buffer
        try:
            xml = self.client.op("<show><running><resource-monitor><minute></minute></resource-monitor></running></show>")
            if xml:
                self._save_raw_xml("resource_monitor", xml)
                
                # DP CPU
                d, msg = parse_dp_cpu_from_rm(xml)
                metrics.update({k: v for k, v in d.items() if v is not None})
                LOG.debug(f"{self.name}: {msg}")
                
                # Packet buffer
                d2, msg2 = parse_pbuf_live_from_rm(xml)
                metrics.update({k: v for k, v in d2.items() if v is not None})
                LOG.debug(f"{self.name}: {msg2}")
            else:
                LOG.warning(f"{self.name}: Failed to get resource monitor: {self.client.last_error}")
        except Exception as e:
            LOG.warning(f"{self.name}: Resource monitor error: {e}")
        
        # Aggregated session info (existing session-based throughput)
        try:
            session_metrics = self.collect_session_info_aggregated()
            metrics.update(session_metrics)
        except Exception as e:
            LOG.warning(f"{self.name}: Session info aggregation error: {e}")
        
        # NEW: Collect interface metrics
        try:
            available_interfaces = self.interface_monitor.get_available_interfaces()
            for interface_name in available_interfaces:
                latest_metrics = self.interface_monitor.get_latest_interface_metrics(interface_name)
                if latest_metrics:
                    interface_metrics[interface_name] = {
                        'timestamp': timestamp.isoformat(),
                        'interface_name': interface_name,
                        'rx_mbps': latest_metrics.rx_mbps,
                        'tx_mbps': latest_metrics.tx_mbps,
                        'total_mbps': latest_metrics.total_mbps,
                        'rx_pps': latest_metrics.rx_pps,
                        'tx_pps': latest_metrics.tx_pps,
                        'interval_seconds': latest_metrics.interval_seconds
                    }
        except Exception as e:
            LOG.warning(f"{self.name}: Interface metrics collection error: {e}")
        
        # NEW: Collect session statistics
        try:
            latest_session_stats = self.interface_monitor.get_latest_session_stats()
            if latest_session_stats:
                session_stats = {
                    'timestamp': timestamp.isoformat(),
                    'active_sessions': latest_session_stats.active_sessions,
                    'max_sessions': latest_session_stats.max_sessions,
                    'tcp_sessions': latest_session_stats.tcp_sessions,
                    'udp_sessions': latest_session_stats.udp_sessions,
                    'icmp_sessions': latest_session_stats.icmp_sessions,
                    'session_rate': latest_session_stats.session_rate
                }
        except Exception as e:
            LOG.warning(f"{self.name}: Session statistics collection error: {e}")
        
        # Add timestamp and firewall name
        metrics["timestamp"] = timestamp.isoformat()
        metrics["firewall_name"] = self.name
        
        self.last_poll_time = timestamp
        
        return CollectionResult(
            success=True,
            firewall_name=self.name,
            metrics=metrics,
            interface_metrics=interface_metrics,
            session_stats=session_stats,
            timestamp=timestamp
        )
    
    def stop(self):
        """Stop the collector and all monitoring"""
        self.session_sampler.stop_sampling()
        self.interface_monitor.stop_monitoring()

class EnhancedMultiFirewallCollector:
    """Enhanced collector manager with interface monitoring"""
    
    def __init__(self, firewall_configs: Dict, output_dir: Path, database, global_config=None):
        self.firewall_configs = firewall_configs
        self.output_dir = output_dir
        self.database = database
        self.global_config = global_config
        self.collectors: Dict[str, EnhancedFirewallCollector] = {}
        self.collection_threads: Dict[str, Thread] = {}
        self.stop_events: Dict[str, Event] = {}
        self.metrics_queue = Queue()
        self.running = False
        
        # Initialize enhanced collectors
        for name, config in firewall_configs.items():
            if config.enabled:
                self.collectors[name] = EnhancedFirewallCollector(name, config, output_dir, global_config)
                self.stop_events[name] = Event()
                # Register firewall in database
                self.database.register_firewall(name, config.host)
    
    def start_collection(self):
        """Start collection threads for all enabled firewalls"""
        if self.running:
            LOG.warning("Collection is already running")
            return
        
        self.running = True
        LOG.info(f"Starting enhanced collection for {len(self.collectors)} firewalls")
        
        # Start collection thread for each firewall
        for name, collector in self.collectors.items():
            thread = Thread(
                target=self._collection_worker,
                args=(name, collector, self.stop_events[name]),
                daemon=True,
                name=f"enhanced-collector-{name}"
            )
            thread.start()
            self.collection_threads[name] = thread
        
        # Start metrics processing thread
        self.metrics_thread = Thread(
            target=self._enhanced_metrics_processor,
            daemon=True,
            name="enhanced-metrics-processor"
        )
        self.metrics_thread.start()
        
        LOG.info("All enhanced collection threads started with interface monitoring")
    
    def stop_collection(self):
        """Stop all collection threads"""
        if not self.running:
            return
        
        LOG.info("Stopping enhanced collection threads...")
        self.running = False
        
        # Stop collectors
        for collector in self.collectors.values():
            collector.stop()
        
        # Signal all threads to stop
        for stop_event in self.stop_events.values():
            stop_event.set()
        
        # Wait for threads to finish
        for name, thread in self.collection_threads.items():
            if thread.is_alive():
                thread.join(timeout=5)
                if thread.is_alive():
                    LOG.warning(f"Thread {name} did not stop gracefully")
        
        # Wait for metrics processor
        if hasattr(self, 'metrics_thread') and self.metrics_thread.is_alive():
            self.metrics_thread.join(timeout=5)
        
        LOG.info("All enhanced collection threads stopped")
    
    def _collection_worker(self, name: str, collector: EnhancedFirewallCollector, stop_event: Event):
        """Worker thread for collecting enhanced metrics from a single firewall"""
        config = self.firewall_configs[name]
        interval = config.poll_interval
        
        LOG.info(f"Started enhanced collection worker for {name} (interval: {interval}s)")
        
        while not stop_event.is_set():
            start_time = time.time()
            
            try:
                result = collector.collect_metrics()
                self.metrics_queue.put(result)
                
                if result.success:
                    LOG.debug(f"{name}: Enhanced metrics collected successfully")
                else:
                    LOG.warning(f"{name}: Collection failed - {result.error}")
                    
            except Exception as e:
                LOG.error(f"{name}: Unexpected error in enhanced collection: {e}")
                result = CollectionResult(
                    success=False,
                    firewall_name=name,
                    error=str(e)
                )
                self.metrics_queue.put(result)
            
            # Sleep for remaining interval time
            elapsed = time.time() - start_time
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                stop_event.wait(sleep_time)
        
        LOG.info(f"Enhanced collection worker for {name} stopped")
    
    def _enhanced_metrics_processor(self):
        """Process collected metrics and store in enhanced database"""
        LOG.info("Started enhanced metrics processor")
        
        while self.running:
            try:
                try:
                    result = self.metrics_queue.get(timeout=1.0)
                except:
                    continue
                
                if result.success:
                    # Store main metrics
                    if result.metrics:
                        success = self.database.insert_metrics(result.firewall_name, result.metrics)
                        if success:
                            LOG.debug(f"Stored metrics for {result.firewall_name}")
                        else:
                            LOG.error(f"Failed to store metrics for {result.firewall_name}")
                    
                    # NEW: Store interface metrics
                    if result.interface_metrics and hasattr(self.database, 'insert_interface_metrics'):
                        for interface_name, interface_data in result.interface_metrics.items():
                            success = self.database.insert_interface_metrics(result.firewall_name, interface_data)
                            if success:
                                LOG.debug(f"Stored interface metrics for {result.firewall_name}:{interface_name}")
                            else:
                                LOG.error(f"Failed to store interface metrics for {result.firewall_name}:{interface_name}")
                    
                    # NEW: Store session statistics
                    if result.session_stats and hasattr(self.database, 'insert_session_statistics'):
                        success = self.database.insert_session_statistics(result.firewall_name, result.session_stats)
                        if success:
                            LOG.debug(f"Stored session statistics for {result.firewall_name}")
                        else:
                            LOG.error(f"Failed to store session statistics for {result.firewall_name}")
                            
                else:
                    LOG.warning(f"Skipping failed collection for {result.firewall_name}: {result.error}")
                
                self.metrics_queue.task_done()
                
            except Exception as e:
                LOG.error(f"Error in enhanced metrics processor: {e}")
        
        LOG.info("Enhanced metrics processor stopped")
    
    def get_collector_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all enhanced collectors"""
        status = {}
        for name, collector in self.collectors.items():
            # Get basic collector status
            basic_status = {
                'authenticated': collector.authenticated,
                'last_poll': collector.last_poll_time.isoformat() if collector.last_poll_time else None,
                'poll_count': collector.poll_count,
                'thread_alive': self.collection_threads.get(name, Thread()).is_alive(),
                'config': {
                    'host': collector.config.host,
                    'interval': collector.config.poll_interval,
                    'enabled': collector.config.enabled
                }
            }
            
            # Add session sampler status
            samples_count = 0
            last_sample_time = None
            with collector.session_sampler.samples_lock:
                samples_count = len(collector.session_sampler.samples)
                if collector.session_sampler.samples:
                    last_sample_time = collector.session_sampler.samples[-1].timestamp.isoformat()
            
            basic_status.update({
                'session_sampler_running': collector.session_sampler.running,
                'session_samples_count': samples_count,
                'last_session_sample': last_sample_time
            })
            
            # NEW: Add interface monitoring status
            available_interfaces = collector.interface_monitor.get_available_interfaces()
            basic_status.update({
                'interface_monitor_running': collector.interface_monitor.running,
                'available_interfaces': available_interfaces,
                'interface_count': len(available_interfaces)
            })
            
            status[name] = basic_status
            
        return status

# Maintain backward compatibility
class FirewallCollector(EnhancedFirewallCollector):
    """Backward compatibility alias"""
    pass

class MultiFirewallCollector(EnhancedMultiFirewallCollector):
    """Backward compatibility alias"""
    pass

if __name__ == "__main__":
    # Example usage
    print("Enhanced collectors with interface monitoring ready")
    print("Features:")
    print("- Existing session-based throughput monitoring")
    print("- NEW: Accurate interface bandwidth tracking")
    print("- NEW: Session statistics monitoring")
    print("- Backward compatible with existing code")
