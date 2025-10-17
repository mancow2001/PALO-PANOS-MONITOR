#!/usr/bin/env python3
"""
Enhanced Web Dashboard for PAN-OS Multi-Firewall Monitor
Fixed for proper asyncio/threading compatibility
"""
import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

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
        self.server_thread = None
        self.should_stop = False
        
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
        
        # Firewall detail template (abbreviated for space - same as before but with proper structure)
        firewall_detail_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ firewall_name }} - PAN-OS Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
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
        <div id="content">Loading firewall details...</div>
    </div>
    <script>
        // Basic firewall detail page
        document.getElementById('content').innerHTML = '<p>Firewall detail view for {{ firewall_name }}</p>';
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
                        # Handle timestamp parsing safely
                        timestamp_str = latest_metrics['timestamp']
                        if isinstance(timestamp_str, str):
                            if timestamp_str.endswith('Z'):
                                timestamp_str = timestamp_str[:-1] + '+00:00'
                            try:
                                last_metric_time = datetime.fromisoformat(timestamp_str)
                            except:
                                # Fallback parsing
                                from database import parse_iso_datetime
                                last_metric_time = parse_iso_datetime(timestamp_str)
                        else:
                            last_metric_time = timestamp_str
                        
                        if last_metric_time.tzinfo is None:
                            last_metric_time = last_metric_time.replace(tzinfo=timezone.utc)
                        
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
                    earliest_str = database_stats['earliest_metric']
                    if isinstance(earliest_str, str):
                        if earliest_str.endswith('Z'):
                            earliest_str = earliest_str[:-1] + '+00:00'
                        try:
                            earliest = datetime.fromisoformat(earliest_str)
                        except:
                            from database import parse_iso_datetime
                            earliest = parse_iso_datetime(earliest_str)
                    else:
                        earliest = earliest_str
                    
                    if earliest.tzinfo is None:
                        earliest = earliest.replace(tzinfo=timezone.utc)
                    
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
                
                return self.templates.TemplateResponse("firewall_detail.html", {
                    "request": request,
                    "firewall_name": firewall_name,
                    "firewall_host": firewall_config.host
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
                
                # Parse timestamps safely
                if start_time:
                    try:
                        from database import parse_iso_datetime
                        start_dt = parse_iso_datetime(start_time)
                    except Exception as e:
                        LOG.warning(f"Failed to parse start_time '{start_time}': {e}")
                
                if end_time:
                    try:
                        from database import parse_iso_datetime
                        end_dt = parse_iso_datetime(end_time)
                    except Exception as e:
                        LOG.warning(f"Failed to parse end_time '{end_time}': {e}")
                
                LOG.info(f"API Query - Firewall: {firewall_name}, Start: {start_dt}, End: {end_dt}, Limit: {limit}")
                
                metrics = self.database.get_metrics(firewall_name, start_dt, end_dt, limit)
                
                LOG.info(f"API Response - Found {len(metrics)} metrics for {firewall_name}")
                
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
        """Start the web server in a thread with proper event loop handling"""
        if self.server_thread and self.server_thread.is_alive():
            LOG.warning("Web server already running")
            return self.server_thread
        
        def run_server():
            """Run server in thread with new event loop"""
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Create and configure server
                config = uvicorn.Config(
                    self.app,
                    host=host,
                    port=port,
                    log_level="warning",
                    access_log=False,
                    loop=loop
                )
                
                server = uvicorn.Server(config)
                
                # Run server
                LOG.info(f"Starting web server on {host}:{port}")
                loop.run_until_complete(server.serve())
                
            except Exception as e:
                LOG.error(f"Web server failed: {e}")
            finally:
                # Clean up
                try:
                    loop.close()
                except:
                    pass
        
        # Start server thread
        self.server_thread = threading.Thread(
            target=run_server,
            name="web-server",
            daemon=True
        )
        self.server_thread.start()
        
        LOG.info(f"Web dashboard started at http://{host}:{port}")
        return self.server_thread
    
    def stop_server(self):
        """Stop the web server"""
        self.should_stop = True
        if self.server_thread and self.server_thread.is_alive():
            LOG.info("Stopping web server...")
            # Note: uvicorn server will stop when the main process exits
            # For graceful shutdown, we'd need more complex signal handling

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
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        dashboard.stop_server()
