# PAN-OS Multi-Firewall Monitor

A comprehensive real-time monitoring solution for multiple Palo Alto Networks firewalls with persistent data storage, enhanced web dashboard, and intelligent timezone handling.

## 🚀 What's New in This Version

### **Major Enhancements**
- **Multi-Firewall Support**: Monitor multiple firewalls simultaneously with individual configurations
- **Persistent Data Storage**: SQLite database ensures data survives application restarts
- **Enhanced Web Dashboard**: 
  - Overview page listing all monitored firewalls
  - Detailed firewall views with customizable date/time ranges
  - Real-time CPU aggregation toggles (Mean/Max/P95)
  - CSV download functionality for filtered data
- **Intelligent Timezone Handling**: Automatic detection and conversion between local and UTC times
- **Modular Architecture**: Clean separation across multiple Python modules for better maintainability

### **Key Improvements**
- **All CPU Aggregation Methods**: Automatically collects Mean, Max, and P95 data plane CPU metrics
- **Interactive Time Filtering**: Select specific date/time ranges with proper timezone conversion
- **Comprehensive Data Export**: Download filtered CSV data with all aggregation methods included
- **Persistent Configuration**: YAML-based configuration with validation and hot-reload capabilities
- **Database-Driven**: All metrics stored in SQLite with automatic cleanup and retention management

## 📁 Project Structure

```
panos-monitor/
├── main.py              # Main application entry point
├── config.py            # Configuration management
├── database.py          # Data persistence layer (SQLite)
├── collectors.py        # Multi-threaded data collection
├── web_dashboard.py     # Enhanced web interface
├── config.yaml          # YAML configuration file
├── requirements.txt     # Python dependencies
├── data/                # Database storage
│   └── metrics.db       # SQLite database
├── output/              # Exports and logs
│   ├── charts/          # Generated visualizations
│   └── raw_xml/         # Debug XML files (optional)
└── templates/           # Web dashboard templates (auto-generated)
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
  log_level: "INFO"

# Multiple firewall configurations
firewalls:
  datacenter_fw:
    host: "https://10.100.192.3"
    username: "admin"
    password: "YourPassword"
    verify_ssl: false
    enabled: true
    poll_interval: 60
  
  branch_fw:
    host: "https://192.168.1.1"
    username: "admin"
    password: "BranchPassword"
    verify_ssl: false
    enabled: true
    poll_interval: 30
```

### Configuration Options

#### Global Settings
- `output_dir`: Directory for exports and logs
- `output_type`: Export format (CSV, XLSX, TXT)
- `database_path`: SQLite database location
- `web_dashboard`: Enable/disable web interface
- `web_port`: Web dashboard port
- `visualization`: Generate PNG charts on export
- `save_raw_xml`: Enable XML debug logging
- `log_level`: Logging verbosity (DEBUG, INFO, WARNING, ERROR)

