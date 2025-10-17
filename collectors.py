#!/usr/bin/env python3
"""
Data collection modules for PAN-OS Multi-Firewall Monitor
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
from threading import Thread, Event
from queue import Queue
from dataclasses import dataclass

import requests
from requests.exceptions import RequestException
import urllib3

# Suppress TLS warnings when verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOG = logging.getLogger("panos_monitor.collectors")

@dataclass
class CollectionResult:
    """Result of a metrics collection attempt"""
    success: bool
    firewall_name: str
    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: Optional[datetime] = None

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

    def op(self, xml_cmd: str) -> Optional[str]:
        """Execute operational command and return XML response"""
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
    if mode == "p95":
        import math
        s = sorted(values)
        idx = max(0, min(len(s)-1, math.ceil(0.95*len(s))-1))
        return s[idx]
    return sum(values) / len(values)

def parse_cpu_from_top(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Parse management CPU from top CDATA"""
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        raw = root.findtext("result") or "".join(root.itertext())
        if not raw:
            return {}, "cpu: no result text"
        
        text = raw.replace("\r", "").replace("\n", " ")
        m = re.search(
            r"%?Cpu\(s\)[^0-9]*([0-9.]+)\s*us[, ]+\s*([0-9.]+)\s*sy[, ]+.*?([0-9.]+)\s*id",
            text, re.IGNORECASE
        )
        if m:
            usr, sy, idle = map(float, m.groups())
            out.update({
                "cpu_user": usr,
                "cpu_system": sy,
                "cpu_idle": idle,
                "mgmt_cpu": usr + sy
            })
            return out, "cpu: parsed top"
        return {}, "cpu: pattern not found"
    except Exception as e:
        return {}, f"cpu parse error: {e}"

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
    """Parse throughput and PPS from session info"""
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        kbps = root.findtext(".//result/kbps")
        pps = root.findtext(".//result/pps")
        
        if kbps is not None:
            try:
                out["throughput_mbps_total"] = float(kbps) / 1000.0
            except ValueError:
                pass
                
        if pps is not None:
            try:
                out["pps_total"] = float(pps)
            except ValueError:
                pass
                
        return out, "throughput: parsed session info"
    except Exception as e:
        return {}, f"throughput parse error: {e}"

def cleanup_old_xml_files(xml_dir: Path, retention_hours: int):
    """Remove XML files older than retention_hours"""
    if not xml_dir.exists() or retention_hours <= 0:
        return
    
    cutoff_time = datetime.now() - timedelta(hours=retention_hours)
    pattern = str(xml_dir / "*.xml")
    removed_count = 0
    
    for file_path in glob.glob(pattern):
        try:
            file_stat = os.stat(file_path)
            file_time = datetime.fromtimestamp(file_stat.st_mtime)
            if file_time < cutoff_time:
                os.remove(file_path)
                removed_count += 1
        except OSError as e:
            LOG.warning(f"Failed to remove old XML file {file_path}: {e}")
    
    if removed_count > 0:
        LOG.info(f"Cleaned up {removed_count} old XML files (older than {retention_hours}h)")

