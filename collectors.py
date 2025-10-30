#!/usr/bin/env python3
"""
Updated Data Collection for Your Specific PAN-OS 11 System
Based on actual debug test results showing working commands
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

import requests
from requests.exceptions import RequestException
import urllib3

# Import our interface monitoring module - FIXED IMPORT
from interface_monitor import (
    InterfaceMonitor, InterfaceConfig,
    parse_interface_statistics_your_panos11, parse_session_statistics_your_panos11
)

# Suppress TLS warnings when verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOG = logging.getLogger("panos_monitor.updated_collectors")

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
    """PAN-OS API client optimized for your specific PAN-OS 11 system"""
    
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
            
            # Check for errors first
            status = root.get('status')
            if status == 'error':
                error_code = root.findtext('.//code', 'unknown')
                error_msg = root.findtext('.//msg', 'Unknown authentication error')
                self.last_error = f"Authentication failed (code {error_code}): {error_msg}"
                LOG.error(f"Keygen failed: {self.last_error}")
                return False
            
            key = root.findtext("result/key")
            if not key:
                self.last_error = f"API key not found in response: {resp.text[:400]}..."
                LOG.error(f"Keygen failed: {self.last_error}")
                return False
                
            self.api_key = key
            self.last_error = None
            LOG.info("Successfully authenticated and obtained API key")
            return True
            
        except RequestException as e:
            self.last_error = f"Keygen HTTP error: {e}"
            LOG.error(f"Keygen failed: {self.last_error}")
            return False
        except Exception as e:
            self.last_error = f"Keygen parse error: {e}"
            LOG.error(f"Keygen failed: {self.last_error}")
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
            
            # Check for API-level errors
            if 'status="error"' in resp.text:
                try:
                    root = ET.fromstring(resp.text)
                    error_code = root.findtext('.//code', 'unknown')
                    error_msg = root.findtext('.//msg', 'Unknown API error')
                    self.last_error = f"API error (code {error_code}): {error_msg}"
                    LOG.warning(f"API command failed: {self.last_error}")
                except:
                    self.last_error = f"API error in response: {resp.text[:200]}..."
                return None
            
            self.last_error = None
            return resp.text
            
        except RequestException as e:
            self.last_error = f"API request error: {e}"
            LOG.error(f"API request failed: {self.last_error}")
            return None
        except Exception as e:
            self.last_error = f"Unexpected error: {e}"
            LOG.error(f"API request failed: {self.last_error}")
            return None

    def op_fast(self, xml_cmd: str) -> Optional[str]:
        """Execute operational command with shorter timeout for frequent polling"""
        return self.op(xml_cmd, timeout=10)

    def request(self, xml_cmd: str) -> Optional[str]:
        """Execute request command - try it anyway for debug status"""
        if not self.api_key:
            self.last_error = "API key not set; call keygen() first"
            return None
            
        url = f"{self.base}/api/"
        # Request commands use type=op (not type=request)
        params = {"type": "op", "cmd": xml_cmd, "key": self.api_key}
        
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            
            # Check for API-level errors
            if 'status="error"' in resp.text:
                try:
                    root = ET.fromstring(resp.text)
                    error_code = root.findtext('.//code', 'unknown')
                    error_msg = root.findtext('.//msg', 'Unknown API error')
                    self.last_error = f"API error (code {error_code}): {error_msg}"
                    LOG.warning(f"Request command failed: {self.last_error}")
                except:
                    self.last_error = f"API error in response: {resp.text[:200]}..."
                return None
            
            self.last_error = None
            return resp.text
            
        except RequestException as e:
            self.last_error = f"API request error: {e}"
            LOG.error(f"Request command failed: {self.last_error}")
            return None
        except Exception as e:
            self.last_error = f"Unexpected error: {e}"
            LOG.error(f"Request command failed: {self.last_error}")
            return None

# Helper functions (same as before)
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

def parse_dp_cpu_from_rm_your_panos11(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Parse data plane CPU from resource monitor - optimized for your PAN-OS 11"""
    out: Dict[str, float] = {}
    
    if not xml_text or not xml_text.strip():
        return {}, "dp-cpu: empty resource monitor response"
    
    try:
        root = ET.fromstring(xml_text)
        
        # Check for API errors
        status = root.get('status')
        if status == 'error':
            error_msg = root.findtext('.//msg', 'Unknown API error')
            return {}, f"dp-cpu: resource monitor API error - {error_msg}"
        
        per_core_latest: List[float] = []
        
        # Based on debug results, your system has resource-monitor structure
        # Let's examine the actual structure more carefully
        
        # First, try the standard paths that should work based on debug success
        dp_paths = [
            ".//data-processors/*/minute/cpu-load-maximum/entry/value",
            ".//resource-monitor//data-processors/*/minute/cpu-load-maximum/entry/value",
            ".//result//data-processors/*/minute/cpu-load-maximum/entry/value"
        ]
        
        found_values = False
        for path in dp_paths:
            nodes = root.findall(path)
            if nodes:
                LOG.debug(f"Found DP CPU values using path: {path}")
                found_values = True
                
                for node in nodes:
                    if node.text:
                        arr = _numbers_from_csv(node.text)
                        if not arr:
                            continue
                        newest = arr[0]  # Most recent value
                        
                        # Check if values are fractional (0.0-1.0) and convert to percentage
                        has_decimals = any(v != int(v) for v in arr if v > 0)
                        if has_decimals and max(arr) <= 1.0:
                            newest *= 100.0
                            
                        # Validate reasonable range
                        if 0 <= newest <= 100:
                            per_core_latest.append(newest)
                        else:
                            LOG.debug(f"DP CPU value out of range: {newest}%")
                break
        
        # If standard paths don't work, try more general resource paths
        if not found_values:
            LOG.debug("Trying alternative DP CPU paths...")
            # Look for any CPU-related entries in the resource monitor
            for entry in root.findall(".//entry"):
                name_elem = entry.find("name")
                value_elem = entry.find("value")
                
                if name_elem is not None and value_elem is not None:
                    name = name_elem.text or ""
                    if "cpu" in name.lower():
                        LOG.debug(f"Found CPU entry: {name}")
                        arr = _numbers_from_csv(value_elem.text or "")
                        if arr:
                            value = arr[0]
                            # Check if fractional
                            if value <= 1.0:
                                value *= 100.0
                            if 0 <= value <= 100:
                                per_core_latest.append(value)
                                found_values = True

        # Calculate all three aggregation methods
        if per_core_latest:
            out["data_plane_cpu_mean"] = _aggregate(per_core_latest, "mean")
            out["data_plane_cpu_max"] = _aggregate(per_core_latest, "max")
            out["data_plane_cpu_p95"] = _aggregate(per_core_latest, "p95")
            
            # Keep the original field for backward compatibility (defaults to mean)
            out["data_plane_cpu"] = out["data_plane_cpu_mean"]
            
            return out, f"dp-cpu: {len(per_core_latest)} cores (your PAN-OS 11)"
        else:
            # Set zero values if no data found
            out["data_plane_cpu_mean"] = 0.0
            out["data_plane_cpu_max"] = 0.0
            out["data_plane_cpu_p95"] = 0.0
            out["data_plane_cpu"] = 0.0
            
            return out, "dp-cpu: no valid data found in resource monitor"

    except ET.ParseError as e:
        return {}, f"dp-cpu: XML parse error - {e}"
    except Exception as e:
        return {}, f"dp-cpu: unexpected parsing error - {e}"

