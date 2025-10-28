# PAN-OS Multi-Firewall Monitor

A comprehensive real-time monitoring solution for multiple Palo Alto Networks firewalls with persistent data storage, enhanced web dashboard, intelligent timezone handling, and **per-second session sampling for accurate throughput metrics**.

## 🚀 What's New in This Version

### **Major Enhancements**
- **Multi-Firewall Support**: Monitor multiple firewalls simultaneously with individual configurations
- **Persistent Data Storage**: SQLite database ensures data survives application restarts
- **Per-Second Session Sampling**: Continuous background sampling of session info for accurate throughput and PPS capture
- **Enhanced Web Dashboard**: 
  - Overview page listing all monitored firewalls
  - Detailed firewall views with customizable date/time ranges
  - Real-time CPU aggregation toggles (Mean/Max/P95)
  - Enhanced throughput and PPS statistics (Mean/Max/Min/P95)
  - CSV download functionality for filtered data with comprehensive metrics
- **Intelligent Timezone Handling**: Automatic detection and conversion between local and UTC times
- **Modular Architecture**: Clean separation across multiple Python modules for better maintainability
- **Automatic Schema Migration**: Database automatically adds new columns for enhanced statistics

### **Key Improvements**
- **All CPU Aggregation Methods**: Automatically collects Mean, Max, and P95 data plane CPU metrics
- **Per-Second Sampling**: Background threads sample session info every second for accurate metrics
- **Enhanced Throughput/PPS Metrics**: Automatically computes Mean, Max, Min, and P95 for both throughput and packets per second
- **Interactive Time Filtering**: Select specific date/time ranges with proper timezone conversion
- **Comprehensive Data Export**: Download filtered CSV data with all statistics (8+ metrics per data point)
- **Persistent Configuration**: YAML-based configuration with validation and hot-reload capabilities
- **Database-Driven**: All metrics stored in SQLite with automatic cleanup and retention management
- **Sampling Quality Metadata**: Track sample count, success rate, and sampling period for quality assessment

## 📁 Project Structure
```
panos-monitor/
├── main.py              # Main application entry point
├── config.py            # Configuration management
├── database.py          # Data persistence layer (SQLite) with auto-migration
├── collectors.py        # Multi-threaded data collection with per-second sampling
├── web_dashboard.py     # Enhanced web interface (FastAPI)
├── config.yaml          # YAML configuration file
├── requirements.txt     # Python dependencies
├── data/                # Database storage
│   └── metrics.db       # SQLite database (auto-created)
├── output/              # Exports and logs
│   ├── charts/          # Generated visualizations
│   └── raw_xml/         # Debug XML files (optional)
└── templates/           # Web dashboard templates (auto-generated)
    ├── dashboard.html   # Main dashboard
    └── firewall_detail.html  # Detailed metrics view
```

## 🔧 Installation

### Prerequisites
- Python 3.7+
- Access to PAN-OS device API (API keys generated automatically)

### Step 1: Download Files

Download all the modular Python files:
- `main.py`
- `config.py` 
- `database.py`
- `collectors.py`
- `web_dashboard.py`
- `requirements.txt`

### Step 2: Create Python Virtual Environment

**On Linux/macOS:**
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate
```

**On Windows:**
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate
```

You should see `(venv)` prefix in your terminal prompt when activated.

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Create Configuration
```bash
# Generate example configuration file
python main.py create-config

# Edit the configuration file with your firewall details
nano config.yaml  # or use your preferred editor
```

## ⚙️ Configuration

### Primary Configuration: config.yaml (Recommended)
```yaml
# Global settings
global:
  output_dir: "./output"
  output_type: "CSV"
  database_path: "./data/metrics.db"
  web_dashboard: true
  web_port: 8080
  visualization: true
  save_raw_xml: false
  xml_retention_hours: 24
  log_level: "INFO"

# Multiple firewall configurations
firewalls:
  datacenter_fw:
    host: "https://10.100.192.3"
    username: "admin"
    password: "YourPassword"
    verify_ssl: false
    enabled: true
    poll_interval: 60  # Recommended: 15-30 seconds for accurate throughput
  
  branch_fw:
    host: "https://192.168.1.1"
    username: "admin"
    password: "BranchPassword"
    verify_ssl: false
    enabled: true
    poll_interval: 30   # Shorter interval captures traffic bursts better
```

