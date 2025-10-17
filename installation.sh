#!/bin/bash
#
# PAN-OS Multi-Firewall Monitor - Installation Script
# Supports Red Hat/CentOS/Rocky/AlmaLinux and Ubuntu/Debian systems
# Creates daemon service running under dedicated non-root user
#
# Usage:
#   sudo ./installation.sh              # Install
#   sudo ./installation.sh --uninstall  # Uninstall
#   sudo ./installation.sh -u           # Uninstall (short)
#

set -e  # Exit on any error

# Configuration
SERVICE_NAME="panos-monitor"
SERVICE_USER="panos"
SERVICE_GROUP="panos"
INSTALL_DIR="/opt/panos-monitor"
CONFIG_DIR="/etc/panos-monitor"
LOG_DIR="/var/log/panos-monitor"
DATA_DIR="/var/lib/panos-monitor"
VENV_DIR="$INSTALL_DIR/venv"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo "==========================================================="
    echo "  PAN-OS Multi-Firewall Monitor - Installation Script"
    echo "==========================================================="
    echo
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root or with sudo"
        echo "Usage: sudo $0"
        exit 1
    fi
}

# Detect OS and package manager
detect_os() {
    if [[ -f /etc/redhat-release ]]; then
        OS="redhat"
        if command -v dnf >/dev/null 2>&1; then
            PKG_MGR="dnf"
        else
            PKG_MGR="yum"
        fi
        print_info "Detected Red Hat-based system using $PKG_MGR"
    elif [[ -f /etc/debian_version ]]; then
        OS="debian"
        PKG_MGR="apt"
        print_info "Detected Debian-based system using apt"
    else
        print_error "Unsupported operating system"
        print_info "This script supports Red Hat/CentOS/Rocky/AlmaLinux and Ubuntu/Debian"
        exit 1
    fi
}

# Install system dependencies
install_system_deps() {
    print_info "Installing system dependencies..."
    
    if [[ "$OS" == "redhat" ]]; then
        $PKG_MGR update -y
        $PKG_MGR groupinstall -y "Development Tools"
        $PKG_MGR install -y python3 python3-pip python3-venv python3-devel \
                           openssl-devel libffi-devel sqlite-devel \
                           systemd curl wget
    elif [[ "$OS" == "debian" ]]; then
        apt update
        apt install -y python3 python3-pip python3-venv python3-dev \
                       build-essential libssl-dev libffi-dev \
                       libsqlite3-dev systemd curl wget
    fi
    
    print_success "System dependencies installed"
}

# Create service user and group
create_service_user() {
    print_info "Creating service user and group..."
    
    # Create group if it doesn't exist
    if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
        groupadd --system "$SERVICE_GROUP"
        print_success "Created group: $SERVICE_GROUP"
    else
        print_info "Group $SERVICE_GROUP already exists"
    fi
    
    # Create user if it doesn't exist
    if ! getent passwd "$SERVICE_USER" >/dev/null 2>&1; then
        useradd --system --gid "$SERVICE_GROUP" --home-dir "$INSTALL_DIR" \
                --shell /bin/false --comment "PAN-OS Monitor Service" "$SERVICE_USER"
        print_success "Created user: $SERVICE_USER"
    else
        print_info "User $SERVICE_USER already exists"
    fi
}

# Create directory structure
create_directories() {
    print_info "Creating directory structure..."
    
    # Create directories
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p "$DATA_DIR"
    
    # Set ownership
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR"
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$DATA_DIR"
    chown -R root:root "$CONFIG_DIR"
    chmod 755 "$CONFIG_DIR"
    
    print_success "Directory structure created"
}

# Create Python virtual environment
create_venv() {
    print_info "Creating Python virtual environment..."
    
    # Create virtual environment as service user
    sudo -u "$SERVICE_USER" python3 -m venv "$VENV_DIR"
    
    # Upgrade pip
    sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install --upgrade pip
    
    print_success "Virtual environment created"
}

# Install Python dependencies
install_python_deps() {
    print_info "Installing Python dependencies..."
    
    # Create requirements.txt if it doesn't exist
    cat > "$INSTALL_DIR/requirements.txt" << 'EOF'
requests>=2.25.0
PyYAML>=6.0
pandas>=1.3.0
openpyxl>=3.0.9
matplotlib>=3.5.0
fastapi>=0.68.0
uvicorn[standard]>=0.15.0
jinja2>=3.0.0
python-dotenv>=0.19.0
EOF
    
    # Install dependencies
    sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
    
    print_success "Python dependencies installed"
}