class FirewallCollector:
    """Collector for a single firewall"""
    
    def __init__(self, name: str, config, output_dir: Path):
        self.name = name
        self.config = config
        self.client = PanOSClient(config.host, config.verify_ssl)
        self.output_dir = output_dir
        self.xml_dir = output_dir / "raw_xml" / name
        self.xml_dir.mkdir(parents=True, exist_ok=True)
        self.authenticated = False
        self.last_poll_time = None
        self.poll_count = 0
        
    def authenticate(self) -> bool:
        """Authenticate with the firewall"""
        success = self.client.keygen(self.config.username, self.config.password)
        if success:
            self.authenticated = True
            LOG.info(f"Successfully authenticated with {self.name}")
        else:
            LOG.error(f"Failed to authenticate with {self.name}: {self.client.last_error}")
        return success
    
    def _save_raw_xml(self, name: str, content: str):
        """Save raw XML response for debugging"""
        if not getattr(self.config, 'save_raw_xml', False):
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_path = self.xml_dir / f"{ts}_{name}.xml"
        try:
            file_path.write_text(content, encoding="utf-8")
        except Exception as e:
            LOG.warning(f"Failed to save XML for {self.name}: {e}")
    
    def collect_metrics(self) -> CollectionResult:
        """Collect metrics from this firewall"""
        if not self.authenticated:
            if not self.authenticate():
                return CollectionResult(
                    success=False,
                    firewall_name=self.name,
                    error="Authentication failed"
                )
        
        metrics = {}
        timestamp = datetime.now(timezone.utc)
        self.poll_count += 1
        
        # Management CPU
        try:
            xml = self.client.op("<show><system><resources/></system></show>")
            if xml:
                self._save_raw_xml("system_resources", xml)
                d, msg = parse_cpu_from_top(xml)
                metrics.update(d)
            else:
                LOG.warning(f"{self.name}: Failed to get system resources: {self.client.last_error}")
        except Exception as e:
            LOG.warning(f"{self.name}: System resources error: {e}")
        
        # Data plane CPU and packet buffer
        try:
            xml = self.client.op("<show><running><resource-monitor><minute></minute></resource-monitor></running></show>")
            if xml:
                self._save_raw_xml("resource_monitor", xml)
                
                # DP CPU
                d, msg = parse_dp_cpu_from_rm(xml)
                metrics.update({k: v for k, v in d.items() if v is not None})
                
                # Packet buffer
                d2, msg2 = parse_pbuf_live_from_rm(xml)
                metrics.update({k: v for k, v in d2.items() if v is not None})
            else:
                LOG.warning(f"{self.name}: Failed to get resource monitor: {self.client.last_error}")
        except Exception as e:
            LOG.warning(f"{self.name}: Resource monitor error: {e}")
        
        # Throughput and PPS
        try:
            xml = self.client.op("<show><session><info/></session></show>")
            if xml:
                self._save_raw_xml("session_info", xml)
                d, msg = parse_throughput_from_session_info(xml)
                metrics.update({k: v for k, v in d.items() if v is not None})
            else:
                LOG.warning(f"{self.name}: Failed to get session info: {self.client.last_error}")
        except Exception as e:
            LOG.warning(f"{self.name}: Session info error: {e}")
        
        # Add timestamp and firewall name
        metrics["timestamp"] = timestamp.isoformat()
        metrics["firewall_name"] = self.name
        
        # Periodic XML cleanup
        if getattr(self.config, 'save_raw_xml', False) and self.poll_count % 10 == 0:
            cleanup_old_xml_files(self.xml_dir, getattr(self.config, 'xml_retention_hours', 24))
        
        self.last_poll_time = timestamp
        
        return CollectionResult(
            success=True,
            firewall_name=self.name,
            metrics=metrics,
            timestamp=timestamp
        )

