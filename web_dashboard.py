#!/usr/bin/env python3
"""
Enhanced Web Dashboard for PAN-OS Multi-Firewall Monitor
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from threading import Thread

try:
    from fastapi import FastAPI, Request, Query, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    import uvicorn
    FASTAPI_OK = True
except ImportError:
    FASTAPI_OK = False

LOG = logging.getLogger("panos_monitor.web")

class WebDashboard:
    """Enhanced web dashboard for multi-firewall monitoring"""
    
    def __init__(self, database, config_manager, collector_manager=None):
        if not FASTAPI_OK:
            raise RuntimeError("FastAPI not available - install with: pip install fastapi uvicorn jinja2")
        
        self.database = database
        self.config_manager = config_manager
        self.collector_manager = collector_manager
        self.app = FastAPI(title="PAN-OS Multi-Firewall Monitor")
        
        # Setup templates directory
        self.templates_dir = Path(__file__).parent / "templates"
        self.templates_dir.mkdir(exist_ok=True)
        self.templates = Jinja2Templates(directory=str(self.templates_dir))
        
        self._create_templates()
        self._setup_routes()
    
    def _create_templates(self):
        """Create HTML templates"""
        # Main dashboard template
        dashboard_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PAN-OS Multi-Firewall Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
        }
        .header h1 {
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 2.2em;
            font-weight: 700;
        }
        .firewall-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .firewall-card {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
            transition: transform 0.2s ease;
        }
        .firewall-card:hover { transform: translateY(-5px); }
        .firewall-name {
            font-size: 1.4em;
            font-weight: 600;
            margin-bottom: 10px;
            color: #2c3e50;
        }
        .firewall-host {
            font-size: 0.9em;
            color: #7f8c8d;
            margin-bottom: 15px;
        }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-online { background: #27ae60; animation: pulse 2s infinite; }
        .status-offline { background: #e74c3c; }
        .status-unknown { background: #95a5a6; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .metrics-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
            gap: 10px;
            margin: 15px 0;
        }
        .metric-item {
            text-align: center;
            padding: 8px;
            background: rgba(52, 152, 219, 0.1);
            border-radius: 8px;
        }
        .metric-label {
            font-size: 0.8em;
            color: #7f8c8d;
            margin-bottom: 4px;
        }
        .metric-value {
            font-size: 1.1em;
            font-weight: 600;
            color: #2c3e50;
        }
        .view-button {
            display: inline-block;
            padding: 10px 20px;
            background: #3498db;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 500;
            transition: background 0.2s ease;
            margin-top: 15px;
        }
        .view-button:hover { 
            background: #2980b9; 
            text-decoration: none;
            color: white;
        }
        .stats-section {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }
        .stats-section h2 {
            color: #2c3e50;
            margin-bottom: 20px;
            font-size: 1.5em;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        .stat-card {
            text-align: center;
            padding: 15px;
            background: rgba(52, 152, 219, 0.1);
            border-radius: 10px;
        }
        .stat-number {
            font-size: 2em;
            font-weight: 700;
            margin-bottom: 5px;
            color: #2980b9;
        }
        .stat-label {
            font-size: 0.9em;
            color: #7f8c8d;
        }
        .cpu-high { color: #e74c3c; }
        .cpu-medium { color: #f39c12; }
        .cpu-low { color: #27ae60; }
        .no-firewalls {
            text-align: center;
            padding: 40px;
        }
        .no-firewalls h2 {
            color: #2c3e50;
            margin-bottom: 10px;
        }
        .no-firewalls p {
            color: #7f8c8d;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔥 PAN-OS Multi-Firewall Monitor</h1>
            <p>Real-time monitoring dashboard for multiple Palo Alto Networks firewalls</p>
        </div>

        {% if database_stats %}
        <div class="stats-section">
            <h2>📊 System Statistics</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">{{ database_stats.total_metrics }}</div>
                    <div class="stat-label">Total Metrics</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ firewalls|length }}</div>
                    <div class="stat-label">Monitored Firewalls</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ database_stats.database_size_mb }}</div>
                    <div class="stat-label">Database Size (MB)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ uptime_hours }}</div>
                    <div class="stat-label">Uptime (Hours)</div>
                </div>
            </div>
        </div>
        {% endif %}

        <div class="firewall-grid">
            {% for firewall in firewalls %}
            <div class="firewall-card">
                <div class="firewall-name">
                    <span class="status-indicator {{ firewall.status_class }}"></span>
                    {{ firewall.name }}
                </div>
                <div class="firewall-host">{{ firewall.host }}</div>
                
                {% if firewall.latest_metrics %}
                <div class="metrics-summary">
                    <div class="metric-item">
                        <div class="metric-label">Mgmt CPU</div>
                        <div class="metric-value {{ firewall.mgmt_cpu_class }}">
                            {{ "%.1f"|format(firewall.latest_metrics.mgmt_cpu or 0) }}%
                        </div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">DP CPU</div>
                        <div class="metric-value {{ firewall.dp_cpu_class }}">
                            {{ "%.1f"|format(firewall.latest_metrics.data_plane_cpu or 0) }}%
                        </div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">Throughput</div>
                        <div class="metric-value">
                            {{ "%.0f"|format(firewall.latest_metrics.throughput_mbps_total or 0) }} Mbps
                        </div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">PPS</div>
                        <div class="metric-value">
                            {{ "{:,.0f}".format(firewall.latest_metrics.pps_total or 0) }}
                        </div>
                    </div>
                </div>
                
                <p style="font-size: 0.8em; color: #7f8c8d; margin: 10px 0;">
                    Last updated: {{ firewall.last_update }}
                </p>
                {% else %}
                <p style="color: #e74c3c;">No metrics available</p>
                {% endif %}
                
                <a href="/firewall/{{ firewall.name }}" class="view-button">
                    📊 View Details
                </a>
            </div>
            {% endfor %}
        </div>

        {% if not firewalls %}
        <div class="stats-section">
            <div class="no-firewalls">
                <h2>No Firewalls Configured</h2>
                <p>Add firewall configurations to start monitoring.</p>
            </div>
        </div>
        {% endif %}
    </div>

    <script>
        // Auto-refresh every 60 seconds
        setTimeout(() => {
            window.location.reload();
        }, 30000);
    </script>
</body>
</html>
        """
        
        # Firewall detail template
        firewall_detail_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ firewall_name }} - PAN-OS Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
        }
        .header h1 {
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 2.2em;
            font-weight: 700;
        }
        .breadcrumb {
            margin-bottom: 15px;
        }
        .breadcrumb a {
            color: #3498db;
            text-decoration: none;
        }
        .breadcrumb a:hover { text-decoration: underline; }
        .controls {
            background: rgba(255,255,255,0.95);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            display: flex;
            gap: 20px;
            align-items: center;
            flex-wrap: wrap;
            box-shadow: 0 4px 16px rgba(0,0,0,0.1);
        }
        .control-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .control-group label {
            font-weight: 500;
            color: #2c3e50;
        }
        .control-group input, .control-group select {
            padding: 8px 12px;
            border: 1px solid #bdc3c7;
            border-radius: 5px;
            background: white;
        }
        button {
            padding: 10px 20px;
            background: #3498db;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-weight: 500;
        }
        button:hover { background: #2980b9; }
        .current-values {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .value-card {
            background: rgba(255,255,255,0.95);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 4px 16px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
            transition: transform 0.2s ease;
        }
        .value-card:hover { transform: translateY(-2px); }
        .value-label {
            font-size: 0.9em;
            color: #7f8c8d;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .value-number {
            font-size: 2em;
            font-weight: 700;
            margin-bottom: 5px;
        }
        .value-unit {
            font-size: 0.9em;
            color: #95a5a6;
            font-weight: 500;
        }
        .cpu-high { color: #e74c3c; }
        .cpu-medium { color: #f39c12; }
        .cpu-low { color: #27ae60; }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .metric-card {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
        }
        .metric-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .metric-title {
            font-size: 1.3em;
            font-weight: 600;
            color: #2c3e50;
        }
        .chart-container {
            position: relative;
            height: 300px;
            margin-top: 10px;
        }
        .timestamp {
            font-size: 0.9em;
            color: #7f8c8d;
            margin-top: 10px;
            text-align: center;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #7f8c8d;
        }
        .error {
            background: rgba(231, 76, 60, 0.1);
            border: 1px solid #e74c3c;
            color: #e74c3c;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .download-info {
            font-size: 0.9em;
            color: #7f8c8d;
            margin-top: 5px;
            font-style: italic;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="breadcrumb">
                <a href="/">← Back to Dashboard</a>
            </div>
            <h1>🔥 {{ firewall_name }}</h1>
            <p>{{ firewall_host }}</p>
        </div>

        <div class="controls">
            <div class="control-group">
                <label for="startDate">Start Date:</label>
                <input type="date" id="startDate" value="{{ default_start_date }}">
            </div>
            <div class="control-group">
                <label for="startTime">Start Time:</label>
                <input type="time" id="startTime" value="{{ default_start_time }}">
            </div>
            <div class="control-group">
                <label for="endDate">End Date:</label>
                <input type="date" id="endDate" value="{{ default_end_date }}">
            </div>
            <div class="control-group">
                <label for="endTime">End Time:</label>
                <input type="time" id="endTime" value="{{ default_end_time }}">
            </div>
            <div class="control-group">
                <label for="maxPoints">Max Points:</label>
                <select id="maxPoints">
                    <option value="100">100</option>
                    <option value="500" selected>500</option>
                    <option value="1000">1000</option>
                    <option value="5000">5000</option>
                    <option value="">All</option>
                </select>
            </div>
            <div class="control-group">
                <label for="cpuAggregation">DP CPU View:</label>
                <select id="cpuAggregation">
                    <option value="mean" selected>Mean (Average)</option>
                    <option value="max">Max (Hottest Core)</option>
                    <option value="p95">P95 (95th Percentile)</option>
                </select>
            </div>
            <button onclick="refreshData()">Update Charts</button>
            <button onclick="downloadCSV()" style="background: #27ae60;">📥 Download CSV</button>
            <div class="control-group">
                <input type="checkbox" id="autoRefresh" checked>
                <label for="autoRefresh">Auto Refresh (60s)</label>
            </div>
        </div>
        
        <div class="download-info">
            💡 Tip: Use the date/time filters above, then click "Update Charts" to load data, then "Download CSV" to export the filtered results.
        </div>

        <div class="current-values" id="currentValues">
            <!-- Current values will be populated by JavaScript -->
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-header">
                    <span class="metric-title">🖥️ CPU Usage</span>
                </div>
                <div class="chart-container">
                    <canvas id="cpuChart"></canvas>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-header">
                    <span class="metric-title">🚀 Network Throughput</span>
                </div>
                <div class="chart-container">
                    <canvas id="throughputChart"></canvas>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-header">
                    <span class="metric-title">📦 Packet Buffer</span>
                </div>
                <div class="chart-container">
                    <canvas id="pbufChart"></canvas>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-header">
                    <span class="metric-title">📊 Packets per Second</span>
                </div>
                <div class="chart-container">
                    <canvas id="ppsChart"></canvas>
                </div>
            </div>
        </div>

        <div class="timestamp" id="lastUpdate"></div>
    </div>

    <script>
        const firewallName = '{{ firewall_name }}';
        let charts = {};
        let autoRefreshEnabled = true;
        let refreshInterval;
        let userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        let currentCpuAggregation = 'mean';
        let lastFetchedData = []; // Store the last fetched data for CSV download

        console.log('User timezone detected:', userTimezone);

        function formatValue(value, decimals = 1) {
            if (value === null || value === undefined) return '--';
            return typeof value === 'number' ? value.toFixed(decimals) : value;
        }

        function formatTimestamp(timestamp) {
            if (!timestamp) return '--';
            const date = new Date(timestamp);
            // Format in user's local timezone
            return date.toLocaleString();
        }

        function getCpuClass(value) {
            if (value === null || value === undefined) return 'cpu-low';
            if (value > 80) return 'cpu-high';
            if (value > 60) return 'cpu-medium';
            return 'cpu-low';
        }

        function convertToUserTimezone(utcDatetimeLocal) {
            // Convert user's local datetime input to UTC for the API
            // The input is already in user's local time, so we need to convert it to UTC
            const localDate = new Date(utcDatetimeLocal);
            return localDate.toISOString();
        }

        function convertFromUserTimezone(utcDatetime) {
            // Convert UTC datetime from API to user's local time for display
            return new Date(utcDatetime);
        }

        async function fetchMetrics() {
            const startDate = document.getElementById('startDate').value;
            const startTime = document.getElementById('startTime').value;
            const endDate = document.getElementById('endDate').value;
            const endTime = document.getElementById('endTime').value;
            const maxPoints = document.getElementById('maxPoints').value;

            const params = new URLSearchParams();
            
            // Convert user's local time to UTC for the API
            if (startDate && startTime) {
                const localStart = `${startDate}T${startTime}:00`;
                const utcStart = convertToUserTimezone(localStart);
                params.append('start_time', utcStart);
            }
            if (endDate && endTime) {
                const localEnd = `${endDate}T${endTime}:59`;
                const utcEnd = convertToUserTimezone(localEnd);
                params.append('end_time', utcEnd);
            }
            if (maxPoints) {
                params.append('limit', maxPoints);
            }
            
            // Add user timezone info
            params.append('user_timezone', userTimezone);

            console.log('Fetching with params:', params.toString());

            try {
                const response = await fetch(`/api/firewall/${firewallName}/metrics?${params}`);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const data = await response.json();
                console.log('API Response:', data.length, 'records');
                if (data.length > 0) {
                    console.log('Sample timestamp (UTC):', data[0].timestamp);
                    console.log('Sample timestamp (Local):', formatTimestamp(data[0].timestamp));
                }
                
                // Store data for CSV download
                lastFetchedData = data;
                
                return data;
            } catch (error) {
                console.error('Failed to fetch metrics:', error);
                document.getElementById('currentValues').innerHTML = '<div class="error">Failed to load data: ' + error.message + '</div>';
                return [];
            }
        }

        function downloadCSV() {
            if (!lastFetchedData || lastFetchedData.length === 0) {
                alert('No data available to download. Please load some data first.');
                return;
            }

            console.log('Preparing CSV download for', lastFetchedData.length, 'records');

            // Prepare CSV headers
            const headers = [
                'Timestamp (Local)',
                'Timestamp (UTC)',
                'Firewall Name',
                'Management CPU (%)',
                'Data Plane CPU Mean (%)',
                'Data Plane CPU Max (%)',
                'Data Plane CPU P95 (%)',
                'Throughput (Mbps)',
                'Packets per Second',
                'Packet Buffer (%)',
                'CPU User (%)',
                'CPU System (%)',
                'CPU Idle (%)'
            ];

            // Prepare CSV rows
            const csvRows = [headers.join(',')];
            
            // Sort data by timestamp (oldest first for CSV)
            const sortedData = [...lastFetchedData].sort((a, b) => 
                new Date(a.timestamp) - new Date(b.timestamp)
            );

            sortedData.forEach(row => {
                const localTime = convertFromUserTimezone(row.timestamp);
                const csvRow = [
                    `"${localTime.toLocaleString()}"`,  // Local time
                    `"${row.timestamp}"`,               // UTC time
                    `"${row.firewall_name || firewallName}"`,
                    formatValue(row.mgmt_cpu) || '',
                    formatValue(row.data_plane_cpu_mean) || '',
                    formatValue(row.data_plane_cpu_max) || '',
                    formatValue(row.data_plane_cpu_p95) || '',
                    formatValue(row.throughput_mbps_total) || '',
                    formatValue(row.pps_total, 0) || '',
                    formatValue(row.pbuf_util_percent) || '',
                    formatValue(row.cpu_user) || '',
                    formatValue(row.cpu_system) || '',
                    formatValue(row.cpu_idle) || ''
                ];
                csvRows.push(csvRow.join(','));
            });

            // Create CSV content
            const csvContent = csvRows.join('\\n');

            // Generate filename with current timestamp and date range
            const now = new Date();
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            
            let filename = `${firewallName}_metrics_${now.getFullYear()}${(now.getMonth()+1).toString().padStart(2,'0')}${now.getDate().toString().padStart(2,'0')}`;
            
            if (startDate && endDate) {
                filename += `_${startDate}_to_${endDate}`;
            }
            
            filename += '.csv';

            // Create and trigger download
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            
            if (link.download !== undefined) {
                const url = URL.createObjectURL(blob);
                link.setAttribute('href', url);
                link.setAttribute('download', filename);
                link.style.visibility = 'hidden';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                
                console.log('CSV download triggered:', filename);
                
                // Show success message
                const originalButton = document.querySelector('button[onclick="downloadCSV()"]');
                const originalText = originalButton.textContent;
                originalButton.textContent = '✅ Downloaded!';
                originalButton.style.background = '#27ae60';
                
                setTimeout(() => {
                    originalButton.textContent = originalText;
                    originalButton.style.background = '#27ae60';
                }, 2000);
            } else {
                alert('CSV download is not supported in this browser.');
            }
        }

        function updateCurrentValues(data) {
            if (!data || data.length === 0) return;
            
            const latest = data[0]; // Data is sorted newest first
            const mgmtCpu = latest.mgmt_cpu;
            
            // Use selected aggregation method for DP CPU
            let dpCpu;
            switch(currentCpuAggregation) {
                case 'max':
                    dpCpu = latest.data_plane_cpu_max;
                    break;
                case 'p95':
                    dpCpu = latest.data_plane_cpu_p95;
                    break;
                default:
                    dpCpu = latest.data_plane_cpu_mean;
            }
            
            const throughput = latest.throughput_mbps_total;
            const pps = latest.pps_total;
            const pbuf = latest.pbuf_util_percent;

            const currentValuesHtml = `
                <div class="value-card">
                    <div class="value-label">Management CPU</div>
                    <div class="value-number ${getCpuClass(mgmtCpu)}">${formatValue(mgmtCpu)}</div>
                    <div class="value-unit">%</div>
                </div>
                <div class="value-card">
                    <div class="value-label">Data Plane CPU (${currentCpuAggregation.toUpperCase()})</div>
                    <div class="value-number ${getCpuClass(dpCpu)}">${formatValue(dpCpu)}</div>
                    <div class="value-unit">%</div>
                </div>
                <div class="value-card">
                    <div class="value-label">Throughput</div>
                    <div class="value-number">${formatValue(throughput)}</div>
                    <div class="value-unit">Mbps</div>
                </div>
                <div class="value-card">
                    <div class="value-label">Packets/sec</div>
                    <div class="value-number">${formatValue(pps, 0)}</div>
                    <div class="value-unit">pps</div>
                </div>
                <div class="value-card">
                    <div class="value-label">Packet Buffer</div>
                    <div class="value-number ${getCpuClass(pbuf)}">${formatValue(pbuf)}</div>
                    <div class="value-unit">%</div>
                </div>
            `;
            
            document.getElementById('currentValues').innerHTML = currentValuesHtml;
            document.getElementById('lastUpdate').textContent = `Last updated: ${formatTimestamp(latest.timestamp)}`;
        }

        function createChart(canvasId, datasets) {
            const ctx = document.getElementById(canvasId).getContext('2d');
            return new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 300 },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: { color: 'rgba(0,0,0,0.1)' },
                            ticks: { color: '#666' }
                        },
                        x: {
                            type: 'time',
                            time: {
                                displayFormats: {
                                    minute: 'HH:mm',
                                    hour: 'HH:mm',
                                    day: 'MMM dd'
                                }
                            },
                            grid: { color: 'rgba(0,0,0,0.1)' },
                            ticks: { 
                                color: '#666',
                                maxTicksLimit: 10
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { color: '#333' }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    }
                }
            });
        }

        function initCharts() {
            console.log('Initializing charts...');
            
            charts.cpu = createChart('cpuChart', [
                {
                    label: 'Management CPU (%)',
                    data: [],
                    borderColor: '#e74c3c',
                    backgroundColor: '#e74c3c20',
                    fill: false,
                    tension: 0.4
                },
                {
                    label: 'Data Plane CPU - Mean (%)',
                    data: [],
                    borderColor: '#3498db',
                    backgroundColor: '#3498db20',
                    fill: false,
                    tension: 0.4
                }
            ]);

            charts.throughput = createChart('throughputChart', [
                {
                    label: 'Throughput (Mbps)',
                    data: [],
                    borderColor: '#2ecc71',
                    backgroundColor: '#2ecc7120',
                    fill: false,
                    tension: 0.4
                }
            ]);

            charts.pbuf = createChart('pbufChart', [
                {
                    label: 'Packet Buffer (%)',
                    data: [],
                    borderColor: '#f39c12',
                    backgroundColor: '#f39c1220',
                    fill: false,
                    tension: 0.4
                }
            ]);

            charts.pps = createChart('ppsChart', [
                {
                    label: 'Packets per Second',
                    data: [],
                    borderColor: '#9b59b6',
                    backgroundColor: '#9b59b620',
                    fill: false,
                    tension: 0.4
                }
            ]);
        }

        function updateCharts(data) {
            if (!data || data.length === 0) return;
            
            console.log('Updating charts with', data.length, 'data points');
            
            // Reverse data to show oldest to newest
            const reversedData = [...data].reverse();
            
            // Convert UTC timestamps to user's local time for display
            const localTimes = reversedData.map(d => convertFromUserTimezone(d.timestamp));
            
            switch(currentCpuAggregation) {
                case 'max':
                    dpCpuData = reversedData.map(d => d.data_plane_cpu_max || 0);
                    dpCpuLabel = 'Data Plane CPU - Max (%)';
                    break;
                case 'p95':
                    dpCpuData = reversedData.map(d => d.data_plane_cpu_p95 || 0);
                    dpCpuLabel = 'Data Plane CPU - P95 (%)';
                    break;
                default:
                    dpCpuData = reversedData.map(d => d.data_plane_cpu_mean || 0);
                    dpCpuLabel = 'Data Plane CPU - Mean (%)';
            }
            
            // CPU Chart
            if (charts.cpu) {
                charts.cpu.data.labels = localTimes;
                charts.cpu.data.datasets[0].data = reversedData.map(d => d.mgmt_cpu || 0);
                charts.cpu.data.datasets[1].data = dpCpuData;
                charts.cpu.data.datasets[1].label = dpCpuLabel;
                charts.cpu.update('active');
            }
            
            // Throughput Chart
            if (charts.throughput) {
                charts.throughput.data.labels = localTimes;
                charts.throughput.data.datasets[0].data = reversedData.map(d => d.throughput_mbps_total || 0);
                charts.throughput.update('active');
            }
            
            // Packet Buffer Chart
            if (charts.pbuf) {
                charts.pbuf.data.labels = localTimes;
                charts.pbuf.data.datasets[0].data = reversedData.map(d => d.pbuf_util_percent || 0);
                charts.pbuf.update('active');
            }
            
            // PPS Chart
            if (charts.pps) {
                charts.pps.data.labels = localTimes;
                charts.pps.data.datasets[0].data = reversedData.map(d => d.pps_total || 0);
                charts.pps.update('active');
            }
        }

        async function refreshData() {
            console.log('Fetching data...');
            const data = await fetchMetrics();
            console.log('Data received:', data.length, 'points');
            
            if (data && data.length > 0) {
                updateCurrentValues(data);
                updateCharts(data);
            } else {
                console.warn('No data received');
            }
        }

        function setupAutoRefresh() {
            if (refreshInterval) {
                clearInterval(refreshInterval);
                refreshInterval = null;
            }
            
            if (autoRefreshEnabled) {
                refreshInterval = setInterval(refreshData, 60000); // 60 seconds
            }
        }

        // Event listeners
        document.getElementById('autoRefresh').addEventListener('change', function(e) {
            autoRefreshEnabled = e.target.checked;
            setupAutoRefresh();
        });

        // CPU Aggregation selector
        document.getElementById('cpuAggregation').addEventListener('change', function(e) {
            currentCpuAggregation = e.target.value;
            console.log('CPU aggregation changed to:', currentCpuAggregation);
            // Refresh the data to update charts and current values
            refreshData();
        });

        // Add event listeners for date/time controls
        document.getElementById('startDate').addEventListener('change', function() {
            console.log('Start date changed to:', this.value);
        });
        
        document.getElementById('endDate').addEventListener('change', function() {
            console.log('End date changed to:', this.value);
        });
        
        document.getElementById('startTime').addEventListener('change', function() {
            console.log('Start time changed to:', this.value);
        });
        
        document.getElementById('endTime').addEventListener('change', function() {
            console.log('End time changed to:', this.value);
        });
        
        document.getElementById('maxPoints').addEventListener('change', function() {
            console.log('Max points changed to:', this.value);
        });

        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Page loaded, initializing...');
            initCharts();
            refreshData();
            setupAutoRefresh();
        });

        // Handle visibility change to pause/resume when tab is not visible
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                if (refreshInterval) {
                    clearInterval(refreshInterval);
                }
            } else {
                setupAutoRefresh();
            }
        });
    </script>
