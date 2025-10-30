#!/usr/bin/env python3
"""
Enhanced Web Dashboard for PAN-OS Multi-Firewall Monitor with Interface Monitoring
Adds interface bandwidth and session statistics monitoring alongside existing features
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

LOG = logging.getLogger("panos_monitor.enhanced_web")

class EnhancedWebDashboard:
    """Enhanced web dashboard with interface monitoring capabilities"""
    
    def __init__(self, database, config_manager, collector_manager=None):
        if not FASTAPI_OK:
            raise RuntimeError("FastAPI not available - install with: pip install fastapi uvicorn jinja2")
        
        self.database = database
        self.config_manager = config_manager
        self.collector_manager = collector_manager
        self.app = FastAPI(title="Enhanced PAN-OS Multi-Firewall Monitor")
        self.server_thread = None
        self.should_stop = False
        
        # Setup templates directory
        self.templates_dir = Path(__file__).parent / "templates"
        self.templates_dir.mkdir(exist_ok=True)
        self.templates = Jinja2Templates(directory=str(self.templates_dir))
        
        self._verify_templates()
        self._setup_enhanced_routes()
    
    def _verify_templates(self):
        """Verify HTML templates exist in the templates directory"""
        
        # Check if templates exist
        dashboard_path = self.templates_dir / "dashboard.html"
        detail_path = self.templates_dir / "firewall_detail.html"
        
        if not dashboard_path.exists():
            LOG.error(f"Dashboard template not found at {dashboard_path}")
            LOG.error("Please ensure dashboard.html exists in the templates directory")
            raise FileNotFoundError(f"Required template not found: {dashboard_path}")
        else:
            LOG.info(f"Using dashboard template: {dashboard_path}")
        
        if not detail_path.exists():
            LOG.error(f"Firewall detail template not found at {detail_path}")
            LOG.error("Please ensure firewall_detail.html exists in the templates directory")
            raise FileNotFoundError(f"Required template not found: {detail_path}")
        else:
            LOG.info(f"Using firewall detail template: {detail_path}")
        
        LOG.info(f"Templates directory: {self.templates_dir}")
        LOG.info("All required templates found successfully")
    
    def _setup_enhanced_routes(self):
        """Setup enhanced FastAPI routes with interface monitoring"""
        
        @self.app.get("/", response_class=HTMLResponse)
        async def enhanced_dashboard(request: Request):
            """Enhanced main dashboard showing all firewalls with interface data"""
            try:
                # Get all firewalls from database
                db_firewalls = self.database.get_all_firewalls()
                
                # Get enhanced database stats
                database_stats = self.database.get_database_stats()
                
                # Prepare enhanced firewall data for template
                firewalls = []
                for fw_data in db_firewalls:
                    name = fw_data['name']
                    
                    # Get latest metrics
                    latest_metrics_list = self.database.get_latest_metrics(name, 1)
                    latest_metrics = latest_metrics_list[0] if latest_metrics_list else None
                    
                    # Get interface summary using enhanced configuration
                    interface_summary = None
                    if hasattr(self.database, 'get_interface_metrics'):
                        try:
                            # Get available interfaces from database
                            available_interfaces = self.database.get_available_interfaces(name)
                            
                            # Get firewall config to determine which interfaces should be monitored
                            firewall_config = self.config_manager.get_firewall(name)
                            monitored_interfaces = []
                            
                            if firewall_config and hasattr(firewall_config, 'should_monitor_interface'):
                                # Use config logic to filter interfaces
                                monitored_interfaces = [
                                    iface for iface in available_interfaces
                                    if firewall_config.should_monitor_interface(iface)
                                ]
                            else:
                                # Fallback to all available interfaces
                                monitored_interfaces = available_interfaces
                            
                            total_rx = 0
                            total_tx = 0
                            
                            for interface_name in monitored_interfaces:
                                interface_metrics = self.database.get_interface_metrics(name, interface_name, limit=1)
                                if interface_metrics:
                                    latest_interface = interface_metrics[0]
                                    total_rx += latest_interface.get('rx_mbps', 0) or 0
                                    total_tx += latest_interface.get('tx_mbps', 0) or 0
                            
                            if total_rx > 0 or total_tx > 0 or len(monitored_interfaces) > 0:
                                interface_summary = {
                                    'total_rx': total_rx,
                                    'total_tx': total_tx,
                                    'interface_count': len(monitored_interfaces),
                                    'monitored_interfaces': monitored_interfaces[:3],  # Show first 3
                                    'total_interfaces': len(available_interfaces)
                                }
                        except Exception as e:
                            LOG.debug(f"Could not get enhanced interface summary for {name}: {e}")
                    
                    # Get session summary
                    session_summary = None
                    if hasattr(self.database, 'get_session_statistics'):
                        try:
                            session_stats = self.database.get_session_statistics(name, limit=1)
                            if session_stats:
                                latest_session = session_stats[0]
                                session_summary = {
                                    'active_sessions': latest_session.get('active_sessions', 0),
                                    'max_sessions': latest_session.get('max_sessions', 0),
                                    'session_utilization': (latest_session.get('active_sessions', 0) / max(latest_session.get('max_sessions', 1), 1)) * 100
                                }
                        except Exception as e:
                            LOG.debug(f"Could not get session summary for {name}: {e}")
                    
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
                        'interface_summary': interface_summary,
                        'session_summary': session_summary,
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
                LOG.error(f"Enhanced dashboard error: {e}")
                import traceback
                traceback.print_exc()
                return HTMLResponse(f"<h1>Error loading enhanced dashboard</h1><p>{e}</p>", status_code=500)
        
        @self.app.get("/firewall/{firewall_name}", response_class=HTMLResponse)
        async def enhanced_firewall_detail(request: Request, firewall_name: str):
            """Enhanced detailed view for a specific firewall"""
            try:
                # Get firewall config
                firewall_config = self.config_manager.get_firewall(firewall_name)
                if not firewall_config:
                    raise HTTPException(status_code=404, detail="Firewall not found")
                
                # Default date range and times
                now = datetime.now()
                end_date = now.strftime("%Y-%m-%d")
                start_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                
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
                LOG.error(f"Enhanced firewall detail error: {e}")
                import traceback
                traceback.print_exc()
                return HTMLResponse(f"<h1>Error loading enhanced firewall details</h1><p>{e}</p>", status_code=500)
        
        @self.app.get("/api/firewall/{firewall_name}/metrics")
        async def get_firewall_metrics(
            firewall_name: str,
            start_time: Optional[str] = Query(None),
            end_time: Optional[str] = Query(None),
            limit: Optional[int] = Query(500),
            user_timezone: Optional[str] = Query(None)
        ):
            """API endpoint to get metrics for a specific firewall (existing)"""
            try:
                start_dt = None
                end_dt = None
                
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
                
                metrics = self.database.get_metrics(firewall_name, start_dt, end_dt, limit)
                return JSONResponse(metrics)
                
            except Exception as e:
                LOG.error(f"API metrics error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/firewall/{firewall_name}/interfaces")
        async def get_firewall_interfaces(
            firewall_name: str,
            start_time: Optional[str] = Query(None),
            end_time: Optional[str] = Query(None),
            limit: Optional[int] = Query(500),
            user_timezone: Optional[str] = Query(None)
        ):
            """NEW: API endpoint to get interface metrics for a specific firewall"""
            try:
                if not hasattr(self.database, 'get_interface_metrics'):
                    raise HTTPException(status_code=501, detail="Interface metrics not supported")
                
                start_dt = None
                end_dt = None
                
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
                
                # Get all available interfaces for this firewall
                available_interfaces = self.database.get_available_interfaces(firewall_name)
                
                # Get metrics for each interface
                interface_data = {}
                for interface_name in available_interfaces:
                    metrics = self.database.get_interface_metrics(
                        firewall_name, interface_name, start_dt, end_dt, limit
                    )
                    if metrics:
                        interface_data[interface_name] = metrics
                
                LOG.info(f"Interface API - Found {len(interface_data)} interfaces for {firewall_name}")
                LOG.debug(f"Interface API - Available interfaces: {available_interfaces}")
                return JSONResponse(interface_data)
                
            except Exception as e:
                LOG.error(f"API interface metrics error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/firewall/{firewall_name}/interface-config")
        async def get_firewall_interface_config(firewall_name: str):
            """NEW: API endpoint to get interface configuration for a firewall"""
            try:
                # Get firewall config from config manager
                firewall_config = self.config_manager.get_firewall(firewall_name)
                if not firewall_config:
                    raise HTTPException(status_code=404, detail="Firewall not found")
                
                # Get available interfaces from database
                available_interfaces = []
                if hasattr(self.database, 'get_available_interfaces'):
                    available_interfaces = self.database.get_available_interfaces(firewall_name)
                
                # Get configured interfaces
                configured_interfaces = []
                if hasattr(firewall_config, 'interface_configs') and firewall_config.interface_configs:
                    configured_interfaces = [
                        {
                            'name': ic.name,
                            'display_name': ic.display_name,
                            'enabled': ic.enabled,
                            'description': ic.description
                        }
                        for ic in firewall_config.interface_configs
                    ]
                
                # Get simple monitor list
                monitor_interfaces = []
                if hasattr(firewall_config, 'monitor_interfaces') and firewall_config.monitor_interfaces:
                    monitor_interfaces = firewall_config.monitor_interfaces
                
                # Get enabled interfaces using firewall config logic
                enabled_interfaces = []
                if hasattr(firewall_config, 'get_enabled_interfaces'):
                    enabled_interfaces = firewall_config.get_enabled_interfaces()
                
                config_info = {
                    'firewall_name': firewall_name,
                    'interface_monitoring': getattr(firewall_config, 'interface_monitoring', False),
                    'auto_discover_interfaces': getattr(firewall_config, 'auto_discover_interfaces', False),
                    'configured_interfaces': configured_interfaces,
                    'monitor_interfaces': monitor_interfaces,
                    'enabled_interfaces': enabled_interfaces,
                    'available_interfaces': available_interfaces,
                    'exclude_interfaces': getattr(firewall_config, 'exclude_interfaces', [])
                }
                
                LOG.debug(f"Interface config for {firewall_name}: {len(enabled_interfaces)} enabled, {len(available_interfaces)} available")
                return JSONResponse(config_info)
                
            except Exception as e:
                LOG.error(f"API interface config error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/firewall/{firewall_name}/sessions")
        async def get_firewall_sessions(
            firewall_name: str,
            start_time: Optional[str] = Query(None),
            end_time: Optional[str] = Query(None),
            limit: Optional[int] = Query(500),
            user_timezone: Optional[str] = Query(None)
        ):
            """NEW: API endpoint to get session statistics for a specific firewall"""
            try:
                if not hasattr(self.database, 'get_session_statistics'):
                    raise HTTPException(status_code=501, detail="Session statistics not supported")
                
                start_dt = None
                end_dt = None
                
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
                
                session_stats = self.database.get_session_statistics(firewall_name, start_dt, end_dt, limit)
                
                LOG.info(f"Session API - Found {len(session_stats)} session records for {firewall_name}")
                return JSONResponse(session_stats)
                
            except Exception as e:
                LOG.error(f"API session statistics error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/firewalls")
        async def get_all_firewalls():
            """API endpoint to get all firewalls (existing)"""
            try:
                firewalls = self.database.get_all_firewalls()
                return JSONResponse(firewalls)
            except Exception as e:
                LOG.error(f"API firewalls error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/status")
        async def get_enhanced_system_status():
            """Enhanced API endpoint to get system status"""
            try:
                status = {
                    "database_stats": self.database.get_database_stats(),
                    "config": {
                        "firewalls": len(self.config_manager.firewalls),
                        "enabled_firewalls": len(self.config_manager.get_enabled_firewalls())
                    },
                    "enhanced_monitoring": True
                }
                
                if self.collector_manager:
                    status["collectors"] = self.collector_manager.get_collector_status()
                
                return JSONResponse(status)
            except Exception as e:
                LOG.error(f"API enhanced status error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
    
    def start_server(self, host: str = "0.0.0.0", port: int = 8080):
        """Start the enhanced web server in a thread"""
        if self.server_thread and self.server_thread.is_alive():
            LOG.warning("Enhanced web server already running")
            return self.server_thread
        
        def run_server():
            """Run enhanced server in thread with new event loop"""
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
                LOG.info(f"Starting enhanced web server on {host}:{port}")
                loop.run_until_complete(server.serve())
                
            except Exception as e:
                LOG.error(f"Enhanced web server failed: {e}")
            finally:
                # Clean up
                try:
                    loop.close()
                except:
                    pass
        
        # Start server thread
        self.server_thread = threading.Thread(
            target=run_server,
            name="enhanced-web-server",
            daemon=True
        )
        self.server_thread.start()
        
        LOG.info(f"Enhanced web dashboard started at http://{host}:{port}")
        return self.server_thread
    
    def stop_server(self):
        """Stop the enhanced web server"""
        self.should_stop = True
        if self.server_thread and self.server_thread.is_alive():
            LOG.info("Stopping enhanced web server...")

# Maintain backward compatibility
class WebDashboard(EnhancedWebDashboard):
    """Backward compatibility alias for the enhanced web dashboard"""
    pass

if __name__ == "__main__":
    # Example usage
    from database import EnhancedMetricsDatabase
    from config import ConfigManager
    
    # Create test database and config
    db = EnhancedMetricsDatabase("test_enhanced.db")
    config_manager = ConfigManager("test_config.yaml")
    
    # Create enhanced dashboard
    dashboard = EnhancedWebDashboard(db, config_manager)
    
    print("Starting enhanced web server...")
    dashboard.start_server(port=8080)
    
    import time
    time.sleep(5)
    print("Enhanced server running at http://localhost:8080")
    print("Features:")
    print("- Session-based throughput monitoring (existing)")
    print("- Accurate interface bandwidth tracking (NEW)")
    print("- Session statistics monitoring (NEW)")
    print("- Enhanced dashboard with interface summaries (NEW)")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        dashboard.stop_server()

