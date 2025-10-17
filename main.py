#!/usr/bin/env python3
"""
PAN-OS Multi-Firewall Monitor - Main Application
Enhanced modular version with persistent storage and multi-firewall support
"""
import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

# Import our modules
from config import ConfigManager, FirewallConfig, create_example_config
from database import MetricsDatabase
from collectors import MultiFirewallCollector
from web_dashboard import WebDashboard

LOG = logging.getLogger("panos_monitor.main")

class GracefulKiller:
    """Handle graceful shutdown on SIGINT/SIGTERM"""
    def __init__(self):
        self.kill_now = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
    
    def exit_gracefully(self, *_):
        self.kill_now = True

class PanOSMonitorApp:
    """Main application class"""
    
    def __init__(self, config_file: str = "config.yaml"):
        self.config_manager = ConfigManager(config_file)
        self.database: Optional[MetricsDatabase] = None
        self.collector_manager: Optional[MultiFirewallCollector] = None
        self.web_dashboard: Optional[WebDashboard] = None
        self.killer = GracefulKiller()
        
        # Setup logging
        self._setup_logging()
        
        # Validate configuration
        self._validate_configuration()
        
        # Initialize components
        self._initialize_components()
    
    def _setup_logging(self):
        """Configure logging"""
        log_level = getattr(logging, self.config_manager.global_config.log_level.upper(), logging.INFO)
        
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        LOG.info(f"Logging configured at {self.config_manager.global_config.log_level} level")
    
    def _validate_configuration(self):
        """Validate configuration and report errors"""
        errors = self.config_manager.validate_config()
        if errors:
            LOG.error("Configuration validation failed:")
            for error in errors:
                LOG.error(f"  - {error}")
            sys.exit(1)
        
        enabled_firewalls = self.config_manager.get_enabled_firewalls()
        if not enabled_firewalls:
            LOG.warning("No enabled firewalls found in configuration")
        else:
            LOG.info(f"Configuration valid - {len(enabled_firewalls)} enabled firewalls")
    
    def _initialize_components(self):
        """Initialize database, collectors, and web dashboard"""
        # Initialize database
        db_path = self.config_manager.global_config.database_path
        LOG.info(f"Initializing database: {db_path}")
        self.database = MetricsDatabase(db_path)
        
        # Initialize output directory
        output_dir = Path(self.config_manager.global_config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        LOG.info(f"Output directory: {output_dir}")
        
        # Initialize collector manager
        enabled_firewalls = self.config_manager.get_enabled_firewalls()
        if enabled_firewalls:
            LOG.info(f"Initializing collectors for {len(enabled_firewalls)} firewalls")
            self.collector_manager = MultiFirewallCollector(
                enabled_firewalls,
                output_dir,
                self.database
            )
        
        # Initialize web dashboard
        if self.config_manager.global_config.web_dashboard:
            LOG.info("Initializing web dashboard")
            self.web_dashboard = WebDashboard(
                self.database,
                self.config_manager,
                self.collector_manager
            )
    
    def start(self):
        """Start the monitoring application"""
        LOG.info("🚀 Starting PAN-OS Multi-Firewall Monitor")
        
        enabled_firewalls = self.config_manager.get_enabled_firewalls()
        
        # Start web dashboard if enabled
        if self.web_dashboard:
            port = self.config_manager.global_config.web_port
            self.web_dashboard.start_server(port=port)
            LOG.info(f"📊 Web dashboard available at http://localhost:{port}")
        
        # Start data collection if we have firewalls
        if self.collector_manager and enabled_firewalls:
            self.collector_manager.start_collection()
            LOG.info(f"📡 Started monitoring {len(enabled_firewalls)} firewalls:")
            for name, config in enabled_firewalls.items():
                LOG.info(f"  - {name}: {config.host} (interval: {config.poll_interval}s)")
        else:
            LOG.warning("No enabled firewalls to monitor")
        
        # Database cleanup on startup
        if self.database:
            cleanup_days = 30  # Keep 30 days of data by default
            deleted = self.database.cleanup_old_metrics(cleanup_days)
            if deleted > 0:
                LOG.info(f"🧹 Cleaned up {deleted} old metrics (older than {cleanup_days} days)")
        
        LOG.info("✅ All services started successfully")
        
        # Main monitoring loop
        self._run_monitoring_loop()
    
    def stop(self):
        """Stop all services gracefully"""
        LOG.info("🛑 Stopping PAN-OS Multi-Firewall Monitor...")
        
        # Stop data collection
        if self.collector_manager:
            self.collector_manager.stop_collection()
        
        # Export final data if configured
        if self.database and self.config_manager.global_config.output_type:
            try:
                self._export_final_data()
            except Exception as e:
                LOG.error(f"Failed to export final data: {e}")
        
        LOG.info("✅ Shutdown complete")
    
    def _run_monitoring_loop(self):
        """Main monitoring loop"""
        try:
            # Print status periodically
            status_interval = 300  # 5 minutes
            last_status_time = 0
            
            while not self.killer.kill_now:
                current_time = time.time()
                
                # Print status every 5 minutes
                if current_time - last_status_time >= status_interval:
                    self._print_status()
                    last_status_time = current_time
                
                # Sleep for 1 second
                time.sleep(1)
                
        except KeyboardInterrupt:
            LOG.info("Received interrupt signal")
        finally:
            self.stop()
    
    def _print_status(self):
        """Print current monitoring status"""
        if not self.collector_manager:
            return
        
        status = self.collector_manager.get_collector_status()
        active_count = sum(1 for s in status.values() if s['thread_alive'])
        
        LOG.info(f"📊 Status: {active_count}/{len(status)} collectors active")
        
        for name, collector_status in status.items():
            if collector_status['authenticated'] and collector_status['thread_alive']:
                last_poll = collector_status['last_poll']
                poll_count = collector_status['poll_count']
                if last_poll:
                    LOG.info(f"  ✅ {name}: {poll_count} polls, last: {last_poll}")
                else:
                    LOG.info(f"  🟡 {name}: {poll_count} polls, starting up...")
            else:
                LOG.warning(f"  ❌ {name}: inactive or authentication failed")
    
    def _export_final_data(self):
        """Export data on shutdown"""
        if not self.database:
            return
        
        output_dir = Path(self.config_manager.global_config.output_dir)
        output_type = self.config_manager.global_config.output_type
        
        LOG.info(f"📁 Exporting final data in {output_type} format")
        
        # Export data for each firewall
        for firewall_name in self.config_manager.list_firewalls():
            try:
                # Get all metrics for this firewall
                metrics = self.database.export_metrics_to_dict(firewall_name)
                if not metrics:
                    continue
                
                # Export based on configured format
                if output_type.upper() == "CSV":
                    self._export_to_csv(firewall_name, metrics, output_dir)
                elif output_type.upper() == "XLSX":
                    self._export_to_xlsx(firewall_name, metrics, output_dir)
                else:
                    self._export_to_txt(firewall_name, metrics, output_dir)
                
            except Exception as e:
                LOG.error(f"Failed to export data for {firewall_name}: {e}")
        
        # Generate visualizations if enabled
        if self.config_manager.global_config.visualization:
            self._generate_visualizations(output_dir)
    
    def _export_to_csv(self, firewall_name: str, metrics: list, output_dir: Path):
        """Export metrics to CSV format"""
        if not PANDAS_OK:
            LOG.warning("pandas not available for CSV export")
            return
        try:
            df = pd.DataFrame(metrics)
            if not df.empty:
                file_path = output_dir / f"{firewall_name}_metrics.csv"
                df.to_csv(file_path, index=False)
                LOG.info(f"📄 Exported {len(df)} records to {file_path}")
        except Exception as e:
            LOG.error(f"Failed to export CSV for {firewall_name}: {e}")
    
    def _export_to_xlsx(self, firewall_name: str, metrics: list, output_dir: Path):
        """Export metrics to Excel format"""
        if not PANDAS_OK:
            LOG.warning("pandas not available for Excel export")
            return
        try:
            df = pd.DataFrame(metrics)
            if not df.empty:
                file_path = output_dir / f"{firewall_name}_metrics.xlsx"
                with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                    df.to_excel(writer, sheet_name="metrics", index=False)
                LOG.info(f"📊 Exported {len(df)} records to {file_path}")
        except Exception as e:
            LOG.error(f"Failed to export Excel for {firewall_name}: {e}")
    
    def _export_to_txt(self, firewall_name: str, metrics: list, output_dir: Path):
        """Export metrics to text format"""
        try:
            file_path = output_dir / f"{firewall_name}_metrics.txt"
            with open(file_path, 'w') as f:
                for metric in metrics:
                    f.write(str(metric) + "\n")
            LOG.info(f"📝 Exported {len(metrics)} records to {file_path}")
        except Exception as e:
            LOG.error(f"Failed to export TXT for {firewall_name}: {e}")
    
    def _generate_visualizations(self, output_dir: Path):
        """Generate visualization charts"""
        if not MATPLOTLIB_OK:
            LOG.warning("matplotlib not available for visualization generation")
            return
        if not PANDAS_OK:
            LOG.warning("pandas not available for visualization generation")
            return
            
        try:
            for firewall_name in self.config_manager.list_firewalls():
                metrics = self.database.export_metrics_to_dict(firewall_name)
                if not metrics:
                    continue
                
                df = pd.DataFrame(metrics)
                if df.empty:
                    continue
                
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.sort_values('timestamp', inplace=True)
                
                # Create charts directory
                charts_dir = output_dir / "charts" / firewall_name
                charts_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate individual charts
                self._create_chart(df, 'mgmt_cpu', 'Management CPU (%)', charts_dir / "mgmt_cpu.png")
                self._create_chart(df, 'data_plane_cpu_mean', 'Data Plane CPU Mean (%)', charts_dir / "dp_cpu_mean.png")
                self._create_chart(df, 'data_plane_cpu_max', 'Data Plane CPU Max (%)', charts_dir / "dp_cpu_max.png")
                self._create_chart(df, 'data_plane_cpu_p95', 'Data Plane CPU P95 (%)', charts_dir / "dp_cpu_p95.png")
                self._create_chart(df, 'throughput_mbps_total', 'Throughput (Mbps)', charts_dir / "throughput.png")
                self._create_chart(df, 'pps_total', 'Packets per Second', charts_dir / "pps.png")
                self._create_chart(df, 'pbuf_util_percent', 'Packet Buffer (%)', charts_dir / "packet_buffer.png")
                
                LOG.info(f"📈 Generated charts for {firewall_name} in {charts_dir}")
                
        except Exception as e:
            LOG.error(f"Failed to generate visualizations: {e}")
    
    def _create_chart(self, df, column: str, title: str, file_path: Path):
        """Create and save a single chart"""
        if column not in df.columns or df[column].isna().all():
            return
        
        try:
            plt.figure(figsize=(12, 6))
            plt.plot(df['timestamp'], df[column], linewidth=2)
            plt.title(title)
            plt.xlabel('Time')
            plt.ylabel(title.split('(')[-1].rstrip(')') if '(' in title else 'Value')
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(file_path, dpi=150, bbox_inches='tight')
            plt.close()
        except Exception as e:
            LOG.error(f"Failed to create chart {title}: {e}")

def create_config_command(args):
    """Create example configuration file"""
    config_file = args.config_file or "config.yaml"
    config_path = Path(config_file)
    
    if config_path.exists() and not args.force:
        print(f"Configuration file {config_file} already exists. Use --force to overwrite.")
        return 1
    
    example_content = create_example_config()
    config_path.write_text(example_content)
    print(f"Created example configuration file: {config_file}")
    print("Edit this file to configure your firewalls and start monitoring.")
    return 0

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="PAN-OS Multi-Firewall Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Start monitoring with default config.yaml
  %(prog)s --config custom.yaml     # Use custom configuration file
  %(prog)s create-config             # Create example configuration file
  %(prog)s --port 9090               # Override web dashboard port
        """
    )
    
    # Global arguments
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Configuration file path (default: config.yaml)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        help="Override web dashboard port"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # create-config command
    config_parser = subparsers.add_parser(
        "create-config",
        help="Create example configuration file"
    )
    config_parser.add_argument(
        "--config-file",
        help="Configuration file to create (default: config.yaml)"
    )
    config_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configuration file"
    )
    
    args = parser.parse_args()
    
    # Handle subcommands
    if args.command == "create-config":
        return create_config_command(args)
    
    # Check if configuration file exists
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Configuration file {args.config} not found.")
        print(f"Create one with: {sys.argv[0]} create-config")
        return 1
    
    try:
        # Create and start application
        app = PanOSMonitorApp(args.config)
        
        # Apply command line overrides
        if args.port:
            app.config_manager.global_config.web_port = args.port
        
        if args.log_level:
            app.config_manager.global_config.log_level = args.log_level
            # Re-setup logging with new level
            app._setup_logging()
        
        # Start the application
        app.start()
        
    except KeyboardInterrupt:
        LOG.info("Received interrupt signal")
        return 0
    except Exception as e:
        LOG.error(f"Application failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