#### Firewall Settings
- `host`: Firewall management URL (include https://)
- `username`/`password`: API credentials
- `verify_ssl`: SSL certificate verification
- `enabled`: Enable/disable monitoring for this firewall
- `poll_interval`: Polling frequency in seconds (minimum 1)

**Note**: `dp_aggregation` is no longer needed! The system now automatically collects Mean, Max, and P95 for all firewalls. You can toggle between views in the web dashboard.

### Legacy Support: .env (Optional)

For backward compatibility, you can still use `.env` files for single firewall configurations:

```bash
# Single firewall configuration (legacy mode)
PAN_HOST=https://10.100.192.3
PAN_USERNAME=admin
PAN_PASSWORD=YourPassword
VERIFY_SSL=false
POLL_INTERVAL=60

# Global settings
OUTPUT_TYPE=CSV
OUTPUT_DIR=./output
WEB_DASHBOARD=Yes
WEB_PORT=8080
DATABASE_PATH=./data/metrics.db
```

## 🚀 Usage

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

For production environments, use the automated installation script that deploys the monitor as a systemd daemon service:

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
    poll_interval: 60

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

#### **Installation Script Options**

```bash
sudo ./installation.sh              # Install the service
sudo ./installation.sh --uninstall  # Uninstall with data options
sudo ./installation.sh -u           # Uninstall (short form)
sudo ./installation.sh --test       # Test existing installation
sudo ./installation.sh --help       # Show help information
```

#### **Production Deployment Benefits**

- 🔒 **Security**: Runs under dedicated non-root user with systemd hardening
- 🔄 **Reliability**: Auto-restart on failure, starts on boot
- 📝 **Logging**: Centralized logging with automatic rotation
- 🛠️ **Management**: Easy service control with helper scripts
- 🏗️ **Structure**: Organized file layout following Linux standards
- 🧹 **Maintenance**: Clean uninstall with data preservation options

### Manual Installation (Development/Testing)

For development or testing purposes, you can still run the monitor manually:

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create configuration
python main.py create-config

# Edit configuration
nano config.yaml

# Run manually
python main.py
```

### Command Line Options

```bash
python main.py --help                    # Show help
python main.py create-config             # Create example config
python main.py create-config --force     # Overwrite existing config
python main.py --config custom.yaml     # Use custom config file
python main.py --port 9090              # Override web port
python main.py --log-level DEBUG        # Set log level
```

### Access Web Dashboard

1. **Main Dashboard**: `http://localhost:8080`
   - Overview of all monitored firewalls
   - Status indicators and latest metrics
   - Links to detailed firewall views

2. **Firewall Details**: `http://localhost:8080/firewall/firewall_name`
   - Detailed metrics for specific firewall
   - Customizable date/time range selection
   - Interactive charts with timezone conversion
   - CPU aggregation method toggle (Mean/Max/P95)
   - CSV download for filtered data

## 📊 Enhanced Features

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

### **Enhanced CPU Monitoring**
- **All Aggregation Methods**: Automatically collects Mean, Max, and P95
- **Real-time Toggle**: Switch between aggregation views instantly
- **Better Insights**: 
  - Mean: Overall system health
  - Max: Identify bottlenecks
  - P95: Capacity planning

### **Advanced Data Export**
- **Filtered CSV Downloads**: Export exactly what you're viewing
- **Comprehensive Data**: All CPU methods, timestamps, and metrics
- **Smart Filenames**: Descriptive names with firewall and date range
- **Format Options**: CSV, XLSX, TXT with optional visualizations

## 💾 Data Persistence

### SQLite Database
- **Automatic Schema**: Creates tables and indexes automatically
- **Efficient Storage**: Optimized for time-series data
- **Data Retention**: Configurable cleanup of old metrics
- **Migration Support**: Easily import existing CSV data

### Database Schema
```sql
-- Firewall registry
CREATE TABLE firewalls (
    name TEXT UNIQUE NOT NULL,
    host TEXT NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Enhanced metrics with all CPU aggregation methods
CREATE TABLE metrics (
    firewall_name TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    mgmt_cpu REAL,
    data_plane_cpu_mean REAL,
    data_plane_cpu_max REAL,
    data_plane_cpu_p95 REAL,
    throughput_mbps_total REAL,
    pps_total REAL,
    pbuf_util_percent REAL,
    -- ... additional fields
);
```

## 🌐 Enhanced Web Dashboard

### Main Dashboard Features
- **Firewall Grid**: Visual overview of all monitored firewalls
- **System Statistics**: Total metrics, database size, uptime tracking
- **Status Indicators**: Live monitoring with animated status dots
- **Quick Metrics**: Latest CPU, throughput, and buffer data for each firewall

### Firewall Detail Features
- **Interactive Charts**: CPU, throughput, packet buffer, and PPS
- **Time Range Controls**: Custom start/end date and time selection
- **CPU Aggregation Toggle**: Switch between Mean/Max/P95 views
- **Data Point Limits**: Choose 100-5000 points or all available data
- **CSV Download**: Export filtered data with comprehensive metrics
- **Auto-refresh**: Configurable with manual override
- **Responsive Design**: Works on desktop and mobile

### API Endpoints
- `GET /`: Main dashboard
- `GET /firewall/{name}`: Firewall detail page
- `GET /api/firewall/{name}/metrics`: JSON metrics with filtering
- `GET /api/firewalls`: List all firewalls
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
- **CPU Components**: User, System, Idle percentages from `show system resources`
- **Total Management CPU**: Combined user + system percentage

### Data Plane (Enhanced)
- **CPU Mean**: Average across all cores (overall health)
- **CPU Max**: Highest loaded core (bottleneck detection)
- **CPU P95**: 95th percentile (capacity planning)
- **Dynamic Detection**: Auto-discovers all processors and cores
- **Maximum Values**: Uses peak CPU values, not averages

### Network Performance
- **Throughput**: Total Mbps from session statistics
- **Packets Per Second**: Real-time PPS monitoring
- **Packet Buffer**: Maximum buffer utilization across processors

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

### Debug Mode

Enable detailed logging:
```yaml
global:
  log_level: "DEBUG"
  save_raw_xml: true
  xml_retention_hours: 1
```

## 📚 Performance and Scaling

### Resource Usage
- **Memory**: ~50MB base + ~2KB per firewall per metric (includes all aggregations)
- **Database Growth**: ~2KB per firewall per poll (comprehensive metrics)
- **CPU**: Minimal impact, scales linearly with firewall count
- **Network**: 3 API calls per firewall per poll interval

### Scaling Guidelines
- **Small deployment**: 1-10 firewalls, 30-60 second intervals
- **Medium deployment**: 10-50 firewalls, 60-120 second intervals  
- **Large deployment**: 50+ firewalls, consider multiple instances or longer intervals

### Database Maintenance
```python
# Automatic cleanup (runs on startup)
deleted = database.cleanup_old_metrics(days_to_keep=30)

# Manual maintenance
from database import MetricsDatabase
db = MetricsDatabase("./data/metrics.db")
stats = db.get_database_stats()
print(f"Database size: {stats['database_size_mb']} MB")
```

## 🆕 What's Different from Original Version

### **Removed Dependencies**
- **Single .env configuration** → Multi-firewall YAML configuration
- **Single firewall limitation** → Unlimited firewall support
- **Memory-only storage** → Persistent SQLite database
- **Fixed CPU aggregation** → Dynamic aggregation with real-time switching

### **New Requirements**
- **PyYAML**: For YAML configuration parsing
- **Enhanced database schema**: Additional columns for CPU aggregation methods
- **Modular architecture**: Multiple Python files instead of single script

### **Backward Compatibility**
- **Legacy .env support**: Still works for single firewall setups
- **Same API endpoints**: Core monitoring API unchanged
- **Configuration migration**: Easy upgrade path from old version

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

# 4. Start monitoring
python main.py

# 5. Access dashboards
# Main: http://localhost:8080
# Firewall detail: http://localhost:8080/firewall/your_firewall_name

# 6. Use enhanced features
# - Toggle CPU aggregation methods in web interface
# - Set custom date/time ranges with timezone conversion
# - Download filtered CSV data
# - Monitor multiple firewalls simultaneously
```

**Happy Multi-Firewall Monitoring! 🔥📊✨**
