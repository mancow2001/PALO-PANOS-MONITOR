# PAN-OS Live Metrics Monitor

A comprehensive real-time monitoring solution for Palo Alto Networks firewalls with live metrics collection, web dashboard, and flexible data exports.

## Features

### 📊 Real-Time Metrics Collection
- **Management Plane CPU**: User, system, and idle percentages from `show system resources`
- **Data Plane CPU**: Maximum load across all processors and cores (auto-detected)
- **Packet Buffer Utilization**: Maximum buffer usage across all data processors
- **Network Throughput**: Total Mbps from session statistics
- **Packets Per Second**: Real-time PPS monitoring

### 🎯 Key Capabilities
- **Dynamic Core Detection**: Auto-discovers all data processors and cores (no model-specific configuration needed)
- **Flexible Aggregation**: Configure DP CPU aggregation mode (mean/max/p95)
- **Enhanced Web Dashboard**: Beautiful real-time visualization with customizable time ranges
- **Multiple Export Formats**: CSV, XLSX, or TXT output on exit
- **Optional Visualizations**: Automatic PNG chart generation
- **XML Debug Logging**: Configurable raw XML capture with automatic retention management
- **Graceful Shutdown**: Clean data exports on CTRL+C or termination signals

## Installation

### Prerequisites
- Python 3.7+
- Access to PAN-OS device API (API key will be generated automatically)

### Step 1: Create Python Virtual Environment

It's recommended to use a virtual environment to avoid dependency conflicts:

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

### Step 2: Install Dependencies

With the virtual environment activated:

```bash
pip install requests python-dotenv pandas openpyxl matplotlib fastapi uvicorn jinja2
```

Or install from requirements file:
```bash
pip install -r requirements.txt
```

### Requirements.txt
```
requests
python-dotenv
pandas
openpyxl
matplotlib
fastapi
uvicorn
jinja2
```

### Deactivating Virtual Environment

When you're done:
```bash
deactivate
```

## Configuration

### Environment Variables (.env file)

Create a `.env` file in the same directory as the script:

```bash
# PAN-OS Connection
PAN_HOST=https://10.100.192.3
PAN_USERNAME=admin
PAN_PASSWORD=YourPassword
VERIFY_SSL=false

# Polling Configuration
POLL_INTERVAL=60                # Seconds between polls (default: 15)

# Data Plane CPU Aggregation
DP_AGGREGATION=mean             # Options: mean | max | p95
                                # mean: Average across all cores (default)
                                # max: Highest loaded core
                                # p95: 95th percentile

# Output Configuration
OUTPUT_TYPE=CSV                 # Options: CSV | XLSX | TXT
OUTPUT_DIR=./output
VISUALIZATION=Yes               # Generate PNG charts on exit (Yes | No)

# Web Dashboard
WEB_DASHBOARD=Yes               # Enable web interface (Yes | No)
WEB_PORT=8080                   # Dashboard port

# Debug Options
SAVE_RAW_XML=false              # Save raw API responses (true | false)
XML_RETENTION_HOURS=24          # Hours to keep XML files (default: 24)
```

### Command Line Arguments

Override environment variables with CLI arguments:

```bash
python panos_monitor.py --host https://firewall.example.com \
                        --username admin \
                        --password secret \
                        --interval 30 \
                        --output-type CSV \
                        --output-dir ./data \
                        --visualize Yes \
                        --port 8080 \
                        --save-xml \
                        --xml-retention 48
```

#### Available Arguments
- `--host`: PAN-OS device URL
- `--username`: API username
- `--password`: API password
- `--interval`: Polling interval in seconds
- `--output-type`: Export format (CSV, XLSX, TXT)
- `--output-dir`: Output directory path
- `--no-verify`: Disable SSL certificate verification
- `--visualize`: Generate charts (Yes/No)
- `--no-web`: Disable web dashboard
- `--port`: Web dashboard port
- `--save-xml`: Enable XML debug logging
- `--xml-retention`: Hours to retain XML files

## Usage

### Basic Usage
```bash
python panos_monitor.py
```

### With Custom Configuration
```bash
python panos_monitor.py --host https://192.168.1.1 --interval 30 --port 8080
```