class MultiFirewallCollector:
    """Manages collection from multiple firewalls"""
    
    def __init__(self, firewall_configs: Dict, output_dir: Path, database):
        self.firewall_configs = firewall_configs
        self.output_dir = output_dir
        self.database = database
        self.collectors: Dict[str, FirewallCollector] = {}
        self.collection_threads: Dict[str, Thread] = {}
        self.stop_events: Dict[str, Event] = {}
        self.metrics_queue = Queue()
        self.running = False
        
        # Initialize collectors
        for name, config in firewall_configs.items():
            if config.enabled:
                self.collectors[name] = FirewallCollector(name, config, output_dir)
                self.stop_events[name] = Event()
                # Register firewall in database
                self.database.register_firewall(name, config.host)
    
    def start_collection(self):
        """Start collection threads for all enabled firewalls"""
        if self.running:
            LOG.warning("Collection is already running")
            return
        
        self.running = True
        LOG.info(f"Starting collection for {len(self.collectors)} firewalls")
        
        # Start collection thread for each firewall
        for name, collector in self.collectors.items():
            thread = Thread(
                target=self._collection_worker,
                args=(name, collector, self.stop_events[name]),
                daemon=True,
                name=f"collector-{name}"
            )
            thread.start()
            self.collection_threads[name] = thread
        
        # Start metrics processing thread
        self.metrics_thread = Thread(
            target=self._metrics_processor,
            daemon=True,
            name="metrics-processor"
        )
        self.metrics_thread.start()
        
        LOG.info("All collection threads started")
    
    def stop_collection(self):
        """Stop all collection threads"""
        if not self.running:
            return
        
        LOG.info("Stopping collection threads...")
        self.running = False
        
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
        
        LOG.info("All collection threads stopped")
    
    def _collection_worker(self, name: str, collector: FirewallCollector, stop_event: Event):
        """Worker thread for collecting metrics from a single firewall"""
        config = self.firewall_configs[name]
        interval = config.poll_interval
        
        LOG.info(f"Started collection worker for {name} (interval: {interval}s)")
        
        while not stop_event.is_set():
            start_time = time.time()
            
            try:
                result = collector.collect_metrics()
                self.metrics_queue.put(result)
                
                if result.success:
                    LOG.debug(f"{name}: Metrics collected successfully")
                else:
                    LOG.warning(f"{name}: Collection failed - {result.error}")
                    
            except Exception as e:
                LOG.error(f"{name}: Unexpected error in collection: {e}")
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
        
        LOG.info(f"Collection worker for {name} stopped")
    
    def _metrics_processor(self):
        """Process collected metrics and store in database"""
        LOG.info("Started metrics processor")
        
        while self.running:
            try:
                # Get result from queue with timeout
                try:
                    result = self.metrics_queue.get(timeout=1.0)
                except:
                    continue  # Timeout, check if still running
                
                if result.success and result.metrics:
                    # Store in database
                    success = self.database.insert_metrics(result.firewall_name, result.metrics)
                    if success:
                        LOG.debug(f"Stored metrics for {result.firewall_name}")
                    else:
                        LOG.error(f"Failed to store metrics for {result.firewall_name}")
                else:
                    LOG.warning(f"Skipping failed collection for {result.firewall_name}: {result.error}")
                
                self.metrics_queue.task_done()
                
            except Exception as e:
                LOG.error(f"Error in metrics processor: {e}")
        
        LOG.info("Metrics processor stopped")
    
    def get_collector_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all collectors"""
        status = {}
        for name, collector in self.collectors.items():
            status[name] = {
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
        return status
    
    def get_latest_metrics(self, firewall_name: str, count: int = 100) -> List[Dict[str, Any]]:
        """Get latest metrics for a firewall from database"""
        return self.database.get_latest_metrics(firewall_name, count)
    
    def restart_collector(self, firewall_name: str) -> bool:
        """Restart a specific collector"""
        if firewall_name not in self.collectors:
            return False
        
        # Stop the specific thread
        if firewall_name in self.stop_events:
            self.stop_events[firewall_name].set()
        
        if firewall_name in self.collection_threads:
            thread = self.collection_threads[firewall_name]
            if thread.is_alive():
                thread.join(timeout=5)
        
        # Restart the thread
        self.stop_events[firewall_name] = Event()
        collector = self.collectors[firewall_name]
        
        thread = Thread(
            target=self._collection_worker,
            args=(firewall_name, collector, self.stop_events[firewall_name]),
            daemon=True,
            name=f"collector-{firewall_name}"
        )
        thread.start()
        self.collection_threads[firewall_name] = thread
        
        LOG.info(f"Restarted collector for {firewall_name}")
        return True

if __name__ == "__main__":
    # Example usage
    from config import FirewallConfig
    from database import MetricsDatabase
    
    # Create test configuration
    test_config = FirewallConfig(
        name="test_fw",
        host="https://192.168.1.1",
        username="admin",
        password="password",
        poll_interval=30
    )
    
    # Create database and collector
    db = MetricsDatabase("test.db")
    output_dir = Path("./test_output")
    output_dir.mkdir(exist_ok=True)
    
    collector = MultiFirewallCollector(
        {"test_fw": test_config},
        output_dir,
        db
    )
    
    print("Starting collection (this is just a test)")
    # collector.start_collection()
    # time.sleep(10)
    # collector.stop_collection()