# Copy application files
copy_application_files() {
    print_info "Copying application files..."
    
    # List of required files
    required_files=("main.py" "config.py" "database.py" "collectors.py" "web_dashboard.py")
    
    # Check if files exist in current directory
    for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            print_error "Required file not found: $file"
            print_info "Please ensure all application files are in the current directory"
            exit 1
        fi
    done
    
    # Copy files
    for file in "${required_files[@]}"; do
        cp "$file" "$INSTALL_DIR/"
        chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/$file"
        chmod 644 "$INSTALL_DIR/$file"
    done
    
    # Make main.py executable
    chmod 755 "$INSTALL_DIR/main.py"
    
    print_success "Application files copied"
}

# Create configuration file
create_config() {
    print_info "Creating configuration file..."
    
    cat > "$CONFIG_DIR/config.yaml" << 'EOF'
# PAN-OS Multi-Firewall Monitor Configuration
# Edit this file to configure your firewalls

global:
  # Storage and output settings
  output_dir: "/var/lib/panos-monitor/output"
  output_type: "CSV"
  database_path: "/var/lib/panos-monitor/data/metrics.db"
  
  # Web interface settings
  web_dashboard: true
  web_port: 8080
  
  # Visualization and debugging
  visualization: true
  save_raw_xml: false
  xml_retention_hours: 24
  log_level: "INFO"

# Configure your firewalls here
firewalls:
  # Example firewall configuration (disabled by default)
  example_fw:
    host: "https://192.168.1.1"
    username: "admin"
    password: "your_password_here"
    verify_ssl: false
    enabled: false  # Set to true after configuring
    poll_interval: 60

# Add more firewalls as needed:
#  production_fw:
#    host: "https://10.0.0.1"
#    username: "monitor_user"
#    password: "secure_password"
#    verify_ssl: true
#    enabled: true
#    poll_interval: 30
EOF
    
    # Set permissions (readable by service user, writable by root)
    chown root:"$SERVICE_GROUP" "$CONFIG_DIR/config.yaml"
    chmod 640 "$CONFIG_DIR/config.yaml"
    
    print_success "Configuration file created at $CONFIG_DIR/config.yaml"
    print_warning "Please edit $CONFIG_DIR/config.yaml to configure your firewalls"
}

# Create systemd service
create_service() {
    print_info "Creating systemd service..."
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=PAN-OS Multi-Firewall Monitor
Documentation=https://github.com/your-repo/panos-monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/python main.py --config $CONFIG_DIR/config.yaml
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=panos-monitor

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR $LOG_DIR $CONFIG_DIR
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload systemd and enable service
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    
    print_success "Systemd service created and enabled"
}

# Create log rotation
create_logrotate() {
    print_info "Setting up log rotation..."
    
    cat > "/etc/logrotate.d/$SERVICE_NAME" << EOF
$LOG_DIR/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 $SERVICE_USER $SERVICE_GROUP
    postrotate
        systemctl reload $SERVICE_NAME > /dev/null 2>&1 || true
    endscript
}
EOF
    
    print_success "Log rotation configured"
}

# Create helper scripts
create_helper_scripts() {
    print_info "Creating helper scripts..."
    
    # Status script
    cat > "/usr/local/bin/${SERVICE_NAME}-status" << EOF
#!/bin/bash
echo "=== PAN-OS Monitor Service Status ==="
systemctl status $SERVICE_NAME --no-pager -l
echo
echo "=== Recent Logs ==="
journalctl -u $SERVICE_NAME --no-pager -n 20
echo
echo "=== Web Dashboard ==="
echo "Access the dashboard at: http://\$(hostname -I | awk '{print \$1}'):8080"
EOF
    
    # Control script
    cat > "/usr/local/bin/${SERVICE_NAME}-control" << EOF
#!/bin/bash
case "\$1" in
    start)
        systemctl start $SERVICE_NAME
        ;;
    stop)
        systemctl stop $SERVICE_NAME
        ;;
    restart)
        systemctl restart $SERVICE_NAME
        ;;
    status)
        ${SERVICE_NAME}-status
        ;;
    logs)
        journalctl -u $SERVICE_NAME -f
        ;;
    config)
        \${EDITOR:-nano} $CONFIG_DIR/config.yaml
        ;;
    *)
        echo "Usage: \$0 {start|stop|restart|status|logs|config}"
        exit 1
        ;;
esac
EOF
    
    # Make scripts executable
    chmod 755 "/usr/local/bin/${SERVICE_NAME}-status"
    chmod 755 "/usr/local/bin/${SERVICE_NAME}-control"
    
    print_success "Helper scripts created"
    print_info "Use '${SERVICE_NAME}-control' to manage the service"
    print_info "Use '${SERVICE_NAME}-status' to check service status"
}

