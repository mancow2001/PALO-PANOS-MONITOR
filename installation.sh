#!/bin/bash
#
# PAN-OS Multi-Firewall Monitor - Installation Script (Fixed for Ubuntu 22.04+)
# Supports Red Hat/CentOS/Rocky/AlmaLinux and Ubuntu/Debian systems
# Creates daemon service running under dedicated non-root user
#
# Usage:
#   sudo ./installation.sh              # Install
#   sudo ./installation.sh --uninstall  # Uninstall
#   sudo ./installation.sh -u           # Uninstall (short)
#   dzdo ./installation.sh              # Install (with Centrify)
#   dzdo ./installation.sh --uninstall  # Uninstall (with Centrify)
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

# Detect elevation command (sudo or dzdo)
detect_elevation_cmd() {
    if command -v dzdo >/dev/null 2>&1; then
        ELEVATION_CMD="dzdo"
        print_info "Detected Centrify dzdo for privilege escalation"
    elif command -v sudo >/dev/null 2>&1; then
        ELEVATION_CMD="sudo"
        print_info "Using sudo for privilege escalation"
    else
        ELEVATION_CMD=""
    fi
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        detect_elevation_cmd
        if [[ -n "$ELEVATION_CMD" ]]; then
            print_error "This script must be run as root or with $ELEVATION_CMD"
            echo "Usage: $ELEVATION_CMD $0"
        else
            print_error "This script must be run as root"
            echo "No sudo or dzdo found. Please run as root or install sudo/dzdo."
        fi
        exit 1
    fi
    
    # Set elevation command for use in script
    detect_elevation_cmd
}

# Detect OS and package manager with more detailed RHEL detection
detect_os() {
    if [[ -f /etc/redhat-release ]]; then
        OS="redhat"
        
        # Get RHEL version for specific handling
        if grep -q "release 7" /etc/redhat-release; then
            RHEL_VERSION="7"
        elif grep -q "release 8" /etc/redhat-release; then
            RHEL_VERSION="8"
        elif grep -q "release 9" /etc/redhat-release; then
            RHEL_VERSION="9"
        else
            RHEL_VERSION="unknown"
        fi
        
        if command -v dnf >/dev/null 2>&1; then
            PKG_MGR="dnf"
        else
            PKG_MGR="yum"
        fi
        
        print_info "Detected Red Hat-based system (version $RHEL_VERSION) using $PKG_MGR"
        
    elif [[ -f /etc/debian_version ]]; then
        OS="debian"
        PKG_MGR="apt"
        
        # Detect Ubuntu version for PEP 668 handling
        if command -v lsb_release >/dev/null 2>&1; then
            UBUNTU_VERSION=$(lsb_release -rs 2>/dev/null || echo "unknown")
            print_info "Detected Debian-based system (Ubuntu $UBUNTU_VERSION) using apt"
        else
            UBUNTU_VERSION="unknown"
            print_info "Detected Debian-based system using apt"
        fi
    else
        print_error "Unsupported operating system"
        print_info "This script supports Red Hat/CentOS/Rocky/AlmaLinux and Ubuntu/Debian"
        exit 1
    fi
}