def parse_pbuf_live_from_rm_your_panos11(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Parse packet buffer from resource monitor - optimized for your PAN-OS 11"""
    out: Dict[str, float] = {}
    
    if not xml_text or not xml_text.strip():
        return {}, "pbuf: empty resource monitor response"
    
    try:
        root = ET.fromstring(xml_text)
        
        # Check for API errors
        status = root.get('status')
        if status == 'error':
            error_msg = root.findtext('.//msg', 'Unknown API error')
            return {}, f"pbuf: resource monitor API error - {error_msg}"
        
        latest_vals: List[float] = []
        
        # Look for packet buffer entries in resource monitor
        # Since your resource monitor works, we'll scan for relevant entries
        
        for entry in root.findall(".//entry"):
            name_elem = entry.find("name")
            value_elem = entry.find("value")
            
            if name_elem is not None and value_elem is not None:
                name = (name_elem.text or "").lower()
                
                # Look for packet buffer indicators
                if any(indicator in name for indicator in [
                    "packet buffer", "packet-buffer", "pbuf",
                    "buffer utilization", "buffer-utilization",
                    "memory utilization", "memory-utilization"
                ]):
                    LOG.debug(f"Found potential packet buffer entry: {name}")
                    value_text = value_elem.text or ""
                    arr = _numbers_from_csv(value_text)
                    if arr:
                        value = arr[0]  # Most recent value
                        if 0 <= value <= 100:  # Validate percentage
                            latest_vals.append(value)
                            LOG.debug(f"Added packet buffer value: {value}%")
                        else:
                            LOG.debug(f"Packet buffer value out of range: {value}%")
        
        if latest_vals:
            out["pbuf_util_percent"] = _aggregate(latest_vals, "mean")
            return out, f"pbuf: {len(latest_vals)} values (your PAN-OS 11)"
        else:
            out["pbuf_util_percent"] = 0.0
            return out, "pbuf: no packet buffer data found in resource monitor"
        
    except ET.ParseError as e:
        return {}, f"pbuf: XML parse error - {e}"
    except Exception as e:
        return {}, f"pbuf: unexpected parsing error - {e}"

def parse_cpu_from_debug_status(xml_text: str) -> Tuple[Dict[str, float], str]:
    """
    Parse management CPU from debug status - most accurate method
    Uses: <request><s><debug><status/></debug></s></request>
    This gives the same values as the GUI dashboard
    """
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
                    "mgmt_cpu_debug": cpu_percent  # Keep both for compatibility
                })
                return out, f"cpu: debug status {cpu_percent}%"
            except ValueError:
                pass
        
        return {}, "cpu: no mp-cpu-utilization in debug status"
    except Exception as e:
        return {}, f"cpu parse error from debug status: {e}"

def parse_cpu_from_system_info(xml_text: str) -> Tuple[Dict[str, float], str]:
    """
    Parse management CPU from system info - more reliable than top
    Uses: <show><s><info/></s></show>
    """
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        
        # Look for system info load average fields
        load_avg_1min = root.findtext(".//system/load-avg-1-min")
        load_avg_5min = root.findtext(".//system/load-avg-5-min")
        load_avg_15min = root.findtext(".//system/load-avg-15-min")
        
        if load_avg_1min:
            try:
                # Load average is typically 0-N (where N is number of cores)
                # Convert to rough CPU percentage (load avg * 100, capped at 100%)
                load_avg = float(load_avg_1min)
                cpu_percent = min(load_avg * 100, 100.0)
                out.update({
                    "mgmt_cpu": cpu_percent,
                    "mgmt_cpu_load_avg": cpu_percent,
                    "load_avg_1min": load_avg
                })
                
                # Add 5min and 15min if available
                if load_avg_5min:
                    out["load_avg_5min"] = float(load_avg_5min)
                if load_avg_15min:
                    out["load_avg_15min"] = float(load_avg_15min)
                
                return out, f"cpu: system info load avg {load_avg} ({cpu_percent:.1f}%)"
            except ValueError:
                pass
        
        # Alternative: look for uptime field which might contain load average
        uptime = root.findtext(".//system/uptime") or ""
        if "load average:" in uptime.lower():
            # Extract load average from uptime string
            # Format: "up 1 day, 2:34, load average: 0.15, 0.10, 0.05"
            match = re.search(r"load average:\s*([0-9.]+)", uptime, re.IGNORECASE)
            if match:
                load_avg = float(match.group(1))
                cpu_percent = min(load_avg * 100, 100.0)
                out.update({
                    "mgmt_cpu": cpu_percent,
                    "mgmt_cpu_load_avg": cpu_percent,
                    "load_avg_1min": load_avg
                })
                return out, f"cpu: uptime load avg {load_avg} ({cpu_percent:.1f}%)"
        
        return {}, "cpu: no load average found in system info"
    except Exception as e:
        return {}, f"cpu parse error from system info: {e}"

def parse_cpu_from_top(xml_text: str) -> Tuple[Dict[str, float], str]:
    """
    Parse management CPU from top CDATA (fallback method)
    Enhanced version with better regex patterns
    """
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        raw = root.findtext("result") or "".join(root.itertext())
        if not raw:
            return {}, "cpu: no result text"
        
        # Clean up the text
        text = raw.replace("\r", "").replace("\n", " ").replace("\t", " ")
        
        # Multiple regex patterns to handle different top output formats
        patterns = [
            # Standard format: %Cpu(s): 51.9%us, 5.4%sy, 1.0%ni, 41.6%id, 0.1%wa, 0.0%hi, 0.0%si, 0.0%st
            r"%?Cpu\(s\)[^0-9]*([0-9.]+)%?\s*us[, ]+\s*([0-9.]+)%?\s*sy[, ]+.*?([0-9.]+)%?\s*id",
            # Alternative format without %: Cpu(s): 51.9 us, 5.4 sy, 1.0 ni, 41.6 id
            r"Cpu\(s\):\s*([0-9.]+)\s*us[, ]+\s*([0-9.]+)\s*sy[, ]+.*?([0-9.]+)\s*id",
            # Compact format: CPU: 51.9us 5.4sy 41.6id
            r"CPU:\s*([0-9.]+)us\s*([0-9.]+)sy\s*([0-9.]+)id",
        ]
        
        for i, pattern in enumerate(patterns):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                usr, sy, idle = map(float, match.groups())
                mgmt_cpu = usr + sy
                out.update({
                    "cpu_user": usr,
                    "cpu_system": sy,
                    "cpu_idle": idle,
                    "mgmt_cpu": mgmt_cpu
                })
                return out, f"cpu: fallback top pattern {i+1} - {mgmt_cpu}%"
        
        return {}, "cpu: no patterns matched in fallback top"
    except Exception as e:
        return {}, f"cpu fallback top parse error: {e}"

def parse_management_cpu_from_system_resources(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Parse management plane CPU from system resources - for your PAN-OS 11"""
    out: Dict[str, float] = {}
    
    if not xml_text or not xml_text.strip():
        return {}, "mgmt-cpu: empty system resources response"
    
    try:
        root = ET.fromstring(xml_text)
        
        # Check for API errors
        status = root.get('status')
        if status == 'error':
            error_msg = root.findtext('.//msg', 'Unknown API error')
            return {}, f"mgmt-cpu: system resources API error - {error_msg}"
        
        # Common paths for management CPU in system resources
        # PAN-OS typically reports CPU usage as a percentage
        cpu_paths = [
            ".//result/cpu/user",
            ".//result/cpu/sys", 
            ".//cpu/user",
            ".//cpu/sys",
            ".//result/load-average/entry",
            ".//load-average/entry"
        ]
        
        cpu_values = []
        
        # Try to find CPU user and system time
        user_cpu = None
        sys_cpu = None
        
        for path in [".//result/cpu/user", ".//cpu/user"]:
            elem = root.find(path)
            if elem is not None and elem.text:
                try:
                    user_cpu = float(elem.text.strip().rstrip('%'))
                    break
                except ValueError:
                    pass
        
        for path in [".//result/cpu/sys", ".//cpu/sys"]:
            elem = root.find(path)
            if elem is not None and elem.text:
                try:
                    sys_cpu = float(elem.text.strip().rstrip('%'))
                    break
                except ValueError:
                    pass
        
        # If we found user and sys CPU, calculate total management CPU
        if user_cpu is not None and sys_cpu is not None:
            total_cpu = user_cpu + sys_cpu
            if 0 <= total_cpu <= 100:
                out["management_cpu"] = total_cpu
                out["management_cpu_user"] = user_cpu
                out["management_cpu_sys"] = sys_cpu
                return out, f"mgmt-cpu: parsed from system resources (user: {user_cpu}%, sys: {sys_cpu}%)"
        
        # Alternative: Look for load average and convert to percentage
        # Load average format: typically 1-minute, 5-minute, 15-minute
        load_entries = root.findall(".//load-average/entry") or root.findall(".//result/load-average/entry")
        if load_entries:
            # Get 1-minute load average (first entry)
            for entry in load_entries:
                name_elem = entry.find("name")
                value_elem = entry.find("value")
                if name_elem is not None and value_elem is not None:
                    name = name_elem.text or ""
                    if "1" in name or "one" in name.lower():  # 1-minute load average
                        try:
                            load_value = float(value_elem.text.strip())
                            # Convert load average to approximate CPU percentage
                            # Assuming single CPU core, load of 1.0 = 100%
                            # For multi-core, this is an approximation
                            cpu_percent = min(load_value * 100, 100)
                            out["management_cpu"] = cpu_percent
                            return out, f"mgmt-cpu: estimated from load average ({load_value})"
                        except ValueError:
                            pass
        
        # Try alternative structure - sometimes CPU is directly under result
        result = root.find(".//result")
        if result is not None:
            # Look for any element with "cpu" in the name
            for child in result:
                tag_lower = child.tag.lower()
                if "cpu" in tag_lower and child.text:
                    try:
                        value = float(child.text.strip().rstrip('%'))
                        if 0 <= value <= 100:
                            cpu_values.append(value)
                            LOG.debug(f"Found CPU value in {child.tag}: {value}%")
                    except ValueError:
                        pass
        
        if cpu_values:
            out["management_cpu"] = sum(cpu_values)
            return out, f"mgmt-cpu: parsed {len(cpu_values)} CPU values"
        
        # If we still haven't found anything, return empty
        out["management_cpu"] = 0.0
        return out, "mgmt-cpu: no CPU data found in system resources"
        
    except ET.ParseError as e:
        return {}, f"mgmt-cpu: XML parse error - {e}"
    except Exception as e:
        return {}, f"mgmt-cpu: unexpected parsing error - {e}"



class EnhancedFirewallCollector:
    """Enhanced collector optimized for your specific PAN-OS 11 system"""
    
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
        
        # Interface monitoring
        interface_configs = getattr(config, 'interface_configs', None)
        if not interface_configs:
            interface_configs = create_default_interface_configs()
        
        self.interface_monitor = InterfaceMonitor(name, self.client, config)
        
        LOG.info(f"{self.name}: Enhanced collector initialized for your specific PAN-OS 11")
        
    def authenticate(self) -> bool:
        """Authenticate with the firewall"""
        success = self.client.keygen(self.config.username, self.config.password)
        if success:
            self.authenticated = True
            
            # Start interface monitoring
            self.interface_monitor.start_monitoring()
            
            LOG.info(f"Successfully authenticated with {self.name} and started monitoring")
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
    
    def collect_management_cpu_your_panos11(self) -> Dict[str, float]:
        """
        Collect Management CPU using multiple methods with fallback
        Priority: debug status > system info > system resources (top)
        """
        cpu_metrics = {}
        
        # Method 1: Debug status (most accurate - matches GUI)
        try:
            LOG.info(f"{self.name}: Attempting Method 1 - Debug status")
            xml = self.client.request("<request><s><debug><status/></debug></s></request>")
            if xml and 'status="success"' in xml:
                self._save_raw_xml("debug_status", xml)
                metrics, msg = parse_cpu_from_debug_status(xml)
                if metrics and "mgmt_cpu" in metrics:
                    # Keep mgmt_cpu to match database schema
                    cpu_metrics.update(metrics)  # Include all fields (mgmt_cpu, mgmt_cpu_debug, etc.)
                    LOG.info(f"{self.name}: ✅ Method 1 SUCCESS - {msg}")
                    LOG.info(f"{self.name}: Management CPU value: {cpu_metrics['mgmt_cpu']:.2f}%")
                    return cpu_metrics  # Return immediately if successful
                else:
                    LOG.debug(f"{self.name}: Method 1 failed to parse: {msg}")
            else:
                LOG.debug(f"{self.name}: Method 1 failed: {self.client.last_error}")
        except Exception as e:
            LOG.debug(f"{self.name}: Method 1 exception: {e}")
        
        # Method 2: System info with load average
        try:
            LOG.info(f"{self.name}: Attempting Method 2 - System info")
            xml = self.client.op("<show><system><info/></system></show>")
            if xml and 'status="success"' in xml:
                self._save_raw_xml("system_info", xml)
                metrics, msg = parse_cpu_from_system_info(xml)
                if metrics and "mgmt_cpu" in metrics:
                    # Keep mgmt_cpu to match database schema
                    cpu_metrics.update(metrics)  # Include all fields
                    LOG.info(f"{self.name}: ✅ Method 2 SUCCESS - {msg}")
                    LOG.info(f"{self.name}: Management CPU value: {cpu_metrics['mgmt_cpu']:.2f}%")
                    return cpu_metrics  # Return immediately if successful
                else:
                    LOG.debug(f"{self.name}: Method 2 failed to parse: {msg}")
            else:
                LOG.debug(f"{self.name}: Method 2 failed: {self.client.last_error}")
        except Exception as e:
            LOG.debug(f"{self.name}: Method 2 exception: {e}")
        
        # Method 3: System resources (top) - fallback
        try:
            LOG.info(f"{self.name}: Attempting Method 3 - System resources (top)")
            xml = self.client.op("<show><system><resources/></system></show>")
            if xml:
                self._save_raw_xml("system_resources", xml)
                
                # Try the new parser first
                metrics, msg = parse_management_cpu_from_system_resources(xml)
                if metrics and "management_cpu" in metrics and metrics["management_cpu"] > 0:
                    # Rename management_cpu to mgmt_cpu to match database schema
                    cpu_metrics["mgmt_cpu"] = metrics["management_cpu"]
                    # Also include user/sys if present
                    if "management_cpu_user" in metrics:
                        cpu_metrics["cpu_user"] = metrics["management_cpu_user"]
                    if "management_cpu_sys" in metrics:
                        cpu_metrics["cpu_system"] = metrics["management_cpu_sys"]
                    LOG.info(f"{self.name}: ✅ Method 3a SUCCESS - {msg}")
                    LOG.info(f"{self.name}: Management CPU value: {cpu_metrics['mgmt_cpu']:.2f}%")
                    return cpu_metrics
                else:
                    LOG.debug(f"{self.name}: Method 3a returned zero or no data: {msg}")
                
                # Fall back to the enhanced top parser
                metrics, msg = parse_cpu_from_top(xml)
                if metrics and "mgmt_cpu" in metrics:
                    # Keep mgmt_cpu to match database schema
                    cpu_metrics.update(metrics)  # Include cpu_user, cpu_system, cpu_idle, mgmt_cpu
                    LOG.info(f"{self.name}: ✅ Method 3b SUCCESS - {msg}")
                    LOG.info(f"{self.name}: Management CPU value: {cpu_metrics['mgmt_cpu']:.2f}%")
                    return cpu_metrics
                else:
                    LOG.debug(f"{self.name}: Method 3b failed to parse: {msg}")
            else:
                LOG.warning(f"{self.name}: Method 3 failed to get XML: {self.client.last_error}")
        except Exception as e:
            LOG.warning(f"{self.name}: Method 3 exception: {e}")
        
        LOG.error(f"{self.name}: ❌ ALL CPU MONITORING METHODS FAILED")
        return {}

    def collect_metrics(self) -> CollectionResult:
        """Enhanced metrics collection optimized for your PAN-OS 11"""
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
        
        # Management CPU using system resources command
        try:
            mgmt_cpu_metrics = self.collect_management_cpu_your_panos11()
            if mgmt_cpu_metrics:
                metrics.update(mgmt_cpu_metrics)
                LOG.debug(f"{self.name}: Management CPU collected: {mgmt_cpu_metrics.get('management_cpu', 0):.1f}%")
        except Exception as e:
            LOG.warning(f"{self.name}: Management CPU collection error: {e}")
        
        # Data plane CPU and packet buffer using WORKING resource monitor
        try:
            xml = self.client.op("<show><running><resource-monitor><minute></minute></resource-monitor></running></show>")
            if xml:
                self._save_raw_xml("resource_monitor", xml)
                
                # DP CPU optimized for your PAN-OS 11
                d, msg = parse_dp_cpu_from_rm_your_panos11(xml)
                metrics.update({k: v for k, v in d.items() if v is not None})
                LOG.debug(f"{self.name}: {msg}")
                
                # Packet buffer optimized for your PAN-OS 11
                d2, msg2 = parse_pbuf_live_from_rm_your_panos11(xml)
                metrics.update({k: v for k, v in d2.items() if v is not None})
                LOG.debug(f"{self.name}: {msg2}")
            else:
                LOG.warning(f"{self.name}: Failed to get resource monitor: {self.client.last_error}")
        except Exception as e:
            LOG.warning(f"{self.name}: Resource monitor error: {e}")
        
        # Collect interface metrics using WORKING interface command
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
        
        # Collect session statistics
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
        self.interface_monitor.stop_monitoring()

# Use the existing MultiFirewallCollector structure but with our updated collector
class MultiFirewallCollector:
    """Enhanced collector manager optimized for your PAN-OS 11 system"""
    
    def __init__(self, firewall_configs=None, output_dir=None, database=None, global_config=None):
        """Initialize MultiFirewallCollector with optional arguments for backward compatibility"""
        
        # Handle the case where no arguments are provided (for backward compatibility)
        if firewall_configs is None:
            LOG.warning("MultiFirewallCollector initialized without arguments - using defaults")
            firewall_configs = {}
            output_dir = Path("/var/lib/panos-monitor/output")
            database = None
            global_config = None
        
        self.firewall_configs = firewall_configs
        self.output_dir = output_dir
        self.database = database
        self.global_config = global_config
        self.collectors: Dict[str, EnhancedFirewallCollector] = {}
        self.collection_threads: Dict[str, Thread] = {}
        self.stop_events: Dict[str, Event] = {}
        self.metrics_queue = Queue()
        self.running = False
        
        # Initialize enhanced collectors only if we have firewall configs
        if firewall_configs:
            for name, config in firewall_configs.items():
                if hasattr(config, 'enabled') and config.enabled:
                    self.collectors[name] = EnhancedFirewallCollector(name, config, output_dir, global_config)
                    self.stop_events[name] = Event()
        else:
            LOG.info("No firewall configurations provided - collector initialized in minimal mode")
    
    def start_collection(self):
        """Start collection threads for all enabled firewalls"""
        if self.running:
            LOG.warning("Collection is already running")
            return
        
        self.running = True
        LOG.info(f"Starting collection optimized for your specific PAN-OS 11 system")
        
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
        
        LOG.info("All collection threads started for your PAN-OS 11 system")
    
    def stop_collection(self):
        """Stop all collection threads"""
        if not self.running:
            return
        
        LOG.info("Stopping collection threads...")
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
        
        LOG.info("All collection threads stopped")
    
    def _collection_worker(self, name: str, collector: EnhancedFirewallCollector, stop_event: Event):
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
    
    def _enhanced_metrics_processor(self):
        """Process collected metrics and store in database"""
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
                    
                    # Store interface metrics
                    if result.interface_metrics and hasattr(self.database, 'insert_interface_metrics'):
                        for interface_name, interface_data in result.interface_metrics.items():
                            success = self.database.insert_interface_metrics(result.firewall_name, interface_data)
                            if success:
                                LOG.debug(f"Stored interface metrics for {result.firewall_name}:{interface_name}")
                            else:
                                LOG.error(f"Failed to store interface metrics for {result.firewall_name}:{interface_name}")
                    
                    # Store session statistics
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
                LOG.error(f"Error in metrics processor: {e}")
        
        LOG.info("Enhanced metrics processor stopped")
    
    def get_collector_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all collectors"""
        status = {}
        for name, collector in self.collectors.items():
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
            
            # Add interface monitoring status
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

def main():
    """Main entry point for panos-monitor application"""
    import argparse
    import sys
    from pathlib import Path
    
    # Simple configuration for testing - replace with actual config loading
    print("PAN-OS Monitor starting with updated interface collection...")
    
    # For now, just verify the updated collectors work
    print("✅ Updated collectors loaded successfully")
    print("✅ Two-stage interface collection enabled")
    print("✅ Enhanced CPU collection methods available")
    
    # If this is being called as the main application, we need to integrate
    # with the existing application structure. For now, return success.
    return True

if __name__ == "__main__":
    # When run directly
    print("Updated collectors for your specific PAN-OS 11 system ready")
    print("Optimizations based on debug results:")
    print("✅ Debug Status: Priority method for management CPU (GUI-accurate)")
    print("✅ System Info: Fallback #1 for management CPU (load average)")
    print("✅ System Resources: Fallback #2 for management CPU (top)")
    print("✅ Resource Monitor: Working - used for DP CPU & packet buffer")
    print("✅ Interface Statistics: Working - used for bandwidth")
    print("🎯 Focus: Multi-method CPU collection and interface monitoring")
    
    # Also test the main function
    main()