# Install function
install() {
    print_header
    print_info "Starting installation of PAN-OS Multi-Firewall Monitor..."
    
    check_root
    detect_os
    
    # Stop service if it's running
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        print_info "Stopping existing service..."
        systemctl stop "$SERVICE_NAME"
    fi
    
    install_system_deps
    create_service_user
    create_directories
    create_venv
    install_python_deps
    copy_application_files
    create_config
    create_service
    create_logrotate
    create_helper_scripts
    
    print_success "Installation completed successfully!"
    echo
    print_info "Next steps:"
    echo "  1. Edit configuration: $CONFIG_DIR/config.yaml"
    echo "  2. Configure your firewalls and set enabled: true"
    echo "  3. Start the service: systemctl start $SERVICE_NAME"
    echo "  4. Check status: ${SERVICE_NAME}-status"
    echo "  5. Access dashboard: http://$(hostname -I | awk '{print $1}'):8080"
    echo
    print_info "Service management commands:"
    echo "  - Start:   systemctl start $SERVICE_NAME"
    echo "  - Stop:    systemctl stop $SERVICE_NAME"
    echo "  - Status:  systemctl status $SERVICE_NAME"
    echo "  - Logs:    journalctl -u $SERVICE_NAME -f"
    echo "  - Control: ${SERVICE_NAME}-control {start|stop|restart|status|logs|config}"
}

# Uninstall function
uninstall() {
    print_header
    print_info "Starting uninstallation of PAN-OS Multi-Firewall Monitor..."
    
    check_root
    
    # Stop and disable service
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        print_info "Stopping service..."
        systemctl stop "$SERVICE_NAME"
    fi
    
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        print_info "Disabling service..."
        systemctl disable "$SERVICE_NAME"
    fi
    
    # Remove service file
    if [[ -f "$SERVICE_FILE" ]]; then
        print_info "Removing systemd service..."
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
    fi
    
    # Remove helper scripts
    print_info "Removing helper scripts..."
    rm -f "/usr/local/bin/${SERVICE_NAME}-status"
    rm -f "/usr/local/bin/${SERVICE_NAME}-control"
    
    # Remove logrotate configuration
    if [[ -f "/etc/logrotate.d/$SERVICE_NAME" ]]; then
        print_info "Removing log rotation configuration..."
        rm -f "/etc/logrotate.d/$SERVICE_NAME"
    fi
    
    # Prompt for data removal
    echo
    read -p "Do you want to remove all data and configuration files? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Removing application files..."
        rm -rf "$INSTALL_DIR"
        rm -rf "$CONFIG_DIR"
        rm -rf "$LOG_DIR"
        rm -rf "$DATA_DIR"
        
        print_info "Removing service user and group..."
        if getent passwd "$SERVICE_USER" >/dev/null 2>&1; then
            userdel "$SERVICE_USER"
        fi
        if getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
            groupdel "$SERVICE_GROUP"
        fi
        
        print_success "Complete uninstallation finished"
    else
        print_info "Application files preserved:"
        print_info "  - Configuration: $CONFIG_DIR"
        print_info "  - Data: $DATA_DIR"
        print_info "  - Logs: $LOG_DIR"
        print_info "  - Application: $INSTALL_DIR"
        print_success "Service uninstallation finished (data preserved)"
    fi
}

# Test installation
test_installation() {
    print_info "Testing installation..."
    
    # Check if user exists
    if ! getent passwd "$SERVICE_USER" >/dev/null 2>&1; then
        print_error "Service user $SERVICE_USER not found"
        return 1
    fi
    
    # Check if directories exist
    for dir in "$INSTALL_DIR" "$CONFIG_DIR" "$LOG_DIR" "$DATA_DIR"; do
        if [[ ! -d "$dir" ]]; then
            print_error "Directory $dir not found"
            return 1
        fi
    done
    
    # Check if Python environment works
    if ! sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "import sys; print('Python OK')" >/dev/null 2>&1; then
        print_error "Python environment not working"
        return 1
    fi
    
    # Check if main application can import
    if ! sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "import sys; sys.path.append('$INSTALL_DIR'); import main" >/dev/null 2>&1; then
        print_error "Application import failed"
        return 1
    fi
    
    print_success "Installation test passed"
    return 0
}

# Main execution
main() {
    case "${1:-}" in
        -u|--uninstall)
            uninstall
            ;;
        --test)
            test_installation
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo
            echo "Options:"
            echo "  (no args)     Install PAN-OS Multi-Firewall Monitor"
            echo "  -u, --uninstall   Uninstall the service"
            echo "  --test        Test existing installation"
            echo "  -h, --help    Show this help message"
            echo
            ;;
        "")
            install
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