### Configuration Options

#### Global Settings
- `output_dir`: Directory for exports and logs
- `output_type`: Export format (CSV, XLSX, TXT)
- `database_path`: SQLite database location
- `web_dashboard`: Enable/disable web interface
- `web_port`: Web dashboard port
- `visualization`: Generate PNG charts on export
- `save_raw_xml`: Enable XML debug logging (for troubleshooting)
- `xml_retention_hours`: How long to keep XML debug files
- `log_level`: Logging verbosity (DEBUG, INFO, WARNING, ERROR)

#### Firewall Settings
- `host`: Firewall management URL (include https://)
- `username`/`password`: API credentials
- `verify_ssl`: SSL certificate verification
- `enabled`: Enable/disable monitoring for this firewall
- `poll_interval`: Polling frequency in seconds (recommended: 15-30 for throughput capture)

**Performance Tip**: Use `poll_interval: 15-30` seconds to capture traffic bursts and transient events accurately. The per-second sampling will then aggregate these periods into meaningful statistics.

### Legacy Support: .env (Optional)

For backward compatibility, single firewall configurations via `.env` files are still supported:
```bash
# Single firewall configuration (legacy mode)
PAN_HOST=https://10.100.192.3
PAN_USERNAME=admin
PAN_PASSWORD=YourPassword
VERIFY_SSL=false
POLL_INTERVAL=30

# Global settings
OUTPUT_TYPE=CSV
OUTPUT_DIR=./output
WEB_DASHBOARD=Yes
WEB_PORT=8080
DATABASE_PATH=./data/metrics.db
```

## 🚀 Usage

### Manual Installation (Development/Testing)
```bash
# Start with default configuration
python main.py

# Use custom configuration file
python main.py --config custom.yaml

# Override web port
python main.py --port 9090

# Set log level
python main.py --log-level DEBUG
```

### Production Installation (Automated Service Deployment)

For production environments, use the automated installation script:

#### **Prerequisites**
- Linux system (Red Hat/CentOS/Rocky/AlmaLinux or Ubuntu/Debian)
- Root or sudo privileges
- All Python module files in the current directory

#### **Installation Process**
```bash
# 1. Make the installation script executable
chmod +x installation.sh

# 2. Run the installation (requires sudo/root)
sudo ./installation.sh
```

**What the installer does:**
- ✅ **Detects OS** and installs system dependencies (Python 3, development tools)
- ✅ **Creates dedicated user** (`panos`) for security isolation
- ✅ **Sets up directory structure** with proper permissions:
  - `/opt/panos-monitor/` - Application files and virtual environment
  - `/etc/panos-monitor/` - Configuration files
  - `/var/log/panos-monitor/` - Log files
  - `/var/lib/panos-monitor/` - Database and data storage
- ✅ **Creates Python virtual environment** with all dependencies
- ✅ **Deploys application files** with correct ownership and permissions
- ✅ **Creates systemd service** with security hardening
- ✅ **Sets up log rotation** and helper management scripts
- ✅ **Handles PEP 668 compliance** for Ubuntu 22.04+ systems

#### **Post-Installation Configuration**
```bash
# 1. Edit the configuration file
sudo nano /etc/panos-monitor/config.yaml

# 2. Configure your firewalls (example):
firewalls:
  datacenter_fw:
    host: "https://10.100.192.3"
    username: "admin"
    password: "YourPassword"
    verify_ssl: false
    enabled: true          # Set to true to enable monitoring
    poll_interval: 30      # Per-second sampling will fill gaps

# 3. Start the service
sudo systemctl start panos-monitor

# 4. Enable auto-start on boot
sudo systemctl enable panos-monitor

# 5. Check service status
panos-monitor-status
```

#### **Service Management**

The installer creates convenient management commands:
```bash
# Using helper scripts (recommended)
panos-monitor-control start     # Start the service
panos-monitor-control stop      # Stop the service
panos-monitor-control restart   # Restart the service
panos-monitor-control status    # Show status and recent logs
panos-monitor-control logs      # Follow live logs
panos-monitor-control config    # Edit configuration file

# Using systemctl directly
sudo systemctl start panos-monitor    # Start service
sudo systemctl stop panos-monitor     # Stop service
sudo systemctl restart panos-monitor  # Restart service
sudo systemctl status panos-monitor   # Check status
sudo journalctl -u panos-monitor -f   # Follow logs
```

#### **Accessing the Web Dashboard**

After installation and configuration:
```bash
# Find your server's IP address
hostname -I

# Access the dashboard
# http://YOUR-SERVER-IP:8080
```

#### **Uninstallation**
```bash
# Uninstall the service (with data preservation prompt)
sudo ./installation.sh --uninstall

# Or using short form
sudo ./installation.sh -u
```

**Uninstall options:**
- **Service only**: Removes systemd service but preserves data and configuration
- **Complete removal**: Removes everything including data, logs, and configuration files

#### **Production Deployment Benefits**

- 🔒 **Security**: Runs under dedicated non-root user with systemd hardening
- 🔄 **Reliability**: Auto-restart on failure, starts on boot
- 📝 **Logging**: Centralized logging with automatic rotation
- 🛠️ **Management**: Easy service control with helper scripts
- 🏗️ **Structure**: Organized file layout following Linux standards
- 🧹 **Maintenance**: Clean uninstall with data preservation options

## 📊 Enhanced Features

### **Per-Second Session Sampling**

The monitor continuously samples session info every second in background threads:
- **Automatic Collection**: No configuration needed
- **Background Processing**: Samples collected asynchronously
- **Aggregation**: Samples aggregated into statistics at each poll interval
- **Quality Metrics**: Track sample count, success rate, and sampling period
- **Minimal Overhead**: Uses short timeouts (5s) for fast responses

**Benefits:**
- Captures traffic bursts that occur between polls
- Reduces "averaging" effects from long poll intervals
- Provides statistical confidence via P95 and Min values
- Allows shorter poll intervals (15-30s) without network spam

### **Multi-Firewall Monitoring**
- **Independent Configuration**: Each firewall has its own polling interval and settings
- **Centralized Dashboard**: View all firewalls from one interface
- **Individual Detail Pages**: Deep dive into specific firewall metrics
- **Status Indicators**: Real-time online/offline status with color coding

### **Intelligent Timezone Handling**
- **Automatic Detection**: Uses browser timezone for input and display
- **Seamless Conversion**: Enter times in your local timezone, stored as UTC
- **Dual Timestamps**: CSV exports include both local and UTC timestamps
- **Smart Defaults**: Time ranges default to current local time

### **Enhanced Throughput and PPS Monitoring**
- **Multiple Statistics**: Automatically collects Mean, Max, Min, and P95 for both metrics
- **Per-Second Granularity**: Samples capture transient events and traffic patterns
- **Real-time Toggle**: Switch between views instantly in web dashboard
- **Better Insights**: 
  - Mean: Overall system health
  - Max: Peak performance/bottlenecks
  - Min: Minimum load
  - P95: Capacity planning and SLA validation

### **CPU Aggregation Methods**
- **All Aggregation Types**: Mean, Max, and P95 collected automatically
- **Real-time Toggle**: Switch between views instantly
- **Better Insights**:
  - Mean: Overall system health
  - Max: Identify bottlenecks (hottest core)
  - P95: Capacity planning

### **Advanced Data Export**
- **Filtered CSV Downloads**: Export exactly what you're viewing
- **Comprehensive Data**: All CPU methods, throughput statistics, PPS statistics, and timestamps
- **Smart Filenames**: Descriptive names with firewall and date range
- **Format Options**: CSV, XLSX, TXT with optional visualizations
- **Sampling Metadata**: Includes sample quality information

### **Database Schema with Auto-Migration**

The system automatically creates and updates database schema:
```sql
-- Enhanced metrics table (auto-created)
CREATE TABLE metrics (
    firewall_name TEXT,
    timestamp TIMESTAMP,
    
    -- CPU metrics
    mgmt_cpu REAL,
    data_plane_cpu_mean REAL,
    data_plane_cpu_max REAL,
    data_plane_cpu_p95 REAL,
    
    -- Throughput metrics (enhanced)
    throughput_mbps_total REAL,
    throughput_mbps_max REAL,          -- Auto-added via migration
    throughput_mbps_min REAL,          -- Auto-added via migration
    throughput_mbps_p95 REAL,          -- Auto-added via migration
    
    -- PPS metrics (enhanced)
    pps_total REAL,
    pps_max REAL,                      -- Auto-added via migration
    pps_min REAL,                      -- Auto-added via migration
    pps_p95 REAL,                      -- Auto-added via migration
    
    -- Sampling quality metrics (auto-added)
    session_sample_count INTEGER,      -- Number of per-second samples
    session_success_rate REAL,         -- Success rate (0.0-1.0)
    session_sampling_period REAL,      -- Actual sampling period (seconds)
    
    -- Other metrics
    pbuf_util_percent REAL
);
```

## 💾 Data Persistence

### SQLite Database
- **Automatic Schema**: Creates tables and indexes automatically
- **Automatic Migration**: Adds new columns for enhanced statistics on first run
- **Efficient Storage**: Optimized for time-series data
- **Data Retention**: Configurable cleanup of old metrics (default: 30 days)
- **Migration Support**: Easily import existing CSV data

### Database Maintenance
```python
# Automatic cleanup (runs on startup)
deleted = database.cleanup_old_metrics(days_to_keep=30)

# Manual maintenance
from database import MetricsDatabase
db = MetricsDatabase("./data/metrics.db")
stats = db.get_database_stats()
print(f"Database size: {stats['database_size_mb']} MB")
print(f"Total metrics: {stats['total_metrics']}")
print(f"Avg samples per poll: {stats.get('avg_samples_per_poll', 'N/A')}")
```

## 🌐 Enhanced Web Dashboard

### Main Dashboard Features
- **Firewall Grid**: Visual overview of all monitored firewalls
- **System Statistics**: Total metrics, firewall count, database size, uptime
- **Status Indicators**: Live monitoring with animated status dots
- **Quick Metrics**: Latest CPU, throughput, and buffer data for each firewall
- **Auto-Refresh**: Updates every 30 seconds by default

### Firewall Detail Features
- **Interactive Charts**: CPU, throughput (with Mean/Max/Min/P95 toggle), packet buffer, and PPS
- **Time Range Controls**: Custom start/end date and time selection with timezone conversion
- **CPU Aggregation Toggle**: Switch between Mean/Max/P95 views instantly
- **Throughput Statistics Toggle**: View Mean, Max, Min, or P95 or all at once
- **PPS Statistics Toggle**: View Mean, Max, Min, or P95 or all at once
- **Data Point Limits**: Choose 100-5000 points or all available data
- **CSV Download**: Export filtered data with all statistics included
- **Auto-refresh**: Configurable with manual override
- **Responsive Design**: Works on desktop and mobile

### API Endpoints
- `GET /`: Main dashboard
- `GET /firewall/{name}`: Firewall detail page
- `GET /api/firewall/{name}/metrics`: JSON metrics with optional filtering
- `GET /api/firewalls`: List all registered firewalls
- `GET /api/status`: System status and statistics

## 🔄 Migration from Single-File Version

### Migrating Existing Data
```python
# Import existing CSV data to new database
from database import MetricsDatabase, migrate_csv_to_database

# Create new database
db = MetricsDatabase("./data/metrics.db")

# Migrate existing CSV data
migrate_csv_to_database("old_panos_stats.csv", db, "legacy_firewall")
```

### Configuration Migration

1. **Extract settings** from old `.env` file
2. **Create new** `config.yaml` with `python main.py create-config`
3. **Update** firewall configurations in YAML format
4. **Test** with `python main.py --log-level DEBUG`

## 📈 Collected Metrics

### Management Plane
- **CPU Components**: User, System, Idle percentages
- **Total Management CPU**: Combined user + system percentage

### Data Plane (Enhanced)
- **CPU Mean**: Average across all cores (overall health)
- **CPU Max**: Highest loaded core (bottleneck detection)
- **CPU P95**: 95th percentile (capacity planning)
- **Dynamic Detection**: Auto-discovers all processors and cores

### Network Performance (Enhanced with Per-Second Sampling)
- **Throughput Mean**: Average Mbps over polling interval
- **Throughput Max**: Peak throughput captured
- **Throughput Min**: Minimum throughput observed
- **Throughput P95**: 95th percentile for SLA validation
- **PPS Mean**: Average packets per second
- **PPS Max**: Peak packets per second
- **PPS Min**: Minimum packets per second
- **PPS P95**: 95th percentile packets per second
- **Packet Buffer**: Maximum buffer utilization across processors

### Sampling Quality (New)
- **Sample Count**: Number of per-second samples collected
- **Success Rate**: Percentage of successful samples (0.0-1.0)
- **Sampling Period**: Actual duration covered by samples (seconds)

### Additional Metrics
- **Timestamps**: UTC storage with local timezone display
- **Firewall Identification**: Multi-firewall support with proper attribution

## 🔒 Security Considerations

### API Permissions
Create dedicated monitoring users with minimal permissions:
- `show system resources` (read-only)
- `show running resource-monitor` (read-only)  
- `show session info` (read-only)

### Best Practices
- **Strong Passwords**: Use complex API credentials
- **SSL Verification**: Enable certificate verification in production (`verify_ssl: true`)
- **Network Restriction**: Limit access to management interfaces
- **Credential Management**: Store sensitive data in protected configuration files
- **Regular Rotation**: Implement API key rotation policies
- **Service User**: Production deployment runs under non-root `panos` user

## 🐛 Troubleshooting

### Common Issues

#### Configuration Errors
```bash
# Validate configuration
python main.py --log-level DEBUG

# Check YAML syntax
python -c "import yaml; yaml.safe_load(open('config.yaml'))"
```

#### Database Issues
```bash
# Check database connectivity
python -c "from database import MetricsDatabase; db = MetricsDatabase('./data/metrics.db'); print('Database OK')"

# View database stats
python -c "from database import MetricsDatabase; db = MetricsDatabase('./data/metrics.db'); print(db.get_database_stats())"
```

#### Web Dashboard Issues
```bash
# Test web server startup
python main.py --port 8081 --log-level DEBUG

# Check if port is available
netstat -an | grep 8080
```

#### Timezone Issues
- **Check browser console** for timezone detection logs
- **Verify time ranges** match your expected local times
- **Use UTC times** if unsure about timezone conversion
- **Check system timezone**: `date` or `timedatectl`

#### Low Throughput Capture
- **Check poll_interval**: Use 15-30 seconds for better capture
- **Verify sampling**: Check logs for "session sampling" messages
- **Monitor quality**: Check CSV export for sample_count and success_rate
- **Network latency**: Ensure firewall API responses are fast (<1s)

### Debug Mode

Enable detailed logging:
```yaml
global:
  log_level: "DEBUG"
  save_raw_xml: true
  xml_retention_hours: 1  # Keep XML files only 1 hour in debug mode
```

Debug XML files will be saved to: `./output/raw_xml/{firewall_name}/`

## 📚 Performance and Scaling

### Resource Usage
- **Memory**: ~50MB base + ~5KB per firewall per metric (including all statistics)
- **Database Growth**: ~4KB per firewall per poll (enhanced metrics)
- **CPU**: Minimal impact, scales linearly with firewall count
- **Network**: 4 API calls per firewall per poll interval (3x system resources, 1x session info)

### Scaling Guidelines
- **Small deployment**: 1-10 firewalls, 30-60 second poll intervals
- **Medium deployment**: 10-50 firewalls, 60-120 second poll intervals  
- **Large deployment**: 50+ firewalls, consider multiple instances or longer intervals

**Note**: Per-second sampling happens independently of poll_interval, so shorter polls don't increase API pressure significantly.

### Database Maintenance
```python
# Automatic cleanup (configured to 30 days by default)
# Runs on application startup

# Manual cleanup
from database import MetricsDatabase
db = MetricsDatabase("./data/metrics.db")
deleted = db.cleanup_old_metrics(days_to_keep=30)
print(f"Deleted {deleted} old records")

# Get enhanced database stats
stats = db.get_database_stats()
print(f"Database size: {stats['database_size_mb']} MB")
print(f"Enhanced statistics: {stats.get('enhanced_statistics_available')}")
```

## 🆕 What's Different from Original Version

### **Removed/Deprecated**
- **Single .env configuration** → Multi-firewall YAML configuration
- **Single firewall limitation** → Unlimited firewall support
- **Memory-only storage** → Persistent SQLite database
- **Fixed CPU aggregation** → Dynamic aggregation with real-time switching
- **Basic throughput metrics** → Enhanced with Mean/Max/Min/P95

### **New Core Features**
- **Per-Second Session Sampling**: Background threads continuously sample session info
- **Automatic Schema Migration**: Database schema updates automatically
- **Enhanced Statistics**: Throughput and PPS now include Mean/Max/Min/P95
- **Sampling Quality Metrics**: Track sample count, success rate, and sampling period
- **Web-Based Dashboard**: Modern, responsive interface with filtering and export
- **Timezone Conversion**: Automatic browser timezone detection and conversion
- **FastAPI Backend**: RESTful API for dashboard data access

### **New Requirements**
- **PyYAML**: For YAML configuration parsing
- **FastAPI + Uvicorn**: For web dashboard
- **Jinja2**: For HTML template rendering
- **Enhanced database schema**: Additional columns for statistics
- **Modular architecture**: Multiple Python files instead of single script

### **Backward Compatibility**
- **Legacy .env support**: Still works for single firewall setups
- **Same API concepts**: Core monitoring principles unchanged
- **Configuration migration**: Easy upgrade path from old version
- **Data import**: CSV migration tools provided

## 📄 License

This monitoring solution is provided as-is for monitoring Palo Alto Networks firewalls. Refer to your PAN-OS licensing for API usage terms.

---

## 🎯 Quick Start
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create configuration
python main.py create-config

# 3. Edit config.yaml with your firewall details
nano config.yaml

# 4. Start monitoring (recommended: 15-30s poll_interval for throughput)
python main.py

# 5. Access dashboards
# Main: http://localhost:8080
# Firewall detail: http://localhost:8080/firewall/your_firewall_name

# 6. Use enhanced features
# - Per-second sampling automatically captures throughput bursts
# - Toggle CPU aggregation methods in web interface
# - Set custom date/time ranges with timezone conversion
# - Download filtered CSV with full statistics
# - Monitor multiple firewalls simultaneously
```

### **Performance Tips**

For best throughput monitoring results:
- Use **poll_interval: 15-30 seconds** to capture traffic bursts
- Per-second sampling will automatically fill gaps between polls
- Check **sample_count** and **success_rate** in exported data for quality assessment
- Use **P95 values** for SLA validation and capacity planning
- Monitor **Min values** to understand baseline traffic patterns

**Happy Multi-Firewall Monitoring! 🔥📊✨**