</body>
</html>
        """
        
        # Write templates to files
        (self.templates_dir / "dashboard.html").write_text(dashboard_html)
        (self.templates_dir / "firewall_detail.html").write_text(firewall_detail_html)
        
        LOG.info(f"Created templates in {self.templates_dir}")
    
    def _setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.get("/", response_class=HTMLResponse)
        async def dashboard(request: Request):
            """Main dashboard showing all firewalls"""
            try:
                # Get all firewalls from database
                db_firewalls = self.database.get_all_firewalls()
                
                # Get database stats
                database_stats = self.database.get_database_stats()
                
                # Prepare firewall data for template
                firewalls = []
                for fw_data in db_firewalls:
                    name = fw_data['name']
                    
                    # Get latest metrics
                    latest_metrics_list = self.database.get_latest_metrics(name, 1)
                    latest_metrics = latest_metrics_list[0] if latest_metrics_list else None
                    
                    # Determine status
                    status_class = "status-unknown"
                    last_update = "Never"
                    
                    if latest_metrics:
                        last_metric_time = datetime.fromisoformat(latest_metrics['timestamp'].replace('Z', '+00:00'))
                        time_diff = datetime.now(timezone.utc) - last_metric_time
                        
                        if time_diff.total_seconds() < 300:  # 5 minutes
                            status_class = "status-online"
                        else:
                            status_class = "status-offline"
                        
                        last_update = last_metric_time.strftime("%Y-%m-%d %H:%M:%S")
                    
                    # CPU status classes
                    mgmt_cpu_class = "cpu-low"
                    dp_cpu_class = "cpu-low"
                    
                    if latest_metrics:
                        mgmt_cpu = latest_metrics.get('mgmt_cpu', 0) or 0
                        dp_cpu = latest_metrics.get('data_plane_cpu', 0) or 0
                        
                        if mgmt_cpu > 80:
                            mgmt_cpu_class = "cpu-high"
                        elif mgmt_cpu > 60:
                            mgmt_cpu_class = "cpu-medium"
                        
                        if dp_cpu > 80:
                            dp_cpu_class = "cpu-high"
                        elif dp_cpu > 60:
                            dp_cpu_class = "cpu-medium"
                    
                    firewalls.append({
                        'name': name,
                        'host': fw_data['host'],
                        'status_class': status_class,
                        'latest_metrics': latest_metrics,
                        'last_update': last_update,
                        'mgmt_cpu_class': mgmt_cpu_class,
                        'dp_cpu_class': dp_cpu_class
                    })
                
                # Calculate uptime
                uptime_hours = 0
                if database_stats.get('earliest_metric'):
                    earliest = datetime.fromisoformat(database_stats['earliest_metric'].replace('Z', '+00:00'))
                    uptime_hours = int((datetime.now(timezone.utc) - earliest).total_seconds() / 3600)
                
                return self.templates.TemplateResponse("dashboard.html", {
                    "request": request,
                    "firewalls": firewalls,
                    "database_stats": database_stats,
                    "uptime_hours": uptime_hours
                })
                
            except Exception as e:
                LOG.error(f"Dashboard error: {e}")
                return HTMLResponse(f"<h1>Error loading dashboard</h1><p>{e}</p>", status_code=500)
        
        @self.app.get("/firewall/{firewall_name}", response_class=HTMLResponse)
        async def firewall_detail(request: Request, firewall_name: str):
            """Detailed view for a specific firewall"""
            try:
                # Get firewall config
                firewall_config = self.config_manager.get_firewall(firewall_name)
                if not firewall_config:
                    raise HTTPException(status_code=404, detail="Firewall not found")
                
                # Default date range and times based on user's current time
                now = datetime.now()
                end_date = now.strftime("%Y-%m-%d")
                start_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                
                # Default times - use current time range (last hour) in user's timezone
                default_end_time = now.strftime("%H:%M")
                default_start_time = (now - timedelta(hours=1)).strftime("%H:%M")
                
                return self.templates.TemplateResponse("firewall_detail.html", {
                    "request": request,
                    "firewall_name": firewall_name,
                    "firewall_host": firewall_config.host,
                    "default_start_date": start_date,
                    "default_end_date": end_date,
                    "default_start_time": default_start_time,
                    "default_end_time": default_end_time
                })
                
            except Exception as e:
                LOG.error(f"Firewall detail error: {e}")
                return HTMLResponse(f"<h1>Error loading firewall details</h1><p>{e}</p>", status_code=500)
        
        @self.app.get("/api/firewall/{firewall_name}/metrics")
        async def get_firewall_metrics(
            firewall_name: str,
            start_time: Optional[str] = Query(None),
            end_time: Optional[str] = Query(None),
            limit: Optional[int] = Query(500),
            user_timezone: Optional[str] = Query(None)
        ):
            """API endpoint to get metrics for a specific firewall"""
            try:
                start_dt = None
                end_dt = None
                
                # Parse start_time (convert from user's local time to UTC)
                if start_time:
                    try:
                        if 'T' in start_time:
                            # Full datetime string
                            start_dt = datetime.fromisoformat(start_time)
                            if start_dt.tzinfo is None:
                                # No timezone specified, treat as user's local time
                                start_dt = start_dt.replace(tzinfo=timezone.utc)
                        else:
                            # Date only, add time
                            start_dt = datetime.fromisoformat(f"{start_time}T00:00:00")
                            start_dt = start_dt.replace(tzinfo=timezone.utc)
                    except Exception as e:
                        LOG.warning(f"Failed to parse start_time '{start_time}': {e}")
                
                # Parse end_time (convert from user's local time to UTC)
                if end_time:
                    try:
                        if 'T' in end_time:
                            # Full datetime string
                            end_dt = datetime.fromisoformat(end_time)
                            if end_dt.tzinfo is None:
                                # No timezone specified, treat as user's local time
                                end_dt = end_dt.replace(tzinfo=timezone.utc)
                        else:
                            # Date only, add time
                            end_dt = datetime.fromisoformat(f"{end_time}T23:59:59")
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                    except Exception as e:
                        LOG.warning(f"Failed to parse end_time '{end_time}': {e}")
                
                LOG.info(f"API Query - Firewall: {firewall_name}, Start: {start_dt}, End: {end_dt}, Limit: {limit}")
                
                metrics = self.database.get_metrics(firewall_name, start_dt, end_dt, limit)
                
                # Debug: show actual timestamps in database for this firewall
                if len(metrics) == 0 and (start_dt or end_dt):
                    # Get some recent timestamps to help debug
                    recent_metrics = self.database.get_latest_metrics(firewall_name, 3)
                    if recent_metrics:
                        LOG.info(f"Debug - Recent timestamps for {firewall_name}:")
                        for i, m in enumerate(recent_metrics):
                            LOG.info(f"  {i+1}. {m.get('timestamp', 'No timestamp')}")
                    else:
                        LOG.info(f"Debug - No metrics found for firewall: {firewall_name}")
                
                LOG.info(f"API Response - Found {len(metrics)} metrics for {firewall_name}")
                
                # Convert timestamps to user's timezone for display
                # Note: The frontend JavaScript will handle timezone conversion
                return JSONResponse(metrics)
                
            except Exception as e:
                LOG.error(f"API metrics error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/firewalls")
        async def get_all_firewalls():
            """API endpoint to get all firewalls"""
            try:
                firewalls = self.database.get_all_firewalls()
                return JSONResponse(firewalls)
            except Exception as e:
                LOG.error(f"API firewalls error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/status")
        async def get_system_status():
            """API endpoint to get system status"""
            try:
                status = {
                    "database_stats": self.database.get_database_stats(),
                    "config": {
                        "firewalls": len(self.config_manager.firewalls),
                        "enabled_firewalls": len(self.config_manager.get_enabled_firewalls())
                    }
                }
                
                if self.collector_manager:
                    status["collectors"] = self.collector_manager.get_collector_status()
                
                return JSONResponse(status)
            except Exception as e:
                LOG.error(f"API status error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
    
    def start_server(self, host: str = "0.0.0.0", port: int = 8080):
        """Start the web server"""
        def run_server():
            try:
                uvicorn.run(
                    self.app,
                    host=host,
                    port=port,
                    log_level="warning",
                    access_log=False
                )
            except Exception as e:
                LOG.error(f"Web server failed to start: {e}")
        
        server_thread = Thread(target=run_server, daemon=True, name="web-server")
        server_thread.start()
        LOG.info(f"Web dashboard started at http://{host}:{port}")
        return server_thread

if __name__ == "__main__":
    # Example usage
    from database import MetricsDatabase
    from config import ConfigManager
    
    # Create test database and config
    db = MetricsDatabase("test.db")
    config_manager = ConfigManager("test_config.yaml")
    
    # Create dashboard
    dashboard = WebDashboard(db, config_manager)
    
    print("Starting test web server...")
    dashboard.start_server(port=8080)
    
    import time
    time.sleep(5)
    print("Test server running at http://localhost:8080")