### Console Output Example
```
2025-10-16 10:30:15 INFO Authenticating with PAN-OS device...
2025-10-16 10:30:16 INFO 🚀 Monitoring https://10.100.192.3 every 60s
2025-10-16 10:30:16 INFO 📊 Dashboard: http://localhost:8080
2025-10-16 10:30:16 INFO 💾 Data exports will be saved to ./output on exit
2025-10-16 10:30:17 INFO [   1] 🖥️  CPU: M= 12.5% DP=  8.3% | 🌐 THR:   245.7 Mbps | 📦 PPS:      45230 | 🔋 PBUF:  2.1%
2025-10-16 10:31:17 INFO [   2] 🖥️  CPU: M= 15.2% DP= 11.7% | 🌐 THR:   312.4 Mbps | 📦 PPS:      52104 | 🔋 PBUF:  3.4%
```

## Web Dashboard

Access the enhanced real-time dashboard at `http://localhost:8080` (or your configured port).

### Dashboard Features
- **Live Metrics Cards**: Current values with color-coded status indicators
- **Interactive Charts**: 
  - CPU Usage (Management and Data Plane)
  - Network Throughput
  - Packet Buffer Utilization
  - Packets per Second
- **Customizable Time Range**: View last 50, 100, 200, or 500 data points
- **Auto-Refresh Toggle**: Enable/disable automatic updates
- **Manual Refresh**: Force immediate data update
- **Responsive Design**: Works on desktop and mobile devices

### API Endpoints
- `GET /`: Main dashboard interface
- `GET /metrics`: JSON array of all collected data points (last 500)
- `GET /stats`: System statistics and configuration

## Data Plane CPU Aggregation Modes

The script calculates a single CPU utilization value from multiple data processors and cores:

### Mean (Default)
```
Average CPU across ALL cores on ALL DPs
Best for: Overall system health monitoring
```

### Max
```
Highest loaded core across all DPs
Best for: Identifying bottlenecks and hotspots
```

### P95
```
95th percentile across all cores
Best for: Capacity planning (ignores transient spikes)
```

### Example Calculation
For a firewall with 2 DPs, each with 4 cores:
- **dp0 cores**: [5%, 12%, 8%, 3%]
- **dp1 cores**: [45%, 67%, 23%, 15%]

Results:
- **Mean**: 22.3% (average of all 8 cores)
- **Max**: 67% (hottest core)
- **P95**: ~60% (95th percentile)

## Metrics Explained

### Management CPU
- **Source**: `show system resources` (top output)
- **Components**: User + System time percentage
- **Note**: Uses CPU average values from top command

### Data Plane CPU
- **Source**: `show running resource-monitor minute`
- **Method**: Uses **maximum** CPU values per core (not average)
- **Aggregation**: Configurable via `DP_AGGREGATION`
- **Auto-Detection**: Discovers all DPs and cores dynamically

### Packet Buffer
- **Source**: `show running resource-monitor minute`
- **Method**: Uses **maximum** buffer utilization (not average)
- **Purpose**: Captures real buffer spikes during traffic bursts

### Throughput & PPS
- **Source**: `show session info`
- **Metrics**: Total kbps (converted to Mbps) and packets per second

## Output Files

On graceful shutdown (CTRL+C), the script generates:

### Data Exports (in OUTPUT_DIR)
- **CSV**: `panos_stats.csv` - Append mode, includes headers
- **XLSX**: `panos_stats.xlsx` - Excel workbook with 'stats' sheet
- **TXT**: `panos_stats.txt` - Plain text format

### Visualizations (if enabled)
- `throughput_total.png` - Network throughput over time
- `pps_total.png` - Packets per second over time
- `packet_buffer_live.png` - Buffer utilization trend
- `mgmt_cpu.png` - Management plane CPU
- `dp_cpu.png` - Data plane CPU

### Debug Files (if XML logging enabled)
- `raw_xml/*.xml` - Timestamped API responses
- Automatic cleanup based on retention policy

## Data Structure

Each collected data point includes:

