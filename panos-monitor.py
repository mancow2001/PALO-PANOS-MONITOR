#!/usr/bin/env python3
"""
PAN-OS Live Metrics + Exports + Web Dashboard (Dynamic Cores) - Enhanced
------------------------------------------------------------------------
• Live mgmt CPU (from `show system resources` top CDATA)
• Live DP CPU (newest sample) + packet buffer (newest sample) from resource-monitor
• Auto-detects ALL data processors and cores; no model-specific logic
• Aggregation mode for DP CPU: mean|max|p95    (env: DP_AGGREGATION=mean)
• Throughput/PPS from `show session info`
• Enhanced real-time web dashboard with improved UX
• On-exit CSV/XLSX/TXT exports + optional PNG charts
• Configurable XML debug logging

.env example
------------
PAN_HOST=https://10.100.192.3
PAN_USERNAME=admin
PAN_PASSWORD=YourPassword
VERIFY_SSL=false
POLL_INTERVAL=60
OUTPUT_TYPE=CSV           # CSV | XLSX | TXT
OUTPUT_DIR=./output
VISUALIZATION=Yes         # Yes | No (charts on exit)
WEB_DASHBOARD=Yes         # Yes | No
WEB_PORT=8080
DP_AGGREGATION=mean       # mean | max | p95
SAVE_RAW_XML=false        # true | false (debug XML logging)
XML_RETENTION_HOURS=24    # hours to keep XML files (if enabled)

requirements.txt
----------------
requests
python-dotenv
pandas
openpyxl
matplotlib
fastapi
uvicorn
jinja2
"""
import argparse
import os
import sys
import time
import signal
import logging
import pathlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple, List
from threading import Thread
import glob

import requests
from requests.exceptions import RequestException

# Optional deps
try:
    from dotenv import load_dotenv
    DOTENV_OK = True
except Exception:
    DOTENV_OK = False

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn
    FASTAPI_OK = True
except Exception:
    FASTAPI_OK = False

# Suppress TLS warnings when verify=False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------- Logging ----------------------------
LOG = logging.getLogger("panos_live")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------- Helpers ----------------------------
def env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y"}

def ensure_output_dir(path: str) -> pathlib.Path:
    p = pathlib.Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def cleanup_old_xml_files(xml_dir: pathlib.Path, retention_hours: int):
    """Remove XML files older than retention_hours"""
    if not xml_dir.exists() or retention_hours <= 0:
        return
    
    cutoff_time = datetime.now() - timedelta(hours=retention_hours)
    pattern = str(xml_dir / "*.xml")
    removed_count = 0
    
    for file_path in glob.glob(pattern):
        file_stat = os.stat(file_path)
        file_time = datetime.fromtimestamp(file_stat.st_mtime)
        if file_time < cutoff_time:
            try:
                os.remove(file_path)
                removed_count += 1
            except OSError as e:
                LOG.warning(f"Failed to remove old XML file {file_path}: {e}")
    
    if removed_count > 0:
        LOG.info(f"Cleaned up {removed_count} old XML files (older than {retention_hours}h)")

def _numbers_from_csv(text: str) -> List[float]:
    nums: List[float] = []
    for x in (text or "").split(","):
        xs = x.strip()
        # allow ints/floats
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", xs or ""):
            nums.append(float(xs))
    return nums

def _aggregate(values: List[float], mode: str = "mean") -> float:
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

class GracefulKiller:
    def __init__(self):
        self.kill_now = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
    def exit_gracefully(self, *_):
        self.kill_now = True

# ---------------------------- PAN-OS Client ----------------------------
class PanOSClient:
    def __init__(self, host: str, verify_ssl: bool = True):
        self.base = host.rstrip("/")
        if not self.base.startswith("http"):
            self.base = "https://" + self.base
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.api_key: Optional[str] = None

    def keygen(self, username: str, password: str) -> str:
        url = f"{self.base}/api/"
        try:
            resp = self.session.get(url, params={"type": "keygen", "user": username, "password": password}, timeout=20)
            resp.raise_for_status()
        except RequestException as e:
            raise RuntimeError(f"Keygen HTTP error: {e}")
        root = ET.fromstring(resp.text)
        key = root.findtext("result/key")
        if not key:
            raise RuntimeError(f"Key not found in keygen response: {resp.text[:400]}...")
        self.api_key = key
        return key

    def op(self, xml_cmd: str) -> str:
        if not self.api_key:
            raise RuntimeError("API key not set; call keygen() first")
        url = f"{self.base}/api/"
        params = {"type": "op", "cmd": xml_cmd, "key": self.api_key}
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.text