# Enable required repositories for RHEL/CentOS
enable_repositories() {
    if [[ "$OS" == "redhat" ]]; then
        print_info "Enabling required repositories..."
        
        case "$RHEL_VERSION" in
            "7")
                # RHEL/CentOS 7
                if command -v subscription-manager >/dev/null 2>&1; then
                    # RHEL 7
                    subscription-manager repos --enable=rhel-7-server-optional-rpms || print_warning "Could not enable optional repos (may not be needed)"
                else
                    # CentOS 7 - install EPEL
                    if ! rpm -qa | grep -q epel-release; then
                        yum install -y epel-release
                    fi
                fi
                ;;
            "8")
                # RHEL/CentOS/Rocky/Alma 8
                if command -v subscription-manager >/dev/null 2>&1; then
                    # RHEL 8
                    subscription-manager repos --enable=rhel-8-for-x86_64-appstream-rpms || print_warning "Could not enable appstream repos"
                    subscription-manager repos --enable=codeready-builder-for-rhel-8-x86_64-rpms || print_warning "Could not enable codeready-builder"
                else
                    # Rocky/Alma/CentOS 8
                    if command -v dnf >/dev/null 2>&1; then
                        dnf config-manager --enable powertools 2>/dev/null || \
                        dnf config-manager --enable PowerTools 2>/dev/null || \
                        dnf config-manager --enable crb 2>/dev/null || \
                        print_warning "Could not enable powertools/CRB repository"
                    fi
                    
                    # Install EPEL if available
                    if ! rpm -qa | grep -q epel-release; then
                        $PKG_MGR install -y epel-release || print_warning "EPEL not available"
                    fi
                fi
                ;;
            "9")
                # RHEL/Rocky/Alma 9
                if command -v subscription-manager >/dev/null 2>&1; then
                    # RHEL 9
                    subscription-manager repos --enable=rhel-9-for-x86_64-appstream-rpms || print_warning "Could not enable appstream repos"
                    subscription-manager repos --enable=codeready-builder-for-rhel-9-x86_64-rpms || print_warning "Could not enable codeready-builder"
                else
                    # Rocky/Alma 9
                    if command -v dnf >/dev/null 2>&1; then
                        dnf config-manager --enable crb 2>/dev/null || print_warning "Could not enable CRB repository"
                    fi
                    
                    # Install EPEL if available
                    if ! rpm -qa | grep -q epel-release; then
                        $PKG_MGR install -y epel-release || print_warning "EPEL not available"
                    fi
                fi
                ;;
        esac
        
        print_success "Repository configuration completed"
    fi
}