```python
{
    "timestamp": "2025-10-16T14:30:15.123456+00:00",  # UTC ISO format
    "cpu_user": 8.5,              # Management CPU user %
    "cpu_system": 4.2,            # Management CPU system %
    "cpu_idle": 87.3,             # Management CPU idle %
    "mgmt_cpu": 12.7,             # Management CPU total (user + system)
    "data_plane_cpu": 23.4,       # Data plane CPU (aggregated)
    "throughput_mbps_total": 456.8,  # Total throughput in Mbps
    "pps_total": 78234.0,         # Packets per second
    "pbuf_util_percent": 3.2      # Packet buffer utilization %
}
```

## XML Debug Logging

Enable detailed API response capture for troubleshooting:

```bash
# Enable in .env
SAVE_RAW_XML=true
XML_RETENTION_HOURS=24

# Or via command line
python panos_monitor.py --save-xml --xml-retention 48
```

**Files created:**
- `output/raw_xml/20251016T143015Z_system_resources.xml`
- `output/raw_xml/20251016T143015Z_resource_monitor.xml`
- `output/raw_xml/20251016T143015Z_session_info.xml`

**Automatic cleanup**: Old files are removed every 10 polls based on retention hours.

## Security Considerations

### SSL/TLS Verification
By default, SSL verification is enabled. To disable (not recommended for production):
```bash
VERIFY_SSL=false
# or
python panos_monitor.py --no-verify
```

### Credentials
- Store credentials in `.env` file (add to `.gitignore`)
- Use environment variables in production
- Consider using API key rotation
- Restrict API user permissions to read-only operations

### Required API Permissions
The script requires read-only access to:
- `show system resources`
- `show running resource-monitor`
- `show session info`

## Troubleshooting

### Connection Issues
```
RuntimeError: Keygen HTTP error
```
- Verify `PAN_HOST` URL is correct (include `https://`)
- Check firewall API is enabled
- Confirm username/password are correct
- Ensure network connectivity to firewall

### No Data Plane CPU
```
dp-cpu cores=0 mode=mean
```
- Check firewall model supports resource monitoring
- Verify API user has sufficient permissions
- Enable XML logging to inspect raw responses

### Web Dashboard Not Loading
```
FastAPI/uvicorn not installed; web dashboard disabled
```
- Install required dependencies: `pip install fastapi uvicorn`
- Check port is not in use: `netmap -an | grep 8080`
- Try different port: `--port 8081`

### Charts Not Generated
```
matplotlib not installed; skipping visualization
```
- Install matplotlib: `pip install matplotlib`
- Ensure `VISUALIZATION=Yes` in configuration

## Performance Notes

- **Memory Usage**: Script keeps last 1000 data points in memory (~1MB)
- **Disk Usage**: CSV/XLSX files grow indefinitely (manual cleanup recommended)
- **API Load**: Each poll makes 3 API calls (minimal impact on firewall)
- **Poll Interval**: Minimum 1 second, recommended 15-60 seconds

## Known Limitations

- Does not support HA pair aggregation (monitor each peer separately)
- No alerting/notification system (export data to external monitoring)
- Web dashboard does not persist across restarts (exports only on exit)
- Maximum 1000 data points retained in memory for dashboard

## Contributing

This is a standalone monitoring tool. To extend functionality:
- Add new metrics by implementing additional parser functions
- Enhance dashboard with additional Chart.js visualizations
- Integrate with external monitoring platforms (Prometheus, InfluxDB, etc.)

## License

This script is provided as-is for monitoring Palo Alto Networks firewalls. Refer to your PAN-OS licensing for API usage terms.

## Support

For issues related to:
- **PAN-OS API**: Consult Palo Alto Networks documentation
- **Script functionality**: Check XML debug logs and verify API responses
- **Python dependencies**: Ensure all required packages are installed

## Version History

- **Latest**: Enhanced CPU/buffer calculations using maximum values, improved web dashboard, XML retention management
- Dynamic core detection for all firewall models
- Flexible aggregation modes for data plane CPU
- Real-time web dashboard with Chart.js
- Multiple export formats with on-exit generation

---

**Quick Start:**
```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env with your firewall details

# 4. Run
python panos_monitor.py

# 5. View dashboard
# Open http://localhost:8080 in browser

# 6. Stop (CTRL+C)
# Data automatically exported to ./output/

# 7. Deactivate virtual environment when done
deactivate
```