# ---------------------------- Parsers (LIVE) ----------------------------
CPU_FIELDS = ["cpu_user", "cpu_system", "cpu_idle", "mgmt_cpu", "data_plane_cpu"]
THR_FIELDS = ["throughput_mbps_total", "pps_total"]
PBUF_FIELDS = ["pbuf_util_percent"]

def parse_cpu_from_top(xml_text: str) -> Tuple[Dict[str, float], str]:
    """Mgmt CPU from top CDATA. Returns user/system/idle and mgmt=sum(user,system)."""
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
            out.update({"cpu_user": usr, "cpu_system": sy, "cpu_idle": idle, "mgmt_cpu": usr + sy})
            return out, "cpu: parsed top"
        return {}, "cpu: pattern not found"
    except Exception as e:
        return {}, f"cpu parse error: {e}"

def parse_dp_cpu_from_rm(xml_text: str) -> Tuple[Dict[str, float], str]:
    """
    LIVE DP CPU (percent): traverse ALL data processors and cores, take newest sample per core.
    Uses cpu-load-maximum instead of cpu-load-average for real spike detection.
    Values are already in percentage format (0-100) from PAN-OS; no normalization needed.
    Aggregate by mean|max|p95 (env DP_AGGREGATION).
    """
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        per_core_latest: List[float] = []
        # All dp groups, all cores (newest → oldest in value arrays)
        # Changed from cpu-load-average to cpu-load-maximum
        for node in root.findall(".//data-processors/*/minute/cpu-load-maximum/entry/value"):
            arr = _numbers_from_csv(node.text or "")
            if not arr:
                continue
            newest = arr[0]
            # PAN-OS returns CPU as integer percentages (0-100), not fractions
            # Only normalize if we detect true fractional values (e.g., 0.85 for 85%)
            # Check if ANY value in the array has a decimal component
            has_decimals = any(v != int(v) for v in arr if v > 0)
            if has_decimals and max(arr) <= 1.0:
                # True fractional format (0.0-1.0), convert to percentage
                newest *= 100.0
            # else: already in percentage format (0-100)
            per_core_latest.append(newest)

        agg_mode = os.getenv("DP_AGGREGATION", "mean")
        out["data_plane_cpu"] = _aggregate(per_core_latest, agg_mode)
        return out, f"dp-cpu cores={len(per_core_latest)} mode={agg_mode} (using maximum)"
    except Exception as e:
        return {}, f"dp-cpu parse error: {e}"
        
def parse_pbuf_live_from_rm(xml_text: str) -> Tuple[Dict[str, float], str]:
    """LIVE packet buffer %: newest sample per dp group, aggregate (mean). Uses maximum values for real spikes."""
    out: Dict[str, float] = {}
    try:
        root = ET.fromstring(xml_text)
        latest_vals: List[float] = []
        # Per DP group resource-utilization entries - use MAXIMUM values to capture real spikes
        for e in root.findall(".//data-processors/*/minute/resource-utilization/entry"):
            name = (e.findtext("name") or "").lower()
            if "packet buffer (maximum)" in name:  # Changed from (average) to (maximum)
                arr = _numbers_from_csv(e.findtext("value") or "")
                if arr:
                    latest_vals.append(arr[0])  # newest value
        out["pbuf_util_percent"] = _aggregate(latest_vals, "mean")
        return out, f"pbuf live groups={len(latest_vals)} (using maximum values)"
    except Exception as e:
        return {}, f"pbuf parse error: {e}"

def parse_throughput_from_session_info(xml_text: str) -> Tuple[Dict[str, float], str]:
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
        return out, "thr: parsed session info"
    except Exception as e:
        return {}, f"thr parse error: {e}"