# Install system dependencies with RHEL-specific packages and PEP 668 compliance
install_system_deps() {
    print_info "Installing system dependencies..."
    
    if [[ "$OS" == "redhat" ]]; then
        # Update package cache
        $PKG_MGR makecache
        
        # Install development tools
        if [[ "$RHEL_VERSION" == "7" ]]; then
            # RHEL/CentOS 7 packages
            $PKG_MGR groupinstall -y "Development Tools"
            $PKG_MGR install -y python3 python3-pip python3-devel \
                               openssl-devel libffi-devel sqlite-devel \
                               systemd curl wget gcc gcc-c++ make \
                               zlib-devel bzip2-devel readline-devel \
                               xz-devel tk-devel
        else
            # RHEL/CentOS 8+ packages
            $PKG_MGR groupinstall -y "Development Tools"
            $PKG_MGR install -y python3 python3-pip python3-devel \
                               openssl-devel libffi-devel sqlite-devel \
                               systemd curl wget gcc gcc-c++ make \
                               zlib-devel bzip2-devel readline-devel \
                               xz-devel tk-devel python3-venv
        fi
        
        # Ensure python3-venv is available (sometimes missing on RHEL)
        if ! python3 -m venv --help >/dev/null 2>&1; then
            print_warning "python3-venv not working, trying alternative installation..."
            if [[ "$RHEL_VERSION" == "7" ]]; then
                $PKG_MGR install -y python3-venv || print_warning "python3-venv package not available"
            fi
        fi
        
    elif [[ "$OS" == "debian" ]]; then
        apt update
        
        # Install basic packages including python3-full for newer Ubuntu
        if [[ "$UBUNTU_VERSION" != "unknown" ]] && dpkg --compare-versions "$UBUNTU_VERSION" "ge" "22.04"; then
            print_info "Installing packages for Ubuntu 22.04+ (PEP 668 compliant)"
            apt install -y python3 python3-pip python3-venv python3-dev python3-full \
                           build-essential libssl-dev libffi-dev \
                           libsqlite3-dev systemd curl wget
        else
            # Older Ubuntu/Debian versions
            apt install -y python3 python3-pip python3-venv python3-dev \
                           build-essential libssl-dev libffi-dev \
                           libsqlite3-dev systemd curl wget
        fi
    fi
    
    # Verify Python 3 installation
    if ! command -v python3 >/dev/null 2>&1; then
        print_error "Python 3 not found after installation"
        exit 1
    fi
    
    # Don't upgrade pip globally due to PEP 668 - this will be handled in venv
    print_info "Skipping global pip upgrade (will be handled in virtual environment)"
    
    print_success "System dependencies installed"
    print_info "Python version: $(python3 --version)"
    
    # Test venv capability
    if python3 -m venv --help >/dev/null 2>&1; then
        print_success "Python venv module is available"
    else
        print_error "Python venv module not available - installation may fail"
    fi
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

# Create Python virtual environment with better error handling and PEP 668 compliance
create_venv() {
    print_info "Creating Python virtual environment..."
    
    # Test venv module first
    if ! python3 -m venv --help >/dev/null 2>&1; then
        print_error "Python venv module not available"
        print_info "Attempting to install python3-venv package..."
        
        if [[ "$OS" == "redhat" ]]; then
            $PKG_MGR install -y python3-venv || {
                print_error "Failed to install python3-venv package"
                print_info "Trying alternative: virtualenv"
                # Install virtualenv to system first, then use it
                if [[ "$RHEL_VERSION" == "7" ]]; then
                    # On RHEL 7, we might need to use the older method
                    python3 -m pip install --user virtualenv
                    if [[ -n "$ELEVATION_CMD" ]]; then
                        $ELEVATION_CMD -u "$SERVICE_USER" python3 -m virtualenv "$VENV_DIR"
                    else
                        su - "$SERVICE_USER" -s /bin/bash -c "python3 -m virtualenv '$VENV_DIR'"
                    fi
                else
                    # For newer RHEL, try package manager first
                    $PKG_MGR install -y python3-virtualenv || python3 -m pip install --user virtualenv
                    if [[ -n "$ELEVATION_CMD" ]]; then
                        $ELEVATION_CMD -u "$SERVICE_USER" python3 -m virtualenv "$VENV_DIR"
                    else
                        su - "$SERVICE_USER" -s /bin/bash -c "python3 -m virtualenv '$VENV_DIR'"
                    fi
                fi
                print_success "Virtual environment created using virtualenv"
                return
            }
        elif [[ "$OS" == "debian" ]]; then
            # For Ubuntu/Debian, python3-venv should already be installed
            print_error "python3-venv should be available on Debian-based systems"
            exit 1
        fi
    fi
    
    # Create virtual environment as service user
    print_info "Creating virtual environment using python3 -m venv..."
    if [[ -n "$ELEVATION_CMD" ]]; then
        $ELEVATION_CMD -u "$SERVICE_USER" python3 -m venv "$VENV_DIR"
    else
        su - "$SERVICE_USER" -s /bin/bash -c "python3 -m venv '$VENV_DIR'"
    fi
    
    # Verify virtual environment was created
    if [[ ! -f "$VENV_DIR/bin/python" ]]; then
        print_error "Virtual environment creation failed"
        exit 1
    fi
    
    # Upgrade pip in virtual environment (this is safe and recommended)
    print_info "Upgrading pip in virtual environment..."
    if [[ -n "$ELEVATION_CMD" ]]; then
        $ELEVATION_CMD -u "$SERVICE_USER" "$VENV_DIR/bin/python" -m pip install --upgrade pip
    else
        su - "$SERVICE_USER" -s /bin/bash -c "'$VENV_DIR/bin/python' -m pip install --upgrade pip"
    fi
    
    print_success "Virtual environment created and pip upgraded"
    print_info "Virtual env Python: $("$VENV_DIR/bin/python" --version)"
    print_info "Virtual env pip: $("$VENV_DIR/bin/pip" --version)"
}

# Install Python dependencies with better error handling
install_python_deps() {
    print_info "Installing Python dependencies..."
    
    # Check if requirements.txt exists in current directory and copy it
    if [[ -f "requirements.txt" ]]; then
        print_info "Using existing requirements.txt file"
        cp "requirements.txt" "$INSTALL_DIR/requirements.txt"
    else
        print_warning "requirements.txt not found in current directory, creating default one"
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
        print_info "Created default requirements.txt - you may want to customize it"
    fi
    
    # Set ownership of requirements file
    chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/requirements.txt"
    
    # Install dependencies with retry logic
    print_info "Installing Python packages (this may take a few minutes)..."
    
    # First, install wheel to help with compilation
    print_info "Installing wheel..."
    if [[ -n "$ELEVATION_CMD" ]]; then
        $ELEVATION_CMD -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install wheel
    else
        su - "$SERVICE_USER" -s /bin/bash -c "'$VENV_DIR/bin/pip' install wheel"
    fi
    
    # Install all dependencies at once (faster and handles dependencies better)
    print_info "Installing all requirements..."
    if [[ -n "$ELEVATION_CMD" ]]; then
        if ! $ELEVATION_CMD -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"; then
            print_warning "Bulk installation failed, trying individual packages..."
            # Fall back to individual installation
            while IFS= read -r requirement; do
                if [[ -n "$requirement" ]] && [[ ! "$requirement" =~ ^#.* ]]; then
                    print_info "Installing: $requirement"
                    if ! $ELEVATION_CMD -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install "$requirement"; then
                        print_warning "Failed to install $requirement, but continuing..."
                    fi
                fi
            done < "$INSTALL_DIR/requirements.txt"
        fi
    else
        if ! su - "$SERVICE_USER" -s /bin/bash -c "'$VENV_DIR/bin/pip' install -r '$INSTALL_DIR/requirements.txt'"; then
            print_warning "Bulk installation failed, trying individual packages..."
            # Fall back to individual installation
            while IFS= read -r requirement; do
                if [[ -n "$requirement" ]] && [[ ! "$requirement" =~ ^#.* ]]; then
                    print_info "Installing: $requirement"
                    if ! su - "$SERVICE_USER" -s /bin/bash -c "'$VENV_DIR/bin/pip' install '$requirement'"; then
                        print_warning "Failed to install $requirement, but continuing..."
                    fi
                fi
            done < "$INSTALL_DIR/requirements.txt"
        fi
    fi
    
    # Verify key packages are installed
    print_info "Verifying installation..."
    key_packages=("requests" "yaml" "pandas" "fastapi" "uvicorn")
    failed_packages=()
    
    for package in "${key_packages[@]}"; do
        if [[ -n "$ELEVATION_CMD" ]]; then
            if $ELEVATION_CMD -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "import $package" 2>/dev/null; then
                print_success "$package: OK"
            else
                print_warning "$package: Failed to import"
                failed_packages+=("$package")
            fi
        else
            if su - "$SERVICE_USER" -s /bin/bash -c "'$VENV_DIR/bin/python' -c 'import $package'" 2>/dev/null; then
                print_success "$package: OK"
            else
                print_warning "$package: Failed to import"
                failed_packages+=("$package")
            fi
        fi
    done
    
    if [[ ${#failed_packages[@]} -gt 0 ]]; then
        print_warning "Some packages failed to install: ${failed_packages[*]}"
        print_info "The application may still work with reduced functionality"
    fi
    
    print_success "Python dependencies installation completed"
}

# Copy application files
copy_application_files() {
    print_info "Copying application files..."
    
    # List of required files
    required_files=("main.py" "config.py" "database.py" "collectors.py" "web_dashboard.py" "interface_monitor.py")
    
    # Check if files exist in current directory
    for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            print_error "Required file not found: $file"
            print_info "Please ensure all application files are in the current directory"
            exit 1
        fi
    done
    
    # Copy Python files
    for file in "${required_files[@]}"; do
        cp "$file" "$INSTALL_DIR/"
        chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/$file"
        chmod 644 "$INSTALL_DIR/$file"
    done
    
    # Make main.py executable
    chmod 755 "$INSTALL_DIR/main.py"
    
    # Copy templates directory if it exists (REQUIRED for dashboard)
    if [[ -d "templates" ]]; then
        print_info "Copying templates directory..."
        
        # Remove old templates if they exist
        if [[ -d "$INSTALL_DIR/templates" ]]; then
            rm -rf "$INSTALL_DIR/templates"
        fi
        
        cp -r "templates" "$INSTALL_DIR/"
        chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/templates"
        find "$INSTALL_DIR/templates" -type f -exec chmod 644 {} \;
        find "$INSTALL_DIR/templates" -type d -exec chmod 755 {} \;
        
        # Verify critical template files exist
        if [[ -f "$INSTALL_DIR/templates/dashboard.html" ]]; then
            print_success "✓ dashboard.html found"
        else
            print_error "dashboard.html not found in templates/"
            print_info "The web dashboard requires dashboard.html to function"
            exit 1
        fi
        
        if [[ -f "$INSTALL_DIR/templates/firewall_detail.html" ]]; then
            print_success "✓ firewall_detail.html found"
        else
            print_warning "firewall_detail.html not found (detail view may not work)"
        fi
        
        print_success "Templates directory copied successfully"
    else
        print_error "Templates directory not found!"
        print_info "The web dashboard requires a 'templates' directory with HTML files"
        print_info "Please ensure the templates directory exists in the current directory"
        exit 1
    fi
    
    # Copy any additional resource files
    additional_files=("requirements.txt" "README.md" "LICENSE")
    for file in "${additional_files[@]}"; do
        if [[ -f "$file" ]]; then
            cp "$file" "$INSTALL_DIR/"
            chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/$file"
            chmod 644 "$INSTALL_DIR/$file"
            print_info "Copied additional file: $file"
        fi
    done
    
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
    poll_interval: 30  # Recommended: 15-30 seconds for throughput

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
    print_info "Recommended poll_interval: 15-30 seconds for capturing traffic bursts"
}

# Create systemd service with proper PATH
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
Environment=PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=$INSTALL_DIR
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
ReadWritePaths=$DATA_DIR $LOG_DIR $CONFIG_DIR $INSTALL_DIR/templates
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
    
    # Create elevation wrapper function
    local elevation_wrapper=""
    if [[ -n "$ELEVATION_CMD" ]]; then
        elevation_wrapper="ELEVATION_CMD=\"$ELEVATION_CMD\""
    else
        elevation_wrapper='
# Detect elevation command
if command -v dzdo >/dev/null 2>&1; then
    ELEVATION_CMD="dzdo"
elif command -v sudo >/dev/null 2>&1; then
    ELEVATION_CMD="sudo"
else
    ELEVATION_CMD=""
fi'
    fi
    
    # Status script
    cat > "/usr/local/bin/${SERVICE_NAME}-status" << EOF
#!/bin/bash
$elevation_wrapper

echo "=== PAN-OS Monitor Service Status ==="
systemctl status $SERVICE_NAME --no-pager -l
echo
echo "=== Recent Logs ==="
journalctl -u $SERVICE_NAME --no-pager -n 20
echo
echo "=== Web Dashboard ==="
echo "Access the dashboard at: http://\$(hostname -I | awk '{print \$1}'):8080"
echo
echo "=== Performance Tips ==="
echo "For best throughput monitoring, use poll_interval: 15-30 seconds"
echo "Current config: $CONFIG_DIR/config.yaml"
EOF
    
    # Control script
    cat > "/usr/local/bin/${SERVICE_NAME}-control" << EOF
#!/bin/bash
$elevation_wrapper

# Function to run commands with appropriate elevation
run_elevated() {
    if [[ \$EUID -eq 0 ]]; then
        # Already root
        "\$@"
    elif [[ -n "\$ELEVATION_CMD" ]]; then
        # Use detected elevation command
        "\$ELEVATION_CMD" "\$@"
    else
        echo "Error: No elevation command available (sudo/dzdo) and not running as root"
        exit 1
    fi
}

case "\$1" in
    start)
        run_elevated systemctl start $SERVICE_NAME
        ;;
    stop)
        run_elevated systemctl stop $SERVICE_NAME
        ;;
    restart)
        run_elevated systemctl restart $SERVICE_NAME
        ;;
    status)
        ${SERVICE_NAME}-status
        ;;
    logs)
        journalctl -u $SERVICE_NAME -f
        ;;
    config)
        if [[ \$EUID -eq 0 ]]; then
            \${EDITOR:-nano} $CONFIG_DIR/config.yaml
        elif [[ -n "\$ELEVATION_CMD" ]]; then
            \$ELEVATION_CMD \${EDITOR:-nano} $CONFIG_DIR/config.yaml
        else
            echo "Error: Root privileges required to edit configuration"
            echo "Try: \${ELEVATION_CMD:-sudo} \${EDITOR:-nano} $CONFIG_DIR/config.yaml"
            exit 1
        fi
        ;;
    install-deps)
        echo "Reinstalling Python dependencies..."
        if [[ -n "\$ELEVATION_CMD" ]]; then
            \$ELEVATION_CMD -u $SERVICE_USER $VENV_DIR/bin/pip install -r $INSTALL_DIR/requirements.txt
        else
            echo "Error: Elevation command required"
            exit 1
        fi
        ;;
    test-connection)
        echo "Testing firewall connections..."
        if [[ -n "\$ELEVATION_CMD" ]]; then
            \$ELEVATION_CMD -u $SERVICE_USER $VENV_DIR/bin/python $INSTALL_DIR/main.py --test-config $CONFIG_DIR/config.yaml
        else
            echo "Error: Elevation command required"
            exit 1
        fi
        ;;
    *)
        echo "Usage: \$0 {start|stop|restart|status|logs|config|install-deps|test-connection}"
        echo
        echo "Commands:"
        echo "  start           Start the service"
        echo "  stop            Stop the service"
        echo "  restart         Restart the service"
        echo "  status          Show service status and recent logs"
        echo "  logs            Follow service logs in real-time"
        echo "  config          Edit configuration file"
        echo "  install-deps    Reinstall Python dependencies"
        echo "  test-connection Test firewall connections"
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
    enable_repositories
    
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
    echo "  3. For optimal throughput monitoring, use poll_interval: 15-30 seconds"
    echo "  4. Start the service: systemctl start $SERVICE_NAME"
    echo "  5. Check status: ${SERVICE_NAME}-status"
    echo "  6. Access dashboard: http://$(hostname -I | awk '{print $1}'):8080"
    echo
    print_warning "IMPORTANT: Use poll_interval of 15-30 seconds to avoid missing traffic bursts!"
    echo
    print_info "Installed files:"
    echo "  - Application: $INSTALL_DIR"
    echo "  - Configuration: $CONFIG_DIR"
    echo "  - Data/Database: $DATA_DIR"
    echo "  - Logs: $LOG_DIR"
    echo "  - Templates: $INSTALL_DIR/templates"
    echo
    print_success "✓ Web dashboard templates installed and verified"
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
    if [[ -n "$ELEVATION_CMD" ]]; then
        if ! $ELEVATION_CMD -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "import sys; print('Python OK')" >/dev/null 2>&1; then
            print_error "Python environment not working"
            return 1
        fi
    else
        if ! su - "$SERVICE_USER" -s /bin/bash -c "'$VENV_DIR/bin/python' -c 'import sys; print(\"Python OK\")'" >/dev/null 2>&1; then
            print_error "Python environment not working"
            return 1
        fi
    fi
    
    # Check if main application can import
    if [[ -n "$ELEVATION_CMD" ]]; then
        if ! $ELEVATION_CMD -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "import sys; sys.path.append('$INSTALL_DIR'); import main" >/dev/null 2>&1; then
            print_error "Application import failed"
            return 1
        fi
    else
        if ! su - "$SERVICE_USER" -s /bin/bash -c "'$VENV_DIR/bin/python' -c 'import sys; sys.path.append(\"$INSTALL_DIR\"); import main'" >/dev/null 2>&1; then
            print_error "Application import failed"
            return 1
        fi
    fi
    
    # Check if templates directory exists and has required files
    if [[ ! -d "$INSTALL_DIR/templates" ]]; then
        print_error "Templates directory not found at $INSTALL_DIR/templates"
        print_warning "Web dashboard will not work without templates"
        return 1
    else
        print_success "Templates directory found: $INSTALL_DIR/templates"
        
        # Verify critical template files
        if [[ -f "$INSTALL_DIR/templates/dashboard.html" ]]; then
            print_success "✓ dashboard.html present"
        else
            print_error "✗ dashboard.html missing (REQUIRED)"
            return 1
        fi
        
        if [[ -f "$INSTALL_DIR/templates/firewall_detail.html" ]]; then
            print_success "✓ firewall_detail.html present"
        else
            print_warning "✗ firewall_detail.html missing (detail view won't work)"
        fi
        
        # List all templates
        local template_count=$(find "$INSTALL_DIR/templates" -type f -name "*.html" | wc -l)
        print_info "Found $template_count HTML template(s)"
    fi
    
    print_success "Installation test passed"
    print_info "Virtual environment pip packages:"
    if [[ -n "$ELEVATION_CMD" ]]; then
        $ELEVATION_CMD -u "$SERVICE_USER" "$VENV_DIR/bin/pip" list | head -10
    fi
    
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
            echo "Privilege Escalation:"
            echo "  Run with sudo:  sudo $0"
            echo "  Run with dzdo:  dzdo $0"
            echo
            echo "This version fixes PEP 668 compliance issues on Ubuntu 22.04+"
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