# ---------------------------- Collector ----------------------------
class StatsCollector:
    def __init__(self, client: PanOSClient):
        self.client = client
        self.rows: List[Dict[str, Optional[float]]] = []   # rolling series for dashboard/exports
        self.raw_debug_dir: Optional[pathlib.Path] = None
        self.save_xml: bool = False
        self.xml_retention_hours: int = 24
        self.max_points = 1000  # keep last 1000 in memory

    def set_debug_dir(self, p: pathlib.Path, save_xml: bool = False, retention_hours: int = 24):
        self.raw_debug_dir = p
        self.save_xml = save_xml
        self.xml_retention_hours = retention_hours

    def _save_raw(self, name: str, content: str):
        if not self.raw_debug_dir or not self.save_xml:
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (self.raw_debug_dir / f"{ts}_{name}.xml").write_text(content, encoding="utf-8")

    def poll_once(self) -> Dict[str, Optional[float]]:
        metrics: Dict[str, Optional[float]] = {k: None for k in CPU_FIELDS + THR_FIELDS + PBUF_FIELDS}
        # timestamp in UTC ISO
        metrics["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Mgmt CPU (top)
        try:
            xml = self.client.op("<show><system><resources/></system></show>")
            self._save_raw("system_resources", xml)
            d, _ = parse_cpu_from_top(xml); metrics.update(d)
        except Exception as e:
            LOG.warning(f"top failed: {e}")

        # Resource monitor (DP CPU + PBUF live)
        try:
            xml = self.client.op("<show><running><resource-monitor><minute></minute></resource-monitor></running></show>")
            self._save_raw("resource_monitor", xml)
            d, _ = parse_dp_cpu_from_rm(xml); metrics.update({k: v for k, v in d.items() if v is not None})
            d2, _ = parse_pbuf_live_from_rm(xml); metrics.update({k: v for k, v in d2.items() if v is not None})
        except Exception as e:
            LOG.warning(f"resource-monitor failed: {e}")

        # Throughput/PPS (session info)
        try:
            xml = self.client.op("<show><session><info/></session></show>")
            self._save_raw("session_info", xml)
            d, _ = parse_throughput_from_session_info(xml); metrics.update({k: v for k, v in d.items() if v is not None})
        except Exception as e:
            LOG.warning(f"session info failed: {e}")

        self.rows.append(metrics)
        if len(self.rows) > self.max_points:
            del self.rows[: len(self.rows) - self.max_points]
        
        # Periodic XML cleanup
        if self.save_xml and len(self.rows) % 10 == 0:  # Every 10 polls
            cleanup_old_xml_files(self.raw_debug_dir, self.xml_retention_hours)
            
        return metrics

# ---------------------------- Outputs ----------------------------
def write_outputs(rows, out_dir: pathlib.Path, out_type: str):
    if not rows:
        return
    if out_type.upper() == "TXT":
        path = out_dir / "panos_stats.txt"
        with path.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(str(r) + "\n")
        LOG.info(f"Appended {len(rows)} rows to {path}")
        return
    if pd is None:
        raise RuntimeError("pandas not installed; required for CSV/XLSX output")
    df = pd.DataFrame(rows)
    df.sort_values("timestamp", inplace=True)
    if out_type.upper() == "CSV":
        path = out_dir / "panos_stats.csv"
        header = not path.exists()
        df.to_csv(path, index=False, mode="a", header=header)
        LOG.info(f"Wrote {len(df)} rows to {path}")
    elif out_type.upper() == "XLSX":
        path = out_dir / "panos_stats.xlsx"
        if path.exists():
            try:
                existing = pd.read_excel(path, sheet_name="stats")
                start = len(existing) + 1
            except Exception:
                start = 0
            with pd.ExcelWriter(path, mode="a", if_sheet_exists="overlay", engine="openpyxl") as xw:
                df.to_excel(xw, index=False, sheet_name="stats", startrow=start, header=(start == 0))
        else:
            with pd.ExcelWriter(path, engine="openpyxl") as xw:
                df.to_excel(xw, index=False, sheet_name="stats")
        LOG.info(f"Wrote {len(df)} rows to {path}")
    else:
        raise ValueError("OUTPUT_TYPE must be CSV, XLSX, or TXT")

def render_charts(all_rows, out_dir: pathlib.Path):
    if plt is None or not all_rows or pd is None:
        if plt is None:
            LOG.warning("matplotlib not installed; skipping visualization")
        return
    df = pd.DataFrame(all_rows)
    if "timestamp" not in df.columns:
        return
    df["ts"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df.sort_values("ts", inplace=True)
    def _plot(col, title, ylabel, fname):
        if col not in df.columns:
            return
        sub = df[["ts", col]].dropna()
        if sub.empty:
            return
        plt.figure()
        plt.plot(sub["ts"], sub[col])
        plt.title(title)
        plt.xlabel("Time")
        plt.ylabel(ylabel)
        plt.tight_layout()
        path = out_dir / fname
        plt.savefig(path)
        plt.close()
        LOG.info(f"Wrote chart: {path}")
    _plot("throughput_mbps_total", "Throughput (Total)", "Mbps", "throughput_total.png")
    _plot("pps_total", "Packets/sec (Total)", "pps", "pps_total.png")
    _plot("pbuf_util_percent", "Packet Buffer Live", "%", "packet_buffer_live.png")
    _plot("mgmt_cpu", "Mgmt CPU (User+System)", "%", "mgmt_cpu.png")
    _plot("data_plane_cpu", "Data Plane CPU (Live)", "%", "dp_cpu.png")

# ---------------------------- Enhanced Web Dashboard ----------------------------
def start_web_server(port: int, rows_ref: List[dict], refresh_ms: int, config: dict):
    if not FASTAPI_OK:
        LOG.warning("FastAPI/uvicorn not installed; web dashboard disabled")
        return
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index():
        refresh_s = int(refresh_ms / 1000)
        agg_mode = os.getenv("DP_AGGREGATION", "mean").upper()
        
        html = f"""
        <!doctype html><html><head><meta charset="utf-8"/>
        <title>PAN-OS Live Metrics Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: #333;
            }}
            .container {{ 
                max-width: 1400px; 
                margin: 0 auto; 
                padding: 20px;
            }}
            .header {{
                background: rgba(255,255,255,0.95);
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 20px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.1);
                backdrop-filter: blur(10px);
            }}
            .header h1 {{
                color: #2c3e50;
                margin-bottom: 10px;
                font-size: 2.2em;
                font-weight: 700;
            }}
            .header-info {{
                display: flex;
                gap: 30px;
                align-items: center;
                flex-wrap: wrap;
                margin-top: 15px;
            }}
            .info-item {{
                display: flex;
                align-items: center;
                gap: 8px;
                background: rgba(52, 152, 219, 0.1);
                padding: 8px 15px;
                border-radius: 20px;
                font-weight: 500;
            }}
            .status-indicator {{
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background: #27ae60;
                animation: pulse 2s infinite;
            }}
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.5; }}
            }}
            .metrics-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                gap: 20px;
                margin-bottom: 20px;
            }}
            .metric-card {{
                background: rgba(255,255,255,0.95);
                border-radius: 15px;
                padding: 20px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.1);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.2);
            }}
            .metric-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
            }}
            .metric-title {{
                font-size: 1.3em;
                font-weight: 600;
                color: #2c3e50;
            }}
            .metric-value {{
                font-size: 1.1em;
                font-weight: 500;
                padding: 5px 12px;
                border-radius: 8px;
                background: rgba(52, 152, 219, 0.1);
                color: #2980b9;
            }}
            .chart-container {{
                position: relative;
                height: 300px;
                margin-top: 10px;
            }}
            .current-values {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }}
            .value-card {{
                background: rgba(255,255,255,0.95);
                border-radius: 12px;
                padding: 20px;
                text-align: center;
                box-shadow: 0 4px 16px rgba(0,0,0,0.1);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.2);
                transition: transform 0.2s ease;
            }}
            .value-card:hover {{
                transform: translateY(-2px);
            }}
            .value-label {{
                font-size: 0.9em;
                color: #7f8c8d;
                margin-bottom: 8px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .value-number {{
                font-size: 2em;
                font-weight: 700;
                margin-bottom: 5px;
            }}
            .value-unit {{
                font-size: 0.9em;
                color: #95a5a6;
                font-weight: 500;
            }}
            .cpu-high {{ color: #e74c3c; }}
            .cpu-medium {{ color: #f39c12; }}
            .cpu-low {{ color: #27ae60; }}
            .controls {{
                background: rgba(255,255,255,0.95);
                border-radius: 12px;
                padding: 15px;
                margin-bottom: 20px;
                display: flex;
                gap: 15px;
                align-items: center;
                flex-wrap: wrap;
                box-shadow: 0 4px 16px rgba(0,0,0,0.1);
            }}
            .control-group {{
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .control-group label {{
                font-weight: 500;
                color: #2c3e50;
            }}
            .control-group select, .control-group input {{
                padding: 5px 10px;
                border: 1px solid #bdc3c7;
                border-radius: 5px;
                background: white;
            }}
            .timestamp {{
                font-size: 0.9em;
                color: #7f8c8d;
                margin-top: 10px;
            }}
            .footer {{
                text-align: center;
                color: rgba(255,255,255,0.8);
                margin-top: 30px;
                font-size: 0.9em;
            }}
        </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔥 PAN-OS Live Metrics Dashboard</h1>
                    <div class="header-info">
                        <div class="info-item">
                            <div class="status-indicator"></div>
                            <span>Live Monitoring</span>
                        </div>
                        <div class="info-item">
                            <span>🔄 Refresh: {refresh_s}s</span>
                        </div>
                        <div class="info-item">
                            <span>📊 DP Aggregation: {agg_mode}</span>
                        </div>
                        <div class="info-item">
                            <span>🖥️ Host: {config.get('host', 'Unknown')}</span>
                        </div>
                    </div>
                </div>

                <div class="current-values" id="currentValues">
                    <!-- Current values will be populated by JavaScript -->
                </div>

                <div class="controls">
                    <div class="control-group">
                        <label for="timeRange">Time Range:</label>
                        <select id="timeRange">
                            <option value="50">Last 50 points</option>
                            <option value="100" selected>Last 100 points</option>
                            <option value="200">Last 200 points</option>
                            <option value="500">Last 500 points</option>
                        </select>
                    </div>
                    <div class="control-group">
                        <label for="autoRefresh">Auto Refresh:</label>
                        <input type="checkbox" id="autoRefresh" checked>
                    </div>
                    <div class="control-group">
                        <button onclick="refreshNow()" style="padding: 8px 15px; background: #3498db; color: white; border: none; border-radius: 5px; cursor: pointer;">Refresh Now</button>
                    </div>
                </div>

                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-header">
                            <span class="metric-title">🖥️ CPU Usage</span>
                            <span class="metric-value" id="cpuCurrent">--</span>
                        </div>
                        <div class="chart-container">
                            <canvas id="cpuChart"></canvas>
                        </div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-header">
                            <span class="metric-title">🚀 Network Throughput</span>
                            <span class="metric-value" id="throughputCurrent">--</span>
                        </div>
                        <div class="chart-container">
                            <canvas id="throughputChart"></canvas>
                        </div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-header">
                            <span class="metric-title">📦 Packet Buffer</span>
                            <span class="metric-value" id="pbufCurrent">--</span>
                        </div>
                        <div class="chart-container">
                            <canvas id="pbufChart"></canvas>
                        </div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-header">
                            <span class="metric-title">📊 Packets per Second</span>
                            <span class="metric-value" id="ppsCurrent">--</span>
                        </div>
                        <div class="chart-container">
                            <canvas id="ppsChart"></canvas>
                        </div>
                    </div>
                </div>

                <div class="timestamp" id="lastUpdate"></div>

                <div class="footer">
                    PAN-OS Monitoring Dashboard • Real-time metrics collection and visualization
                </div>
            </div>

            <script>
                let autoRefreshEnabled = true;
                let charts = {{}};
                let refreshInterval;

                async function fetchData() {{
                    try {{
                        const response = await fetch('/metrics');
                        return await response.json();
                    }} catch (error) {{
                        console.error('Failed to fetch data:', error);
                        return [];
                    }}
                }}

                function formatValue(value, decimals = 1) {{
                    if (value === null || value === undefined) return '--';
                    return typeof value === 'number' ? value.toFixed(decimals) : value;
                }}

                function formatTimestamp(timestamp) {{
                    if (!timestamp) return '--';
                    const date = new Date(timestamp);
                    return date.toLocaleTimeString();
                }}

                function getCpuClass(value) {{
                    if (value === null || value === undefined) return 'cpu-low';
                    if (value > 80) return 'cpu-high';
                    if (value > 60) return 'cpu-medium';
                    return 'cpu-low';
                }}

                function updateCurrentValues(data) {{
                    if (!data || data.length === 0) return;
                    
                    const latest = data[data.length - 1];
                    const mgmtCpu = latest.mgmt_cpu;
                    const dpCpu = latest.data_plane_cpu;
                    const throughput = latest.throughput_mbps_total;
                    const pps = latest.pps_total;
                    const pbuf = latest.pbuf_util_percent;

                    const currentValuesHtml = `
                        <div class="value-card">
                            <div class="value-label">Management CPU</div>
                            <div class="value-number ${{getCpuClass(mgmtCpu)}}">${{formatValue(mgmtCpu)}}</div>
                            <div class="value-unit">%</div>
                        </div>
                        <div class="value-card">
                            <div class="value-label">Data Plane CPU</div>
                            <div class="value-number ${{getCpuClass(dpCpu)}}">${{formatValue(dpCpu)}}</div>
                            <div class="value-unit">%</div>
                        </div>
                        <div class="value-card">
                            <div class="value-label">Throughput</div>
                            <div class="value-number">${{formatValue(throughput)}}</div>
                            <div class="value-unit">Mbps</div>
                        </div>
                        <div class="value-card">
                            <div class="value-label">Packets/sec</div>
                            <div class="value-number">${{formatValue(pps, 0)}}</div>
                            <div class="value-unit">pps</div>
                        </div>
                        <div class="value-card">
                            <div class="value-label">Packet Buffer</div>
                            <div class="value-number ${{getCpuClass(pbuf)}}">${{formatValue(pbuf)}}</div>
                            <div class="value-unit">%</div>
                        </div>
                    `;
                    
                    document.getElementById('currentValues').innerHTML = currentValuesHtml;
                    
                    // Update metric headers
                    document.getElementById('cpuCurrent').textContent = `Mgmt: ${{formatValue(mgmtCpu)}}% | DP: ${{formatValue(dpCpu)}}%`;
                    document.getElementById('throughputCurrent').textContent = `${{formatValue(throughput)}} Mbps`;
                    document.getElementById('pbufCurrent').textContent = `${{formatValue(pbuf)}}%`;
                    document.getElementById('ppsCurrent').textContent = `${{formatValue(pps, 0)}} pps`;
                    
                    document.getElementById('lastUpdate').textContent = `Last updated: ${{formatTimestamp(latest.timestamp)}}`;
                }}

                function createChart(canvasId, label1, label2, color1, color2) {{
                    const ctx = document.getElementById(canvasId).getContext('2d');
                    const datasets = [{{
                        label: label1,
                        data: [],
                        borderColor: color1,
                        backgroundColor: color1 + '20',
                        fill: false,
                        tension: 0.4,
                        pointRadius: 2,
                        pointHoverRadius: 5
                    }}];
                    
                    if (label2) {{
                        datasets.push({{
                            label: label2,
                            data: [],
                            borderColor: color2,
                            backgroundColor: color2 + '20',
                            fill: false,
                            tension: 0.4,
                            pointRadius: 2,
                            pointHoverRadius: 5
                        }});
                    }}

                    return new Chart(ctx, {{
                        type: 'line',
                        data: {{
                            labels: [],
                            datasets: datasets
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            animation: {{ duration: 300 }},
                            scales: {{
                                y: {{
                                    beginAtZero: true,
                                    grid: {{ color: 'rgba(0,0,0,0.1)' }},
                                    ticks: {{ color: '#666' }}
                                }},
                                x: {{
                                    grid: {{ color: 'rgba(0,0,0,0.1)' }},
                                    ticks: {{ 
                                        color: '#666',
                                        maxTicksLimit: 10
                                    }}
                                }}
                            }},
                            plugins: {{
                                legend: {{
                                    position: 'top',
                                    labels: {{ color: '#333' }}
                                }}
                            }},
                            interaction: {{
                                intersect: false,
                                mode: 'index'
                            }}
                        }}
                    }});
                }}

                function initCharts() {{
                    console.log('Initializing charts...');
                    try {{
                        charts.cpu = createChart('cpuChart', 'Management CPU (%)', 'Data Plane CPU (%)', '#e74c3c', '#3498db');
                        charts.throughput = createChart('throughputChart', 'Throughput (Mbps)', null, '#2ecc71');
                        charts.pbuf = createChart('pbufChart', 'Packet Buffer (%)', null, '#f39c12');
                        charts.pps = createChart('ppsChart', 'Packets per Second', null, '#9b59b6');
                        console.log('Charts initialized successfully');
                    }} catch (error) {{
                        console.error('Failed to initialize charts:', error);
                    }}
                }}

                function updateCharts(data) {{
                    if (!data || data.length === 0) {{
                        console.warn('No data to update charts');
                        return;
                    }}
                    
                    const timeRange = parseInt(document.getElementById('timeRange').value);
                    const displayData = data.slice(-timeRange);
                    console.log('Updating charts with', displayData.length, 'data points');
                    
                    const labels = displayData.map(d => formatTimestamp(d.timestamp));
                    
                    // CPU Chart
                    if (charts.cpu) {{
                        charts.cpu.data.labels = labels;
                        charts.cpu.data.datasets[0].data = displayData.map(d => d.mgmt_cpu || 0);
                        charts.cpu.data.datasets[1].data = displayData.map(d => d.data_plane_cpu || 0);
                        charts.cpu.update('active');
                    }}
                    
                    // Throughput Chart
                    if (charts.throughput) {{
                        charts.throughput.data.labels = labels;
                        charts.throughput.data.datasets[0].data = displayData.map(d => d.throughput_mbps_total || 0);
                        charts.throughput.update('active');
                    }}
                    
                    // Packet Buffer Chart
                    if (charts.pbuf) {{
                        charts.pbuf.data.labels = labels;
                        charts.pbuf.data.datasets[0].data = displayData.map(d => d.pbuf_util_percent || 0);
                        charts.pbuf.update('active');
                    }}
                    
                    // PPS Chart
                    if (charts.pps) {{
                        charts.pps.data.labels = labels;
                        charts.pps.data.datasets[0].data = displayData.map(d => d.pps_total || 0);
                        charts.pps.update('active');
                    }}
                    
                    console.log('All charts updated');
                }}

                async function refreshData() {{
                    try {{
                        console.log('Fetching data...');
                        const data = await fetchData();
                        console.log('Data received:', data.length, 'points');
                        
                        if (data && data.length > 0) {{
                            updateCurrentValues(data);
                            updateCharts(data);
                            console.log('Charts updated successfully');
                        }} else {{
                            console.warn('No data received');
                        }}
                    }} catch (error) {{
                        console.error('Failed to refresh data:', error);
                    }}
                }}

                function refreshNow() {{
                    console.log('Manual refresh triggered');
                    refreshData();
                }}

                function setupAutoRefresh() {{
                    if (refreshInterval) {{
                        clearInterval(refreshInterval);
                        refreshInterval = null;
                    }}
                    
                    if (autoRefreshEnabled) {{
                        console.log('Setting up auto-refresh every {refresh_ms}ms');
                        refreshInterval = setInterval(() => {{
                            console.log('Auto-refresh triggered');
                            refreshData();
                        }}, {refresh_ms});
                    }} else {{
                        console.log('Auto-refresh disabled');
                    }}
                }}

                // Event listeners
                document.getElementById('autoRefresh').addEventListener('change', function(e) {{
                    autoRefreshEnabled = e.target.checked;
                    setupAutoRefresh();
                }});

                document.getElementById('timeRange').addEventListener('change', function() {{
                    refreshData();
                }});

                // Initialize
                document.addEventListener('DOMContentLoaded', function() {{
                    initCharts();
                    refreshData();
                    setupAutoRefresh();
                }});

                // Handle visibility change to pause/resume when tab is not visible
                document.addEventListener('visibilitychange', function() {{
                    if (document.hidden) {{
                        if (refreshInterval) {{
                            clearInterval(refreshInterval);
                        }}
                    }} else {{
                        setupAutoRefresh();
                    }}
                }});
            </script>
        </body></html>
        """
        return HTMLResponse(content=html)

    @app.get("/metrics", response_class=JSONResponse)
    def metrics():
        return rows_ref[-500:]

    @app.get("/stats", response_class=JSONResponse)
    def stats():
        if not rows_ref:
            return {"status": "no_data"}
        
        latest = rows_ref[-1] if rows_ref else {}
        return {
            "status": "ok",
            "total_points": len(rows_ref),
            "latest": latest,
            "uptime_minutes": len(rows_ref) * (refresh_ms / 60000),
            "config": {
                "refresh_interval_ms": refresh_ms,
                "dp_aggregation": os.getenv("DP_AGGREGATION", "mean"),
                "host": config.get("host", "unknown")
            }
        }

    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    except Exception as e:
        LOG.error(f"Web server failed to start: {e}")

def launch_web_thread(port: int, rows_ref: List[dict], refresh_ms: int, config: dict):
    t = Thread(target=start_web_server, args=(port, rows_ref, refresh_ms, config), daemon=True)
    t.start()
    LOG.info(f"Enhanced web dashboard running at http://localhost:{port} (refresh {refresh_ms/1000:.0f}s)")

# ---------------------------- CLI / Main ----------------------------
def load_config_from_env():
    if DOTENV_OK:
        load_dotenv()
    return {
        "host": os.getenv("PAN_HOST", ""),
        "username": os.getenv("PAN_USERNAME", ""),
        "password": os.getenv("PAN_PASSWORD", ""),
        "verify_ssl": env_bool("VERIFY_SSL", True),
        "interval": int(os.getenv("POLL_INTERVAL", "15")),
        "output_type": os.getenv("OUTPUT_TYPE", "CSV").upper(),
        "output_dir": os.getenv("OUTPUT_DIR", "./output"),
        "visualize": env_bool("VISUALIZATION", True),
        "web_dashboard": env_bool("WEB_DASHBOARD", True),
        "web_port": int(os.getenv("WEB_PORT", "8080")),
        "save_raw_xml": env_bool("SAVE_RAW_XML", False),
        "xml_retention_hours": int(os.getenv("XML_RETENTION_HOURS", "24")),
    }

def parse_args(defaults: dict):
    p = argparse.ArgumentParser(description="PAN-OS Live Poller + Exports + Enhanced Web Dashboard")
    p.add_argument("--host", default=defaults.get("host"))
    p.add_argument("--username", default=defaults.get("username"))
    p.add_argument("--password", default=defaults.get("password"))
    p.add_argument("--interval", type=int, default=defaults.get("interval", 15))
    p.add_argument("--output-type", choices=["CSV", "XLSX", "TXT"], default=defaults.get("output_type", "CSV"))
    p.add_argument("--output-dir", default=defaults.get("output_dir", "./output"))
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--visualize", choices=["Yes", "No"], default=("Yes" if defaults.get("visualize", True) else "No"))
    p.add_argument("--no-web", action="store_true")
    p.add_argument("--port", type=int, default=defaults.get("web_port", 8080))
    p.add_argument("--save-xml", action="store_true", help="Enable XML debug logging")
    p.add_argument("--xml-retention", type=int, default=defaults.get("xml_retention_hours", 24), 
                   help="Hours to retain XML files (default: 24)")
    return p.parse_args()

def main():
    cfg = load_config_from_env()
    args = parse_args(cfg)

    if not args.host or not (args.username and args.password):
        LOG.error("PAN_HOST, PAN_USERNAME, PAN_PASSWORD are required (via .env or CLI)")
        sys.exit(2)

    verify_ssl = False if args.no_verify else cfg.get("verify_ssl", True)
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    out_dir = ensure_output_dir(args.output_dir)
    raw_dir = ensure_output_dir(out_dir / "raw_xml")

    # XML logging configuration
    save_xml = args.save_xml or cfg.get("save_raw_xml", False)
    xml_retention = args.xml_retention
    
    if save_xml:
        LOG.info(f"XML debug logging enabled - files will be retained for {xml_retention} hours")
    else:
        LOG.info("XML debug logging disabled (set SAVE_RAW_XML=true or --save-xml to enable)")

    client = PanOSClient(args.host, verify_ssl=verify_ssl)
    LOG.info("Authenticating with PAN-OS device...")
    client.keygen(args.username, args.password)

    collector = StatsCollector(client)
    collector.set_debug_dir(raw_dir, save_xml=save_xml, retention_hours=xml_retention)

    interval = max(1, int(args.interval))
    visualize = (args.visualize.lower() == "yes")

    # Enhanced web dashboard with config
    web_config = {
        "host": args.host,
        "interval": interval,
        "dp_aggregation": os.getenv("DP_AGGREGATION", "mean"),
        "xml_logging": save_xml
    }

    if cfg.get("web_dashboard", True) and not args.no_web:
        launch_web_thread(args.port, collector.rows, int(interval * 1000), web_config)

    killer = GracefulKiller()

    LOG.info(f"🚀 Monitoring {args.host} every {interval}s")
    LOG.info(f"📊 Dashboard: http://localhost:{args.port}")
    LOG.info(f"💾 Data exports will be saved to {out_dir} on exit")
    if not verify_ssl:
        LOG.warning("⚠️  TLS certificate verification is DISABLED")

    try:
        poll_count = 0
        while not killer.kill_now:
            start = time.time()
            try:
                row = collector.poll_once()
                poll_count += 1
                
                # Enhanced logging with emojis and better formatting
                mgmt_cpu = row.get("mgmt_cpu")
                dp_cpu = row.get("data_plane_cpu") 
                throughput = row.get("throughput_mbps_total")
                pps = row.get("pps_total")
                pbuf = row.get("pbuf_util_percent")
                
                mgmt_str = f"{mgmt_cpu:.1f}%" if mgmt_cpu is not None else "N/A"
                dp_str = f"{dp_cpu:.1f}%" if dp_cpu is not None else "N/A"
                thr_str = f"{throughput:.1f}" if throughput is not None else "N/A"
                pps_str = f"{int(pps)}" if pps is not None else "N/A"
                pbuf_str = f"{pbuf:.1f}%" if pbuf is not None else "N/A"
                
                LOG.info(
                    f"[{poll_count:4d}] 🖥️  CPU: M={mgmt_str:>6} DP={dp_str:>6} | "
                    f"🌐 THR: {thr_str:>8} Mbps | 📦 PPS: {pps_str:>10} | 🔋 PBUF: {pbuf_str:>6}"
                )
                
            except Exception as e:
                LOG.error(f"❌ Poll {poll_count + 1} failed: {e}")
                
            elapsed = time.time() - start
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
                
    except KeyboardInterrupt:
        LOG.info("🛑 Received interrupt signal, shutting down gracefully...")
    finally:
        # Final cleanup and exports
        LOG.info("📁 Performing final data export and cleanup...")
        try:
            write_outputs(collector.rows, out_dir, args.output_type)
        except Exception as e:
            LOG.error(f"❌ Final export failed: {e}")
            
        if visualize:
            try:
                render_charts(collector.rows, out_dir)
            except Exception as e:
                LOG.error(f"❌ Chart rendering failed: {e}")
                
        # Final XML cleanup if enabled
        if save_xml:
            try:
                cleanup_old_xml_files(raw_dir, xml_retention)
                LOG.info(f"🧹 Final XML cleanup completed")
            except Exception as e:
                LOG.error(f"❌ XML cleanup failed: {e}")
                
        LOG.info("✅ Shutdown complete. All data has been saved.")

if __name__ == "__main__":
    main()